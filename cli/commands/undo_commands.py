"""Undo command: /undo."""

from .base import Command, CommandResult
from typing import Any
from pathlib import Path

from rich.markup import escape

from services import undo
from services.undo import RevertOutcome


def _print_outcome(console: Any, outcome: RevertOutcome) -> None:
    safe_path = escape(outcome.path)
    if outcome.status == "reverted":
        console.print(f"[success]Undo: reverted {safe_path}[/success]")
    elif outcome.status == "deleted":
        console.print(f"[success]Undo: deleted newly created file {safe_path}[/success]")
    elif outcome.status == "missing":
        console.print(f"[warning]File {safe_path} no longer exists.[/warning]")
    elif outcome.status == "skipped":
        console.print(
            f"[warning]File {safe_path} has been modified since the last edit. "
            f"Undo skipped to avoid data loss.[/warning]"
        )
    else:
        console.print(f"[error]Undo failed: {escape(outcome.reason or '')}[/error]")


class UndoCommand(Command):
    @property
    def name(self) -> str:
        return "/undo"

    async def execute(self, args: str, context: dict[str, Any]) -> CommandResult:
        agent = context.get("agent")
        console = context.get("console")
        if not agent or not console:
            return CommandResult(success=False, message="No active agent")

        changes = undo.list_changes(agent)
        if not changes:
            console.print("[warning]Nothing to undo.[/warning]")
            return CommandResult(success=True)

        console.print("\n[bold]Files changed (select to undo):[/bold]")
        for change in changes:
            file_type = "(new)" if change.is_new_file else "(edited)"
            try:
                rel_path = Path(change.path).relative_to(context["config"].cwd)
            except ValueError:
                rel_path = change.path
            console.print(
                f"  [cyan]\\[{change.index}][/cyan] {escape(str(rel_path))} [dim]{file_type}[/dim]"
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
            for outcome in undo.revert_all(agent):
                _print_outcome(console, outcome)
            return CommandResult(success=True)

        try:
            _print_outcome(console, undo.revert(agent, int(choice)))
        except (ValueError, IndexError):
            console.print(f"[error]Invalid choice: {escape(choice)}[/error]")

        return CommandResult(success=True)

    def get_help(self) -> str:
        return "Undo file changes made in the last operation"
