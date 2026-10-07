"""Session commands: /save, /sessions, /history, /resume, /checkpoint, /restore."""

from datetime import datetime
from pathlib import Path
from typing import Any

from rich.markup import escape
from rich.text import Text

from .base import Command, CommandResult
from agent.state import StateManager, SessionSnapshot
from services import sessions
from services.sessions import SessionError

SESSIONS_LIST_LIMIT = 20
RESUME_PREVIEW_TURNS = 3
HISTORY_MESSAGE_MAX_CHARS = 4000


def _format_time(iso_value: str) -> str:
    try:
        value = datetime.fromisoformat(iso_value)
    except (TypeError, ValueError):
        return str(iso_value)
    if value.date() == datetime.now().date():
        return value.strftime("today %H:%M")
    return value.strftime("%Y-%m-%d %H:%M")


def _print_sessions(
    console: Any,
    sessions: list[dict[str, Any]],
    current_id: str | None,
    cwd: Path | None,
    limit: int | None,
) -> None:
    shown = sessions if limit is None else sessions[:limit]
    for index, s in enumerate(shown, 1):
        marker = "[success]*[/success]" if s["session_id"] == current_id else " "
        title = escape(s.get("title") or "(no messages)")
        line = (
            f" {marker} [cyan]{index:>2}[/cyan]  [dim]{s['session_id'][:8]}[/dim]  "
            f"{_format_time(s['updated_at'])}  [dim]{s.get('message_count', 0)} msgs[/dim]  "
            f"{title}"
        )
        if s.get("source") and s["source"] != "cli":
            line += f" [dim]({escape(s['source'])})[/dim]"
        if s.get("cwd") and cwd is not None and s["cwd"] != str(Path(cwd).resolve()):
            line += f"\n        [dim]{escape(s['cwd'])}[/dim]"
        console.print(line)
    if limit is not None and len(sessions) > limit:
        console.print(
            f"  [dim]… {len(sessions) - limit} older. Use /sessions all to see everything.[/dim]"
        )


def _print_transcript(
    console: Any,
    messages: list[dict[str, Any]],
    last_turns: int | None = None,
) -> None:
    """Print user/assistant messages; tool calls are summarised on one line."""
    for msg in sessions.transcript(messages, last_turns=last_turns):
        text = msg["text"]
        if len(text) > HISTORY_MESSAGE_MAX_CHARS:
            text = text[:HISTORY_MESSAGE_MAX_CHARS] + "\n… (truncated)"

        if msg["role"] == "user":
            console.print()
            console.print("[bold cyan]You[/bold cyan]")
            console.print(Text(text))
            continue

        if text:
            console.print("[bold magenta]SimhaCLI[/bold magenta]")
            console.print(Text(text))
        for call in msg["toolCalls"]:
            arguments = call["arguments"]
            if isinstance(arguments, dict):
                summary = ", ".join(f"{k}={str(v)[:40]}" for k, v in arguments.items())
            else:
                summary = str(arguments)[:80]
            console.print(Text(f"  ↳ {call['name']}({summary})", style="dim"))


def _switch_to_snapshot(
    agent: Any, config: Any, console: Any, snapshot: SessionSnapshot
) -> None:
    warning = sessions.switch_to(agent, config, snapshot)
    if warning:
        console.print(f"[warning]{escape(warning)}[/warning]")
    _print_transcript(console, snapshot.messages, last_turns=RESUME_PREVIEW_TURNS)
    console.print()


class SaveCommand(Command):
    @property
    def name(self) -> str:
        return "/save"

    async def execute(self, args: str, context: dict[str, Any]) -> CommandResult:
        agent = context.get("agent")
        console = context.get("console")
        if not agent or not console:
            return CommandResult(success=False, message="No active session")
        if not agent.session.has_conversation():
            return CommandResult(success=False, message="Nothing to save yet.")

        StateManager().save_session(agent.session.to_snapshot())
        console.print(f"[success]Session saved: {agent.session.session_id}[/success]")
        return CommandResult(success=True)

    def get_help(self) -> str:
        return "Save current session to disk (chats are also saved automatically)"


class SessionsCommand(Command):
    @property
    def name(self) -> str:
        return "/sessions"

    async def execute(self, args: str, context: dict[str, Any]) -> CommandResult:
        console = context.get("console")
        if not console:
            return CommandResult(success=False, message="Missing console")

        agent = context.get("agent")
        config = context.get("config")
        parts = args.split(maxsplit=1)
        subcommand = parts[0].lower() if parts else ""

        if subcommand == "delete":
            if len(parts) < 2:
                return CommandResult(
                    success=False, message="Usage: /sessions delete <number|id>"
                )
            current_id = agent.session.session_id if agent and agent.session else None
            try:
                session_id = sessions.delete(parts[1], current_id)
            except SessionError as e:
                return CommandResult(success=False, message=str(e))
            console.print(f"[success]Deleted session {session_id[:8]}[/success]")
            return CommandResult(success=True)

        saved = sessions.list_sessions()
        if not saved:
            console.print("[dim]No saved chats yet.[/dim]")
            return CommandResult(success=True)

        console.print("\n[bold]Saved chats[/bold] [dim](newest first)[/dim]")
        _print_sessions(
            console,
            saved,
            current_id=agent.session.session_id if agent and agent.session else None,
            cwd=config.cwd if config else None,
            limit=None if subcommand == "all" else SESSIONS_LIST_LIMIT,
        )
        console.print(
            "\n[dim]/resume <number|id> to continue · /history <number|id> to read · "
            "/sessions delete <number|id>[/dim]"
        )
        return CommandResult(success=True)

    def get_help(self) -> str:
        return "List saved chats. Usage: /sessions [all | delete <number|id>]"


