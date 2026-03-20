"""Base command interface and result."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class CommandResult:
    """Result of a command execution."""

    success: bool
    message: Optional[str] = None
    should_exit: bool = False
    data: Optional[dict[str, Any]] = None


class Command(ABC):
    """Abstract base class for all commands."""

    @property
    @abstractmethod
    def name(self) -> str:
        """The command name (e.g., '/help')."""
        pass

    @abstractmethod
    async def execute(self, args: str, context: dict[str, Any]) -> CommandResult:
        """Execute the command with given arguments and context.

        Args:
            args: Command arguments string (everything after the command name)
            context: Dictionary containing:
                - console: Rich console for output
                - config: Current configuration
                - agent: Optional Agent instance
                - tui: TUI instance
                - session: Optional current session
                - workspace: Workspace context

        Returns:
            CommandResult with execution outcome
        """
        pass

    def get_help(self) -> str:
        """Return help text for this command."""
        return "No help available."
