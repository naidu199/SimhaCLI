"""System commands: /help, /exit, /config, /clear, /stats, /tools, /mcp, /version, /bot."""

from .base import Command, CommandResult
from typing import Any


class HelpCommand(Command):
    @property
    def name(self) -> str:
        return "/help"

    async def execute(self, args: str, context: dict[str, Any]) -> CommandResult:
        tui = context.get("tui")
        console = context.get("console")
        if tui:
            tui.show_help()
        elif console:
            console.print("[bold]SimhaCLI Help[/bold]")
            console.print(
                "Commands: /help, /exit, /config, /model, /approval, /init, /undo, /run, /bot"
            )
            console.print("Use @ to attach files. Type 'q' to stop the agent.")
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


class BotCommand(Command):
    @property
    def name(self) -> str:
        return "/bot"

    async def execute(self, args: str, context: dict[str, Any]) -> CommandResult:
        from config.loader import load_config
        from rich.panel import Panel

        console = context.get("console")
        if not console:
            return CommandResult(success=False, message="Missing console")

        try:
            cfg = load_config(prompt_api=False)
        except Exception as e:
            console.print(f"[red]Failed to load config: {e}[/red]")
            return CommandResult(success=False)

        bot_config = cfg.telegram
        bot_token = bot_config.bot_token
        allowed_ids = bot_config.allowed_user_ids

        console.print()

        if not bot_token:
            console.print(
                Panel(
                    "[bold yellow]Telegram Bot Setup Required[/bold yellow]\n\n"
                    "The Telegram bot is not configured yet.\n\n"
                    "[bold]Quick Setup:[/bold]\n"
                    "1. Run: [cyan]simhacli bot setup[/cyan]\n"
                    "2. Follow the prompts to get a bot token from @BotFather\n"
                    "3. Enter your Telegram user ID from @userinfobot\n\n"
                    "After setup, start the bot with: [cyan]simhacli bot start[/cyan]",
                    title="🤖 Bot Not Configured",
                    border_style="yellow",
                )
            )
        else:
            # Show status
            console.print(
                Panel(
                    f"[bold]Bot Token:[/bold] [green]...{bot_token[-8:] if len(bot_token) > 8 else bot_token}[/green]\n"
                    f"[bold]Allowed Users:[/bold] {', '.join(str(uid) for uid in allowed_ids)}\n\n"
                    f"[bold]Manage:[/bold]\n"
                    f"• [cyan]simhacli bot setup[/cyan] — reconfigure token/IDs\n"
                    f"• [cyan]simhacli bot start[/cyan] — start the bot\n"
                    f"• [cyan]simhacli bot status[/cyan] — show this status",
                    title="[bold green]✅ Telegram Bot Active[/bold green]",
                    border_style="green",
                )
            )

        console.print()
        return CommandResult(success=True)

    def get_help(self) -> str:
        return "Show Telegram bot configuration and setup instructions"
