"""Newline-delimited JSON messaging over stdin/stdout.

One JSON object per line, in both directions:

- request:      {"id": 1, "method": "chat/send", "params": {...}}
- response:     {"id": 1, "result": {...}}  or  {"id": 1, "error": {...}}
- notification: {"method": "agent/event", "params": {...}}

The server also sends requests to the client (e.g. ``approval/request``);
those use string ids ("s1", "s2", ...) so they never collide with the
client's ids.
"""

from __future__ import annotations

import asyncio
import itertools
import json
import logging
import os
import sys
import threading
from dataclasses import dataclass
from typing import Any, BinaryIO

logger = logging.getLogger(__name__)

# JSON-RPC style error codes (see SIMHACLI_SERVER_PLAN.md, section 3)
PARSE_ERROR = -32700
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
SERVER_ERROR = -32000
NOT_INITIALIZED = -32001
TURN_RUNNING = -32002
CREDENTIALS_MISSING = -32003


class ProtocolError(Exception):
    """Raised by a handler to answer a request with a specific error code."""

    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class ConnectionClosed(Exception):
    """The client went away before answering a server-initiated request."""


@dataclass
class IncomingRequest:
    id: Any
    method: str
    params: dict[str, Any]


@dataclass
class IncomingNotification:
    method: str
    params: dict[str, Any]


def take_over_stdio() -> tuple[BinaryIO, BinaryIO]:
    """Reserve the process's real stdin/stdout for the protocol.

    Returns private (input, output) streams for protocol traffic. Afterwards:
    - fd 1 points at stderr, so print(), Rich output and child processes that
      inherit stdout can never corrupt the protocol stream;
    - fd 0 points at the null device, so child processes (e.g. the shell
      tool) can't read protocol messages meant for the server.
    """
    protocol_in = os.fdopen(os.dup(sys.stdin.fileno()), "rb", buffering=0)
    protocol_out = os.fdopen(os.dup(sys.stdout.fileno()), "wb", buffering=0)

    sys.stdout.flush()
    os.dup2(sys.stderr.fileno(), sys.stdout.fileno())
    sys.stdout = sys.stderr

    devnull_fd = os.open(os.devnull, os.O_RDONLY)
    os.dup2(devnull_fd, sys.stdin.fileno())
    os.close(devnull_fd)

    return protocol_in, protocol_out


class JsonLineConnection:
    def __init__(self, input_stream: BinaryIO, output_stream: BinaryIO) -> None:
        self._input = input_stream
        self._output = output_stream
        self._write_lock = threading.Lock()
        self._incoming: asyncio.Queue[Any] = asyncio.Queue()
        self._pending: dict[str, asyncio.Future] = {}
        self._ids = itertools.count(1)
        self._loop: asyncio.AbstractEventLoop | None = None
        self._closed = False

    # ------------------------------------------------------------------
    # Reading
    # ------------------------------------------------------------------
    def start(self) -> None:
        """Start reading the input stream on a background thread.

        A thread (rather than asyncio pipes) works the same on Windows.
        """
        self._loop = asyncio.get_running_loop()
        thread = threading.Thread(
            target=self._read_lines, name="simhacli-protocol-reader", daemon=True
        )
        thread.start()

    def _read_lines(self) -> None:
        try:
            while True:
                line = self._input.readline()
                if not line:
                    break
                self._loop.call_soon_threadsafe(self._incoming.put_nowait, line)
        except (OSError, ValueError) as e:
            logger.error(f"Protocol input failed: {e}")
        finally:
            self._loop.call_soon_threadsafe(self._incoming.put_nowait, None)

    async def next_message(self) -> IncomingRequest | IncomingNotification | None:
        """Next request or notification from the client; None when the input closes.

        Responses to server-initiated requests are consumed here and resolve
        the matching ``request()`` call. Malformed lines are answered with a
        parse error and skipped.
        """
        while True:
            line = await self._incoming.get()
            if line is None:
                self._close_pending()
                return None

            line = line.strip()
            if not line:
                continue
            try:
                message = json.loads(line)
            except (ValueError, UnicodeDecodeError) as e:
                self.send_error(None, PARSE_ERROR, f"Invalid JSON: {e}")
                continue
            if not isinstance(message, dict):
                self.send_error(None, PARSE_ERROR, "Message must be a JSON object")
                continue

            if "method" not in message:
                self._resolve_response(message)
                continue

            method = message.get("method")
            params = message.get("params")
            if not isinstance(method, str):
                self.send_error(message.get("id"), INVALID_PARAMS, "method must be a string")
                continue
            if params is None:
                params = {}
            if not isinstance(params, dict):
                self.send_error(message.get("id"), INVALID_PARAMS, "params must be an object")
                continue

            if "id" in message and message["id"] is not None:
                return IncomingRequest(message["id"], method, params)
            return IncomingNotification(method, params)

    def _resolve_response(self, message: dict[str, Any]) -> None:
        future = self._pending.pop(str(message.get("id")), None)
        if future is None or future.done():
            logger.warning(f"Response for unknown request id: {message.get('id')!r}")
            return
        if "error" in message and message["error"] is not None:
            error = message["error"] if isinstance(message["error"], dict) else {}
            future.set_exception(
                ProtocolError(
                    error.get("code", SERVER_ERROR),
                    error.get("message", "Client returned an error"),
                )
            )
        else:
            future.set_result(message.get("result"))

    def _close_pending(self) -> None:
        self._closed = True
        for future in self._pending.values():
            if not future.done():
                future.set_exception(ConnectionClosed("Client disconnected"))
        self._pending.clear()

    # ------------------------------------------------------------------
    # Writing (thread-safe: log records may arrive from other threads)
    # ------------------------------------------------------------------
    def _write(self, message: dict[str, Any]) -> None:
        data = json.dumps(message, ensure_ascii=False, default=str).encode("utf-8")
        with self._write_lock:
            try:
                self._output.write(data + b"\n")
                self._output.flush()
            except (OSError, ValueError):
                # Client closed its end; nothing useful left to do
                pass

    def send_result(self, request_id: Any, result: Any) -> None:
        self._write({"id": request_id, "result": result})

    def send_error(self, request_id: Any, code: int, message: str) -> None:
        self._write({"id": request_id, "error": {"code": code, "message": message}})

    def notify(self, method: str, params: dict[str, Any]) -> None:
        self._write({"method": method, "params": params})

    async def request(self, method: str, params: dict[str, Any]) -> Any:
        """Send a request to the client and wait for its result."""
        if self._closed:
            raise ConnectionClosed("Client disconnected")
        request_id = f"s{next(self._ids)}"
        future = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        try:
            self._write({"id": request_id, "method": method, "params": params})
            return await future
        finally:
            self._pending.pop(request_id, None)


class ProtocolLogHandler(logging.Handler):
    """Forward log records to the client as ``server/log`` notifications."""

    def __init__(self, connection: JsonLineConnection, level: int = logging.WARNING) -> None:
        super().__init__(level)
        self._connection = connection

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self._connection.notify(
                "server/log",
                {"level": record.levelname.lower(), "message": self.format(record)},
            )
        except Exception:
            self.handleError(record)
