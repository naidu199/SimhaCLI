"""Convert agent objects into JSON-safe dicts for the protocol."""

from __future__ import annotations

import dataclasses
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

from agent.events import AgentEvent, AgentEventType
from tools.base import FileDiff, ToolConfirmation


def to_jsonable(value: Any) -> Any:
    """Recursively convert a value into JSON-serializable data."""
    if value is None or isinstance(value, (bool, int, float, str)):
        # str subclasses (e.g. OriginalContent) become plain strings
        return str(value) if isinstance(value, str) and type(value) is not str else value
    if isinstance(value, Enum):
        return to_jsonable(value.value)
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, FileDiff):
        return value.to_diff()
    if isinstance(value, dict):
        return {str(k): to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [to_jsonable(v) for v in value]
    if isinstance(value, bytes):
        return f"<{len(value)} bytes>"
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: to_jsonable(getattr(value, field.name))
            for field in dataclasses.fields(value)
        }
    return str(value)


def event_to_dict(event: AgentEvent) -> dict[str, Any]:
    """``{"type": ..., "data": ...}`` for an ``agent/event`` notification."""
    data = dict(event.data)
    if event.type == AgentEventType.TOOL_CALL_COMPLETE:
        # The flattened fields (output, error, diff, ...) carry the same
        # information; the raw ToolResult also holds full file contents.
        data.pop("result", None)
    return {"type": event.type.value, "data": to_jsonable(data)}


def confirmation_to_dict(confirmation: ToolConfirmation) -> dict[str, Any]:
    """Payload for an ``approval/request`` sent to the client."""
    return {
        "tool": confirmation.tool_name,
        "description": confirmation.description,
        "params": to_jsonable(confirmation.params),
        "command": confirmation.command,
        "paths": [str(path) for path in confirmation.affected_paths],
        "diff": confirmation.diff.to_diff() if confirmation.diff else None,
        "fileChange": file_change_to_dict(confirmation.diff),
        "isDangerous": confirmation.is_dangerous,
    }


def file_change_to_dict(diff: FileDiff | None) -> dict[str, Any] | None:
    """Full before/after contents, so a client can show a real diff view."""
    if diff is None:
        return None
    return {
        "path": str(diff.path),
        "oldContent": str(diff.old_content or ""),
        "newContent": str(diff.new_content or ""),
        "isNewFile": bool(diff.is_new_file),
    }
