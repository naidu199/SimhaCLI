"""Command handlers for SimhaCLI."""

from .base import Command, CommandResult
from .registry import CommandRegistry, get_command_registry
from .system_commands import BotCommand, HelpCommand, ConfigCommand, ClearCommand, StatsCommand, ToolsCommand, McpCommand, ExitCommand, QuitCommand, VersionCommand
from .model_commands import ModelCommand, ApprovalCommand, CredentialsCommand, CredsAliasCommand
from .session_commands import SaveCommand, SessionsCommand, ResumeCommand, CheckpointCommand, RestoreCommand
from .permissions_commands import PermissionsCommand
from .workflow_commands import WorkflowCommand
from .init_commands import InitCommand
from .undo_commands import UndoCommand
from .run_commands import RunCommand
from .run_commands import BangCommand

__all__ = [
    "Command",
    "CommandResult",
    "CommandRegistry",
    "get_command_registry",
    "BotCommand",
    "HelpCommand",
    "ConfigCommand",
    "ClearCommand",
    "StatsCommand",
    "ToolsCommand",
    "McpCommand",
    "ExitCommand",
    "QuitCommand",
    "VersionCommand",
    "ModelCommand",
    "ApprovalCommand",
    "CredentialsCommand",
    "CredsAliasCommand",
    "SaveCommand",
    "SessionsCommand",
    "ResumeCommand",
    "CheckpointCommand",
    "RestoreCommand",
    "PermissionsCommand",
    "WorkflowCommand",
    "InitCommand",
    "UndoCommand",
    "RunCommand",
    "BangCommand",
]
