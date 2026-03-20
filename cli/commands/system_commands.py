"""System commands: /help, /exit, /config, /clear, /stats, /tools, /mcp, /version."""

from .base import Command, CommandResult
from typing import Any


class HelpCommand(Command):
    @property
    def name(self) -> str:
        return "/help"

    async def execute(self, args: str, context: dict[str, Any]) -> CommandResult:
        tui = context.get("tui")
        if tui:
            tui.show_help()
        return CommandResult(success=True)

    def get_help(self) -> str:
        return "Show this help message"


class ExitCommand(Command):
    @property
    def name(self) -> str:
        return "/exit"

    async def execute(self, args: str, context: dict[str, Any]) -> CommandResult:
        return CommandResult(success=True, should_exit=True)

    def get_help(self) -> str:
        return "Exit SimhaCLI"


class QuitCommand(ExitCommand):
    """Alias for exit."""

    @property
    def name(self) -> str:
        return "/quit"


class ConfigCommand(Command):
    @property
    def name(self) -> str:
        return "/config"

    async def execute(self, args: str, context: dict[str, Any]) -> CommandResult:
        config = context.get("config")
        console = context.get("console")
        if not config or not console:
            return CommandResult(success=False, message="Missing context")

        console.print("\n[bold]Current Configuration[/bold]")
        console.print(f"  Model: {config.model_name}")
        console.print(f"  Temperature: {config.temperature}")
        console.print(f"  Approval: {config.approval.value}")
        console.print(f"  Working Dir: {config.cwd}")
        console.print(f"  Max Turns: {config.max_turns}")
        console.print(f"  Hooks Enabled: {config.hooks_enabled}")
        return CommandResult(success=True)

    def get_help(self) -> str:
        return "Display current configuration"


class ClearCommand(Command):
    @property
    def name(self) -> str:
        return "/clear"

    async def execute(self, args: str, context: dict[str, Any]) -> CommandResult:
        agent = context.get("agent")
        console = context.get("console")
        if not agent or not console:
            return CommandResult(success=False, message="No active session to clear")

        agent.session.context_manager.clear()
        agent.session.loop_detector.clear()
        console.print("[success]Conversation cleared[/success]")
        return CommandResult(success=True)

    def get_help(self) -> str:
        return "Clear conversation history"


class StatsCommand(Command):
    @property
    def name(self) -> str:
        return "/stats"

    async def execute(self, args: str, context: dict[str, Any]) -> CommandResult:
        agent = context.get("agent")
        console = context.get("console")
        if not agent or not console:
            return CommandResult(success=False, message="No active session")

        stats = agent.session.get_stats()
        console.print("\n[bold]Session Statistics[/bold]")
        for key, value in stats.items():
            console.print(f"   {key}: {value}")
        return CommandResult(success=True)

    def get_help(self) -> str:
        return "Show session statistics"


class ToolsCommand(Command):
    @property
    def name(self) -> str:
        return "/tools"

    async def execute(self, args: str, context: dict[str, Any]) -> CommandResult:
        agent = context.get("agent")
        console = context.get("console")
        if not agent or not console:
            return CommandResult(success=False, message="No active session")

        tools = agent.session.tool_registry.get_tools()
        console.print(f"\n[bold]Available tools ({len(tools)})[/bold]")
        for tool in tools:
            console.print(f"  • {tool.name}")
        return CommandResult(success=True)

    def get_help(self) -> str:
        return "List available tools"


class McpCommand(Command):
    @property
    def name(self) -> str:
        return "/mcp"

    async def execute(self, args: str, context: dict[str, Any]) -> CommandResult:
        agent = context.get("agent")
        console = context.get("console")
        if not agent or not console:
            return CommandResult(success=False, message="No active session")

        mcp_servers = agent.session.mcp_manager.get_all_servers()
        console.print(f"\n[bold]MCP Servers ({len(mcp_servers)})[/bold]")
        for server in mcp_servers:
            status = server["status"]
            status_color = "green" if status == "connected" else "red"
            console.print(
                f"  • {server['name']}: [{status_color}]{status}[/{status_color}] ({server['tools']} tools)"
            )
        return CommandResult(success=True)

    def get_help(self) -> str:
        return "Show MCP server status"


class VersionCommand(Command):
    @property
    def name(self) -> str:
        return "/version"

    async def execute(self, args: str, context: dict[str, Any]) -> CommandResult:
        try:
            from __init__ import __version__
        except ImportError:
            # Fallback if import fails
            __version__ = "unknown"
        console = context.get("console")
        if console:
            console.print(f"\n[bold]SimhaCLI[/bold] version [cyan]{__version__}[/cyan]")
            console.print("Built by [cyan]Narasimha Naidu Korrapati[/cyan]")
        return CommandResult(success=True)

    def get_help(self) -> str:
        return "Display SimhaCLI version"
