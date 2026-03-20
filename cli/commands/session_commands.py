"""Session commands: /save, /sessions, /resume, /checkpoint, /restore."""

from .base import Command, CommandResult
from typing import Any
from agent.state import StateManager, SessionSnapshot
from agent.session import Session
from pathlib import Path


class SaveCommand(Command):
    @property
    def name(self) -> str:
        return "/save"

    async def execute(self, args: str, context: dict[str, Any]) -> CommandResult:
        agent = context.get("agent")
        console = context.get("console")
        if not agent or not console:
            return CommandResult(success=False, message="No active session")

        state_manager = StateManager()
        session_snapshot = SessionSnapshot(
            session_id=agent.session.session_id,
            created_at=agent.session.created_at,
            updated_at=agent.session.updated_at,
            turn_count=agent.session.turn_count,
            messages=agent.session.context_manager.get_messages(),
            total_usage=agent.session.context_manager.total_usage,
        )
        state_manager.save_session(session_snapshot)
        console.print(f"[success]Session saved: {agent.session.session_id}[/success]")
        return CommandResult(success=True)

    def get_help(self) -> str:
        return "Save current session to disk"


class SessionsCommand(Command):
    @property
    def name(self) -> str:
        return "/sessions"

    async def execute(self, args: str, context: dict[str, Any]) -> CommandResult:
        console = context.get("console")
        if not console:
            return CommandResult(success=False, message="Missing console")

        state_manager = StateManager()
        sessions = state_manager.list_sessions()
        console.print("\n[bold]Saved Sessions[/bold]")
        for s in sessions:
            console.print(
                f"  • {s['session_id']} (turns: {s['turn_count']}, updated: {s['updated_at']})"
            )
        return CommandResult(success=True)

    def get_help(self) -> str:
        return "List all saved sessions"


class ResumeCommand(Command):
    @property
    def name(self) -> str:
        return "/resume"

    async def execute(self, args: str, context: dict[str, Any]) -> CommandResult:
        if not args:
            return CommandResult(success=False, message="Usage: /resume <session_id>")

        agent = context.get("agent")
        config = context.get("config")
        console = context.get("console")
        if not agent or not config or not console:
            return CommandResult(success=False, message="Missing context")

        state_manager = StateManager()
        snapshot = state_manager.load_session(args)
        if not snapshot:
            return CommandResult(success=False, message=f"Session does not exist: {args}")

        session = Session(config=config)
        await session.initialize()
        session.session_id = snapshot.session_id
        session.created_at = snapshot.created_at
        session.updated_at = snapshot.updated_at
        session.turn_count = snapshot.turn_count
        session.context_manager.total_usage = snapshot.total_usage

        for msg in snapshot.messages:
            if msg.get("role") == "system":
                continue
            elif msg["role"] == "user":
                session.context_manager.add_user_message(msg.get("content", ""))
            elif msg["role"] == "assistant":
                session.context_manager.add_assistant_message(
                    msg.get("content", ""), msg.get("tool_calls")
                )
            elif msg["role"] == "tool":
                session.context_manager.add_tool_result(
                    msg.get("tool_call_id", ""), msg.get("content", "")
                )

        await agent.session.client.close_client()
        await agent.session.mcp_manager.shutdown_mcp()

        agent.session = session
        console.print(f"[success]Resumed session: {session.session_id}[/success]")
        return CommandResult(success=True)

    def get_help(self) -> str:
        return "Resume a saved session. Usage: /resume <session_id>"


class CheckpointCommand(Command):
    @property
    def name(self) -> str:
        return "/checkpoint"

    async def execute(self, args: str, context: dict[str, Any]) -> CommandResult:
        agent = context.get("agent")
        console = context.get("console")
        if not agent or not console:
            return CommandResult(success=False, message="No active session")

        state_manager = StateManager()
        session_snapshot = SessionSnapshot(
            session_id=agent.session.session_id,
            created_at=agent.session.created_at,
            updated_at=agent.session.updated_at,
            turn_count=agent.session.turn_count,
            messages=agent.session.context_manager.get_messages(),
            total_usage=agent.session.context_manager.total_usage,
        )
        checkpoint_id = state_manager.save_checkpoint(session_snapshot)
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

        state_manager = StateManager()
        snapshot = state_manager.load_checkpoint(args)
        if not snapshot:
            return CommandResult(success=False, message=f"Checkpoint does not exist: {args}")

        session = Session(config=config)
        await session.initialize()
        session.session_id = snapshot.session_id
        session.created_at = snapshot.created_at
        session.updated_at = snapshot.updated_at
        session.turn_count = snapshot.turn_count
        session.context_manager.total_usage = snapshot.total_usage

        for msg in snapshot.messages:
            if msg.get("role") == "system":
                continue
            elif msg["role"] == "user":
                session.context_manager.add_user_message(msg.get("content", ""))
            elif msg["role"] == "assistant":
                session.context_manager.add_assistant_message(
                    msg.get("content", ""), msg.get("tool_calls")
                )
            elif msg["role"] == "tool":
                session.context_manager.add_tool_result(
                    msg.get("tool_call_id", ""), msg.get("content", "")
                )

        await agent.session.client.close_client()
        await agent.session.mcp_manager.shutdown_mcp()

        agent.session = session
        console.print(f"[success]Restored checkpoint for session: {session.session_id}[/success]")
        return CommandResult(success=True)

    def get_help(self) -> str:
        return "Restore a checkpoint. Usage: /restore <checkpoint_id>"
