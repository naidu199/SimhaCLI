"""Reverting the agent's file changes, shared by ``/undo`` and ``simhacli serve``.

The agent's undo stack holds ``(path, old_content, new_content)`` entries for
the files changed in the latest turn. Entries that can't be reverted safely
(the file changed since the agent's edit) are kept on the stack.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

UndoItem = tuple[str, str, str]


@dataclass
class UndoChange:
    index: int  # 1-based position on the stack
    path: str
    is_new_file: bool


@dataclass
class RevertOutcome:
    path: str
    status: str  # "reverted" | "deleted" | "skipped" | "missing" | "failed"
    reason: str | None = None

    @property
    def done(self) -> bool:
        return self.status in ("reverted", "deleted")


def was_new_file(old_content: str | None) -> bool:
    """True if the entry represents a file that did not exist before.

    Tools record old_content as ``tools.base.OriginalContent`` which carries an
    ``existed`` flag, so an originally-empty file is not mistaken for a new one.
    Plain strings (unknown origin) fall back to the legacy ``""`` heuristic.
    """
    if old_content is None:
        return True
    existed = getattr(old_content, "existed", None)
    if existed is not None:
        return not existed
    return old_content == ""


def list_changes(agent: Any) -> list[UndoChange]:
    return [
        UndoChange(index=i, path=str(path), is_new_file=was_new_file(old))
        for i, (path, old, _new) in enumerate(agent.get_undo_stack(), 1)
    ]


def revert_item(item: UndoItem) -> RevertOutcome:
    """Restore one file to its content before the agent's change."""
    path_str, old_content, new_content = item
    file_path = Path(path_str)
    try:
        if not file_path.exists():
            return RevertOutcome(path_str, "missing", "File no longer exists")

        encoding = getattr(old_content, "encoding", None) or "utf-8"
        try:
            with file_path.open("r", encoding="utf-8", newline="") as f:
                current = f.read()
        except UnicodeDecodeError:
            with file_path.open("r", encoding="latin-1", newline="") as f:
                current = f.read()

        # Tolerate newline translation (e.g. text-mode writes on Windows).
        unchanged = current == new_content or current.replace(
            "\r\n", "\n"
        ) == new_content.replace("\r\n", "\n")
        if not unchanged:
            return RevertOutcome(
                path_str,
                "skipped",
                "File has been modified since the agent's edit; undo skipped to avoid data loss",
            )
        if was_new_file(old_content):
            file_path.unlink()
            return RevertOutcome(path_str, "deleted")
        # Write exactly what was there before (original encoding and line
        # endings, no newline translation).
        file_path.write_bytes(str(old_content).encode(encoding))
        return RevertOutcome(path_str, "reverted")
    except Exception as e:
        return RevertOutcome(path_str, "failed", str(e))


def revert(agent: Any, index: int) -> RevertOutcome:
    """Revert the change at 1-based ``index``. Raises IndexError if invalid."""
    stack = agent.get_undo_stack()
    if not 1 <= index <= len(stack):
        raise IndexError(f"No change number {index}")
    item = stack.pop(index - 1)
    outcome = revert_item(item)
    if outcome.status == "skipped":
        stack.append(item)
    return outcome


def revert_all(agent: Any) -> list[RevertOutcome]:
    """Revert every change, newest first. Skipped entries stay on the stack."""
    stack = agent.get_undo_stack()
    items = list(stack)
    stack.clear()
    outcomes = []
    for item in reversed(items):
        outcome = revert_item(item)
        if outcome.status == "skipped":
            stack.append(item)
        outcomes.append(outcome)
    return outcomes
