"""Undo command: /undo."""

from .base import Command, CommandResult
from typing import Any
from pathlib import Path

from rich.markup import escape


def _was_new_file(old_content: str | None) -> bool:
    """Return True if the undo entry represents a file that did not exist before.

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


class UndoCommand(Command):
    @property
    def name(self) -> str:
        return "/undo"

    async def execute(self, args: str, context: dict[str, Any]) -> CommandResult:
        agent = context.get("agent")
        console = context.get("console")
        if not agent or not console:
            return CommandResult(success=False, message="No active agent")

        stack = agent.get_undo_stack()
        if not stack:
            console.print("[warning]Nothing to undo.[/warning]")
            return CommandResult(success=True)

        console.print("\n[bold]Files changed (select to undo):[/bold]")
        for i, (path_str, old_content, _) in enumerate(stack, 1):
            file_type = "(new)" if _was_new_file(old_content) else "(edited)"
            try:
                rel_path = Path(path_str).relative_to(context["config"].cwd)
            except ValueError:
                rel_path = path_str
            console.print(
                f"  [cyan]\\[{i}][/cyan] {escape(str(rel_path))} [dim]{file_type}[/dim]"
            )

        console.print("  [cyan]\\[a][/cyan] Undo all")
        console.print("  [cyan]\\[q][/cyan] Cancel")

        try:
            choice = (
                await context["tui"].get_multiline_input("\nEnter choice: ")
            ) or ""
            choice = choice.strip().lower()
        except (KeyboardInterrupt, EOFError):
            console.print("[dim]Cancelled.[/dim]")
            return CommandResult(success=True)

        if choice in ("q", ""):
            console.print("[dim]Cancelled.[/dim]")
            return CommandResult(success=True)

        if choice == "a":
            # Snapshot first: _undo_single_file re-appends skipped entries,
            # so popping until empty would loop forever.
            items = list(stack)
            stack.clear()
            for item in reversed(items):
                self._undo_single_file(agent, context, item)
            return CommandResult(success=True)

        try:
            idx = int(choice)
            if 1 <= idx <= len(stack):
                item = stack.pop(idx - 1)
                self._undo_single_file(agent, context, item)
                return CommandResult(success=True)
            else:
                console.print(f"[error]Invalid choice: {escape(choice)}[/error]")
        except ValueError:
            console.print(f"[error]Invalid choice: {escape(choice)}[/error]")

        return CommandResult(success=True)

    def get_help(self) -> str:
        return "Undo file changes made in the last operation"

    def _undo_single_file(
        self, agent: Any, context: dict[str, Any], item: tuple[str, str, str]
    ) -> None:
        path_str, old_content, new_content = item
        console = context["console"]
        stack = agent.get_undo_stack()
        safe_path = escape(str(path_str))
        try:
            file_path = Path(path_str)
            if not file_path.exists():
                console.print(f"[warning]File {safe_path} no longer exists.[/warning]")
                return

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
                console.print(
                    f"[warning]File {safe_path} has been modified since the last edit. "
                    f"Undo skipped to avoid data loss.[/warning]"
                )
                stack.append((path_str, old_content, new_content))
            elif _was_new_file(old_content):
                file_path.unlink()
                console.print(
                    f"[success]Undo: deleted newly created file {safe_path}[/success]"
                )
            else:
                # Write exactly what was there before (original encoding and
                # line endings, no newline translation).
                file_path.write_bytes(str(old_content).encode(encoding))
                console.print(f"[success]Undo: reverted {safe_path}[/success]")
        except Exception as e:
            console.print(f"[error]Undo failed: {escape(str(e))}[/error]")
