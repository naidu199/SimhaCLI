"""Saved-chat operations shared by the CLI commands and ``simhacli serve``.

Functions return data and raise ``SessionError`` with a user-facing message;
callers decide how to present it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent.state import SessionSnapshot, StateManager, message_text


class SessionError(Exception):
    """A user-facing problem with a session reference or operation."""


def list_sessions(limit: int | None = None) -> list[dict[str, Any]]:
    """Saved chats, newest first (see ``StateManager.list_sessions``)."""
    sessions = StateManager().list_sessions()
    return sessions if limit is None else sessions[:limit]


def resolve(ref: str) -> str:
    """Session id for a list number (1 = newest), full id or unique id prefix."""
    session_id = StateManager().resolve_session_id(str(ref))
    if session_id is None:
        raise SessionError(
            f"No saved session matches '{ref}'. Use /sessions to list them."
        )
    return session_id


def load(ref: str) -> SessionSnapshot:
    session_id = resolve(ref)
    snapshot = StateManager().load_session(session_id)
    if snapshot is None:
        raise SessionError(f"Session does not exist: {ref}")
    return snapshot


def _tool_call_summary(call: dict[str, Any]) -> dict[str, Any]:
    function = call.get("function") or {}
    raw = function.get("arguments") or ""
    try:
        arguments: Any = json.loads(raw) if raw else {}
    except ValueError:
        arguments = raw
    return {"name": function.get("name", "tool"), "arguments": arguments}


def transcript(
    messages: list[dict[str, Any]], last_turns: int | None = None
) -> list[dict[str, Any]]:
    """User/assistant messages as ``{role, text, toolCalls}``.

    Tool results and the system prompt are left out; ``last_turns`` keeps
    only the messages from the last N user messages onwards.
    """
    messages = [m for m in messages if m.get("role") in ("user", "assistant")]
    if last_turns is not None:
        user_indexes = [i for i, m in enumerate(messages) if m.get("role") == "user"]
        if len(user_indexes) > last_turns:
            messages = messages[user_indexes[-last_turns] :]

    return [
        {
            "role": msg["role"],
            "text": message_text(msg.get("content")).strip(),
            "toolCalls": [_tool_call_summary(c) for c in msg.get("tool_calls") or []],
        }
        for msg in messages
    ]


def has_user_messages(messages: list[dict[str, Any]]) -> bool:
    return any(m.get("role") == "user" for m in messages)


def save_current(agent: Any, config: Any) -> bool:
    """Persist the active chat (if auto-save is on and it has messages)."""
    session = agent.session
    if session and session.has_conversation() and config.auto_save_sessions:
        StateManager().save_session(session.to_snapshot())
        return True
    return False


def switch_to(agent: Any, config: Any, snapshot: SessionSnapshot) -> str | None:
    """Continue ``snapshot`` in the agent's session.

    Saves the current chat first. Returns a warning when the chat was started
    in a different directory than the agent is working in.
    """
    save_current(agent, config)
    agent.session.restore_snapshot(snapshot)
    agent.clear_undo_stack()

    if snapshot.cwd and snapshot.cwd != str(Path(config.cwd).resolve()):
        return (
            f"This chat was started in {snapshot.cwd}; "
            f"the agent is working in {config.cwd}."
        )
    return None


def resume(agent: Any, config: Any, ref: str) -> tuple[SessionSnapshot, str | None]:
    """Load ``ref`` and switch to it. Returns (snapshot, cwd warning)."""
    snapshot = load(ref)
    if snapshot.session_id == agent.session.session_id:
        return snapshot, None
    return snapshot, switch_to(agent, config, snapshot)


def start_new(agent: Any) -> bool:
    """Start a new chat. Returns True if the previous one had messages."""
    had_conversation = agent.session.has_conversation()
    agent.session.start_new()
    return had_conversation


def delete(ref: str, current_session_id: str | None) -> str:
    """Delete a saved chat (not the one in use). Returns its id."""
    session_id = resolve(ref)
    if session_id == current_session_id:
        raise SessionError(
            "That is the current chat. Use /clear first, then delete it."
        )
    StateManager().delete_session(session_id)
    return session_id
