"""Command handler that integrates the command registry with SimhaCLI."""

from typing import Any
from .commands import get_command_registry, CommandResult
from agent.events import AgentEventType
import asyncio


class CommandHandler:
    """Handles command execution using the command registry."""

    def __init__(self, registry: Any) -> None:
        self.registry = registry

    async def handle_command(
        self, command: str, context: dict[str, Any]
    ) -> CommandResult | bool:
        """Handle a command and return result.

        Args:
            command: The full command string including the slash (e.g., "/help")
            context: Execution context

        Returns:
            CommandResult if a command was found, or False if exit requested
        """
        parts = command.strip().split(maxsplit=1)
        if not parts:
            parts = [""]
        # Only the command name is case-insensitive; arguments keep their case
        cmd_name = parts[0].lower()
        cmd_args = parts[1] if len(parts) > 1 else ""

        result = await self.registry.execute(cmd_name, cmd_args, context)

        if result.should_exit:
            return False
        return result
