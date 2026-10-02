"""``simhacli serve``: run the agent behind the stdin/stdout JSON protocol.

See SIMHACLI_SERVER_PLAN.md for the protocol and design rules.
"""

from __future__ import annotations

import asyncio
import itertools
import logging
import re
import sys
from pathlib import Path
from typing import Any, Awaitable, Callable

from agent.agent import Agent
from agent.events import AgentEventType
from agent.state import StateManager
from config.config import Config
from config.loader import load_config
from server.attachments import build_message
from server.protocol import (
    CREDENTIALS_MISSING,
    INVALID_PARAMS,
    METHOD_NOT_FOUND,
    NOT_INITIALIZED,
    SERVER_ERROR,
    TURN_RUNNING,
    IncomingNotification,
    IncomingRequest,
    JsonLineConnection,
    ProtocolError,
    ProtocolLogHandler,
    take_over_stdio,
)
from server.serialization import confirmation_to_dict, event_to_dict
from tools.base import ToolConfirmation

logger = logging.getLogger(__name__)

PROTOCOL_VERSION = 1
CANCEL_WAIT_SECONDS = 15.0
_SOURCE_NAME = re.compile(r"[^a-z0-9_-]")


def _server_version() -> str:
    try:
        from importlib.metadata import version

        return version("simhacli")
    except Exception:
        return "unknown"


