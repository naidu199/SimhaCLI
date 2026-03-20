"""Undo command: /undo."""

from .base import Command, CommandResult
from typing import Any
from pathlib import Path


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
            file_type = "(new)" if old_content == "" else "(edited)"
            try:
                rel_path = Path(path_str).relative_to(context["config"].cwd)
            except ValueError:
                rel_path = path_str
            console.print(f"  [cyan][{i}][/cyan] {rel_path} [dim]{file_type}[/dim]")

        console.print("  [cyan]\\[a][/cyan] Undo all")
        console.print("  [cyan]\\[q][/cyan] Cancel")

        try:
            choice = await context["tui"].get_multiline_input("\nEnter choice: ")
            choice = choice.strip().lower()
        except (KeyboardInterrupt, EOFError):
            console.print("[dim]Cancelled.[/dim]")
            return CommandResult(success=True)

        if choice in ("q", ""):
            console.print("[dim]Cancelled.[/dim]")
            return CommandResult(success=True)

        if choice == "a":
            while agent.has_undo_changes():
                self._undo_single_file(agent, context, stack.pop())
            return CommandResult(success=True)

        try:
            idx = int(choice)
            if 1 <= idx <= len(stack):
                item = stack.pop(idx - 1)
                self._undo_single_file(agent, context, item)
                return CommandResult(success=True)
            else:
                console.print(f"[error]Invalid choice: {choice}[/error]")
        except ValueError:
            console.print(f"[error]Invalid choice: {choice}[/error]")

        return CommandResult(success=True)

    def get_help(self) -> str:
        return "Undo file changes made in the last operation"

    def _undo_single_file(
        self, agent: Any, context: dict[str, Any], item: tuple[str, str, str]
    ) -> None:
        path_str, old_content, new_content = item
        console = context["console"]
        stack = agent.get_undo_stack()
        try:
            file_path = Path(path_str)
            if old_content == "" and file_path.exists():
                file_path.unlink()
                console.print(
                    f"[success]Undo: deleted newly created file {path_str}[/success]"
                )
            elif file_path.exists():
                try:
                    current = file_path.read_text(encoding="utf-8")
                except UnicodeDecodeError:
                    current = file_path.read_text(encoding="latin-1")
                if current == new_content:
                    file_path.write_text(old_content, encoding="utf-8")
                    console.print(f"[success]Undo: reverted {path_str}[/success]")
                else:
                    console.print(
                        f"[warning]File {path_str} has been modified since the last edit. "
                        f"Undo skipped to avoid data loss.[/warning]"
                    )
                    stack.append((path_str, old_content, new_content))
            else:
                console.print(f"[warning]File {path_str} no longer exists.[/warning]")
        except Exception as e:
            console.print(f"[error]Undo failed: {e}[/error]")
