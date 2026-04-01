"""Factory to build command registry with all commands."""

from typing import Any
from .commands import (
    BotCommand,
    CommandRegistry,
    get_command_registry,
    HelpCommand,
    ConfigCommand,
    ClearCommand,
    StatsCommand,
    ToolsCommand,
    McpCommand,
    ExitCommand,
    QuitCommand,
    VersionCommand,
    ModelCommand,
    ApprovalCommand,
    CredentialsCommand,
    CredsAliasCommand,
    SaveCommand,
    SessionsCommand,
    ResumeCommand,
    CheckpointCommand,
    RestoreCommand,
    PermissionsCommand,
    WorkflowCommand,
    InitCommand,
    UndoCommand,
    RunCommand,
    BangCommand,
)


def create_command_registry() -> CommandRegistry:
    """Create and populate the command registry."""
    registry = get_command_registry()

    # System commands
    registry.register(HelpCommand())
    registry.register(ConfigCommand())
    registry.register(ClearCommand())
    registry.register(StatsCommand())
    registry.register(ToolsCommand())
    registry.register(McpCommand())
    registry.register(ExitCommand())
    registry.register(QuitCommand())
    registry.register(VersionCommand())
    registry.register(BotCommand())

    # Model/approval commands
    registry.register(ModelCommand())
    registry.register(ApprovalCommand())
    registry.register(CredentialsCommand())
    registry.register(CredsAliasCommand())

    # Session commands
    registry.register(SaveCommand())
    registry.register(SessionsCommand())
    registry.register(ResumeCommand())
    registry.register(CheckpointCommand())
    registry.register(RestoreCommand())

    # Permissions command
    registry.register(PermissionsCommand())

    # Workflow command
    registry.register(WorkflowCommand())

    # Init command
    registry.register(InitCommand())

    # Undo command
    registry.register(UndoCommand())

    # Run command
    registry.register(RunCommand())
    registry.register(BangCommand())

    return registry
