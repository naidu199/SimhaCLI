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
from services import sessions, settings, undo
from services.sessions import SessionError
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
            "sessions/list": self._sessions_list,
            "sessions/history": self._sessions_history,
            "sessions/resume": self._sessions_resume,
            "sessions/new": self._sessions_new,
            "sessions/delete": self._sessions_delete,
            "config/get": self._config_get,
            "model/set": self._model_set,
            "approval/set": self._approval_set,
            "credentials/set": self._credentials_set,
            "undo/list": self._undo_list,
            "undo/revert": self._undo_revert,
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
    # Sessions (saved chats)
    # ------------------------------------------------------------------
    def _require_idle(self, action: str) -> None:
        if self.turn_running:
            raise ProtocolError(TURN_RUNNING, f"Can't {action} while a turn is running")

    @staticmethod
    def _session_ref(params: dict[str, Any]) -> str:
        ref = params.get("id")
        if not isinstance(ref, str) or not ref.strip():
            raise ProtocolError(INVALID_PARAMS, "id must be a non-empty string")
        return ref.strip()

    async def _sessions_list(self, params: dict[str, Any]) -> dict[str, Any]:
        limit = params.get("limit")
        if limit is not None and (isinstance(limit, bool) or not isinstance(limit, int) or limit < 1):
            raise ProtocolError(INVALID_PARAMS, "limit must be a positive integer")
        current_id = self.agent.session.session_id
        return {
            "sessions": [
                {
                    "id": s["session_id"],
                    "title": s.get("title"),
                    "createdAt": s.get("created_at"),
                    "updatedAt": s.get("updated_at"),
                    "messageCount": s.get("message_count", 0),
                    "cwd": s.get("cwd"),
                    "model": s.get("model"),
                    "source": s.get("source"),
                    "isCurrent": s["session_id"] == current_id,
                }
                for s in sessions.list_sessions(limit)
            ]
        }

    async def _sessions_history(self, params: dict[str, Any]) -> dict[str, Any]:
        if params.get("id") is None:
            session = self.agent.session
            return {
                "id": session.session_id,
                "title": session.to_snapshot().title,
                "messages": sessions.transcript(session.context_manager.get_messages()),
            }
        try:
            snapshot = sessions.load(self._session_ref(params))
        except SessionError as e:
            raise ProtocolError(INVALID_PARAMS, str(e)) from e
        return {
            "id": snapshot.session_id,
            "title": snapshot.title,
            "messages": sessions.transcript(snapshot.messages),
        }

    async def _sessions_resume(self, params: dict[str, Any]) -> dict[str, Any]:
        self._require_idle("switch chats")
        try:
            snapshot, warning = sessions.resume(self.agent, self.config, self._session_ref(params))
        except SessionError as e:
            raise ProtocolError(INVALID_PARAMS, str(e)) from e
        result = {
            "sessionId": snapshot.session_id,
            "title": snapshot.title,
            "messages": sessions.transcript(snapshot.messages),
        }
        if warning:
            result["warning"] = warning
        return result

    async def _sessions_new(self, params: dict[str, Any]) -> dict[str, Any]:
        self._require_idle("start a new chat")
        sessions.start_new(self.agent)
        return {"sessionId": self.agent.session.session_id}

    async def _sessions_delete(self, params: dict[str, Any]) -> dict[str, Any]:
        try:
            sessions.delete(self._session_ref(params), self.agent.session.session_id)
        except SessionError as e:
            raise ProtocolError(INVALID_PARAMS, str(e)) from e
        return {"deleted": True}

    # ------------------------------------------------------------------
    # Settings
    # ------------------------------------------------------------------
    async def _config_get(self, params: dict[str, Any]) -> dict[str, Any]:
        return {
            "model": self.config.model.name,
            "approval": self.config.approval.value,
            "approvalPolicies": [p.value for p in type(self.config.approval)],
            "cwd": str(self.config.cwd),
            "autoSaveSessions": self.config.auto_save_sessions,
            "apiBaseUrl": self.config.get_api_base_url(),
            "hasApiKey": self.config.get_api_key() is not None,
        }

    async def _model_set(self, params: dict[str, Any]) -> dict[str, Any]:
        self._require_idle("change the model")
        name = params.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ProtocolError(INVALID_PARAMS, "name must be a non-empty string")
        saved = settings.set_model(self.agent, self.config, name)
        return self._with_save_result({"model": self.config.model.name}, saved)

    async def _approval_set(self, params: dict[str, Any]) -> dict[str, Any]:
        policy = params.get("policy")
        if not isinstance(policy, str):
            raise ProtocolError(INVALID_PARAMS, "policy must be a string")
        try:
            applied, saved = settings.set_approval(self.agent, self.config, policy)
        except ValueError as e:
            raise ProtocolError(INVALID_PARAMS, str(e)) from e
        return self._with_save_result({"approval": applied.value}, saved)

    @staticmethod
    def _with_save_result(result: dict[str, Any], saved: settings.SaveResult) -> dict[str, Any]:
        if saved.path:
            result["savedTo"] = str(saved.path)
        if saved.error:
            result["saveError"] = saved.error
        return result

    async def _credentials_set(self, params: dict[str, Any]) -> dict[str, Any]:
        self._require_idle("change credentials")
        api_key = params.get("apiKey")
        base_url = params.get("baseUrl")
        for name, value in (("apiKey", api_key), ("baseUrl", base_url)):
            if value is not None and not isinstance(value, str):
                raise ProtocolError(INVALID_PARAMS, f"{name} must be a string")
        if not (api_key or "").strip() and not (base_url or "").strip():
            raise ProtocolError(INVALID_PARAMS, "Provide apiKey and/or baseUrl")
        await settings.set_credentials(self.agent, self.config, api_key=api_key, base_url=base_url)
        self._needs_credentials = self.config.get_api_key() is None
        return {"needsCredentials": self._needs_credentials}

    # ------------------------------------------------------------------
    # Undo
    # ------------------------------------------------------------------
    async def _undo_list(self, params: dict[str, Any]) -> dict[str, Any]:
        return {
            "changes": [
                {"index": c.index, "path": c.path, "isNewFile": c.is_new_file}
                for c in undo.list_changes(self.agent)
            ]
        }

    async def _undo_revert(self, params: dict[str, Any]) -> dict[str, Any]:
        self._require_idle("undo changes")
        if params.get("all") is True:
            outcomes = undo.revert_all(self.agent)
        else:
            index = params.get("index")
            if isinstance(index, bool) or not isinstance(index, int):
                raise ProtocolError(INVALID_PARAMS, "Provide index (integer) or all: true")
            try:
                outcomes = [undo.revert(self.agent, index)]
            except IndexError as e:
                raise ProtocolError(INVALID_PARAMS, str(e)) from e
        return {
            "reverted": [o.path for o in outcomes if o.done],
            "skipped": [
                {"path": o.path, "status": o.status, "reason": o.reason}
                for o in outcomes
                if not o.done
            ],
            "remaining": len(undo.list_changes(self.agent)),
        }

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