class HistoryCommand(Command):
    @property
    def name(self) -> str:
        return "/history"

    async def execute(self, args: str, context: dict[str, Any]) -> CommandResult:
        agent = context.get("agent")
        console = context.get("console")
        if not console:
            return CommandResult(success=False, message="Missing console")

        if not args.strip():
            if not agent or not agent.session:
                return CommandResult(success=False, message="No active session")
            messages = agent.session.context_manager.get_messages()
            title = "Current chat"
        else:
            try:
                snapshot = sessions.load(args)
            except SessionError as e:
                return CommandResult(success=False, message=str(e))
            messages = snapshot.messages
            title = snapshot.title or snapshot.session_id[:8]

        console.print(f"\n[bold]{escape(title)}[/bold]")
        if not sessions.has_user_messages(messages):
            console.print("[dim]No messages yet.[/dim]")
            return CommandResult(success=True)
        _print_transcript(console, messages)
        console.print()
        return CommandResult(success=True)

    def get_help(self) -> str:
        return "Show a chat's messages. Usage: /history [number|id] (default: current chat)"


class ResumeCommand(Command):
    @property
    def name(self) -> str:
        return "/resume"

    async def execute(self, args: str, context: dict[str, Any]) -> CommandResult:
        agent = context.get("agent")
        config = context.get("config")
        console = context.get("console")
        if not agent or not config or not console:
            return CommandResult(success=False, message="Missing context")

        ref = args.strip()
        if not ref:
            saved = sessions.list_sessions()
            if not saved:
                return CommandResult(success=False, message="No saved chats yet.")
            console.print("\n[bold]Saved chats[/bold] [dim](newest first)[/dim]")
            _print_sessions(
                console,
                saved,
                current_id=agent.session.session_id,
                cwd=config.cwd,
                limit=SESSIONS_LIST_LIMIT,
            )
            tui = context.get("tui")
            if tui is None:
                return CommandResult(
                    success=False, message="Usage: /resume <number|id>"
                )
            ref = ((await tui.get_multiline_input("\nChat to resume (Enter to cancel): ")) or "").strip()
            if not ref:
                console.print("[dim]Cancelled.[/dim]")
                return CommandResult(success=True)

        try:
            snapshot = sessions.load(ref)
        except SessionError as e:
            return CommandResult(success=False, message=str(e))
        if snapshot.session_id == agent.session.session_id:
            console.print("[dim]Already in that chat.[/dim]")
            return CommandResult(success=True)

        _switch_to_snapshot(agent, config, console, snapshot)
        console.print(
            f"[success]Resumed: {escape(snapshot.title or snapshot.session_id[:8])}[/success]"
        )
        return CommandResult(success=True)

    def get_help(self) -> str:
        return "Continue a saved chat. Usage: /resume [number|id] (no argument: pick from list)"


class CheckpointCommand(Command):
    @property
    def name(self) -> str:
        return "/checkpoint"

    async def execute(self, args: str, context: dict[str, Any]) -> CommandResult:
        agent = context.get("agent")
        console = context.get("console")
        if not agent or not console:
            return CommandResult(success=False, message="No active session")

        checkpoint_id = StateManager().save_checkpoint(agent.session.to_snapshot())
        console.print(f"[success]Checkpoint created: {checkpoint_id}[/success]")
        return CommandResult(success=True)

    def get_help(self) -> str:
        return "Create a checkpoint of current session"


class RestoreCommand(Command):
    @property
    def name(self) -> str:
        return "/restore"

    async def execute(self, args: str, context: dict[str, Any]) -> CommandResult:
        if not args:
            return CommandResult(success=False, message="Usage: /restore <checkpoint_id>")

        agent = context.get("agent")
        config = context.get("config")
        console = context.get("console")
        if not agent or not config or not console:
            return CommandResult(success=False, message="Missing context")

        snapshot = StateManager().load_checkpoint(args.strip())
        if not snapshot:
            return CommandResult(success=False, message=f"Checkpoint does not exist: {args}")

        _switch_to_snapshot(agent, config, console, snapshot)
        console.print(
            f"[success]Restored checkpoint for session: {snapshot.session_id}[/success]"
        )
        return CommandResult(success=True)

    def get_help(self) -> str:
        return "Restore a checkpoint. Usage: /restore <checkpoint_id>"
