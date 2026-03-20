"""Command registry for managing and executing commands."""

from typing import Any, Dict, Optional, Type
from .base import Command, CommandResult


class CommandRegistry:
    """Registry for all available commands."""

    def __init__(self) -> None:
        self._commands: Dict[str, Command] = {}

    def register(self, command: Command) -> None:
        """Register a command."""
        self._commands[command.name] = command

    def get(self, name: str) -> Optional[Command]:
        """Get a command by name."""
        return self._commands.get(name)

    def list_commands(self) -> list[str]:
        """List all registered command names."""
        return sorted(self._commands.keys())

    async def execute(
        self, name: str, args: str, context: dict[str, Any]
    ) -> CommandResult:
        """Execute a command by name."""
        command = self.get(name)
        if not command:
            return CommandResult(success=False, message=f"Unknown command: {name}")
        return await command.execute(args, context)


# Global registry instance
_default_registry: Optional[CommandRegistry] = None


def get_command_registry() -> CommandRegistry:
    """Get or create the global command registry."""
    global _default_registry
    if _default_registry is None:
        _default_registry = CommandRegistry()
    return _default_registry