class AgentServer:
    def __init__(self, connection: JsonLineConnection, cwd: Path | None = None) -> None:
        self._conn = connection
        self._default_cwd = cwd
        self.config: Config | None = None
        self.agent: Agent | None = None
        self._needs_credentials = False
        self._source = "server"
        self._turn_ids = itertools.count(1)
        self._turn_id: str | None = None
        self._turn_task: asyncio.Task | None = None
        self._stopping = False

        self._handlers: dict[str, Callable[[dict[str, Any]], Awaitable[Any]]] = {
            "initialize": self._initialize,
            "chat/send": self._chat_send,
            "chat/cancel": self._chat_cancel,
            "shutdown": self._shutdown,
        }

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------
    async def serve(self) -> None:
        self._conn.start()
        try:
            while not self._stopping:
                message = await self._conn.next_message()
                if message is None:
                    break
                if isinstance(message, IncomingNotification):
                    logger.debug(f"Ignoring notification: {message.method}")
                    continue
                await self._dispatch(message)
        finally:
            await self._close()

    async def _dispatch(self, request: IncomingRequest) -> None:
        handler = self._handlers.get(request.method)
        if handler is None:
            self._conn.send_error(
                request.id, METHOD_NOT_FOUND, f"Unknown method: {request.method}"
            )
            return
        if request.method not in ("initialize", "shutdown") and self.agent is None:
            self._conn.send_error(request.id, NOT_INITIALIZED, "Call initialize first")
            return
        try:
            result = await handler(request.params)
        except ProtocolError as e:
            self._conn.send_error(request.id, e.code, e.message)
        except Exception as e:
            logger.exception(f"{request.method} failed")
            self._conn.send_error(request.id, SERVER_ERROR, f"{type(e).__name__}: {e}")
        else:
            self._conn.send_result(request.id, result)

    async def _close(self) -> None:
        await self._cancel_turn()
        if self.agent is not None:
            try:
                await self.agent.__aexit__(None, None, None)
            except Exception:
                logger.exception("Error while shutting down the agent")
            self.agent = None

    # ------------------------------------------------------------------
    # initialize
    # ------------------------------------------------------------------
    async def _initialize(self, params: dict[str, Any]) -> dict[str, Any]:
        if self.agent is None:
            cwd = self._resolve_cwd(params.get("cwd"))
            client_name = params.get("clientName")
            if isinstance(client_name, str) and client_name.strip():
                self._source = _SOURCE_NAME.sub("", client_name.strip().lower())[:32] or "server"

            # Never prompt on stdin: it belongs to the protocol
            config = load_config(cwd=cwd, prompt_api=False)
            self._needs_credentials = config.get_api_key() is None

            agent = Agent(config=config, confirmation_callback=self._request_approval)
            await agent.__aenter__()
            self.config = config
            self.agent = agent

        return {
            "serverVersion": _server_version(),
            "protocolVersion": PROTOCOL_VERSION,
            "cwd": str(self.config.cwd),
            "model": self.config.model.name,
            "approval": self.config.approval.value,
            "sessionId": self.agent.session.session_id,
            "needsCredentials": self._needs_credentials,
        }

    def _resolve_cwd(self, value: Any) -> Path:
        if value is None:
            return (self._default_cwd or Path.cwd()).resolve()
        if not isinstance(value, str) or not value.strip():
            raise ProtocolError(INVALID_PARAMS, "cwd must be a non-empty string")
        cwd = Path(value).expanduser().resolve()
        if not cwd.is_dir():
            raise ProtocolError(INVALID_PARAMS, f"cwd is not a directory: {value}")
        return cwd

    # ------------------------------------------------------------------
    # chat/send, chat/cancel
    # ------------------------------------------------------------------
    @property
    def turn_running(self) -> bool:
        return self._turn_task is not None and not self._turn_task.done()

    async def _chat_send(self, params: dict[str, Any]) -> dict[str, Any]:
        if self.turn_running:
            raise ProtocolError(TURN_RUNNING, "A turn is already running")
        if self._needs_credentials:
            raise ProtocolError(CREDENTIALS_MISSING, "No API key is configured")

        text = params.get("text")
        if not isinstance(text, str) or not text.strip():
            raise ProtocolError(INVALID_PARAMS, "text must be a non-empty string")
        message = build_message(
            text,
            params.get("attachments"),
            self.config.cwd,
            getattr(self.config.model, "supports_vision", True),
        )

        turn_id = f"t{next(self._turn_ids)}"
        self._turn_id = turn_id
        self._turn_task = asyncio.create_task(self._run_turn(turn_id, message))
        return {"turnId": turn_id}

    async def _run_turn(self, turn_id: str, message: str | list) -> None:
        agent = self.agent
        agent.clear_undo_stack()
        status = "completed"
        error: str | None = None
        events = agent.run(message)
        try:
            async for event in events:
                if event.type == AgentEventType.AGENT_ERROR and status == "completed":
                    status = "error"
                    error = event.data.get("message")
                self._conn.notify(
                    "agent/event", {"turnId": turn_id, **event_to_dict(event)}
                )
        except asyncio.CancelledError:
            status = "cancelled"
        except Exception as e:
            logger.exception("Turn failed")
            status = "error"
            error = f"{type(e).__name__}: {e}"
        finally:
            try:
                await events.aclose()
            except BaseException:
                pass
            self._autosave()
            finished: dict[str, Any] = {
                "turnId": turn_id,
                "status": status,
                "undoCount": agent.get_undo_count(),
            }
            if error:
                finished["error"] = error
            self._conn.notify("turn/finished", finished)

    async def _chat_cancel(self, params: dict[str, Any]) -> dict[str, Any]:
        turn_id = params.get("turnId")
        if not isinstance(turn_id, str):
            raise ProtocolError(INVALID_PARAMS, "turnId must be a string")
        if not self.turn_running or turn_id != self._turn_id:
            return {"cancelled": False}
        await self._cancel_turn()
        return {"cancelled": True}

    async def _cancel_turn(self) -> None:
        task = self._turn_task
        if task is None or task.done():
            return
        task.cancel()
        try:
            await asyncio.wait_for(asyncio.shield(task), CANCEL_WAIT_SECONDS)
        except asyncio.TimeoutError:
            logger.error("Turn did not stop within %.0f seconds", CANCEL_WAIT_SECONDS)
        except asyncio.CancelledError:
            pass

    def _autosave(self) -> None:
        if not self.config.auto_save_sessions or self.agent is None:
            return
        session = self.agent.session
        try:
            if session and session.has_conversation():
                StateManager().save_session(session.to_snapshot(source=self._source))
        except Exception:
            logger.exception("Could not save this chat")

    # ------------------------------------------------------------------
    # Approvals
    # ------------------------------------------------------------------
    async def _request_approval(self, confirmation: ToolConfirmation) -> bool:
        """Ask the client; anything but an explicit approval is a denial."""
        payload = confirmation_to_dict(confirmation)
        payload["turnId"] = self._turn_id
        try:
            result = await self._conn.request("approval/request", payload)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning(f"Approval request failed, denying: {e}")
            return False
        return isinstance(result, dict) and result.get("approved") is True

    # ------------------------------------------------------------------
    # shutdown
    # ------------------------------------------------------------------
    async def _shutdown(self, params: dict[str, Any]) -> dict[str, Any]:
        await self._close()
        self._stopping = True
        return {}


async def _serve(streams: tuple, cwd: Path | None) -> None:
    connection = JsonLineConnection(*streams)
    log_handler = ProtocolLogHandler(connection)
    logging.getLogger().addHandler(log_handler)
    try:
        await AgentServer(connection, cwd=cwd).serve()
    finally:
        logging.getLogger().removeHandler(log_handler)


def run_server(cwd: Path | None = None, verbose: bool = False) -> None:
    """Entry point for ``simhacli serve``."""
    # Must happen before anything can print to stdout or read stdin
    streams = take_over_stdio()
    logging.basicConfig(
        level=logging.INFO if verbose else logging.WARNING,
        stream=sys.stderr,
        format="%(levelname)s %(name)s: %(message)s",
    )
    try:
        asyncio.run(_serve(streams, cwd))
    except KeyboardInterrupt:
        pass
