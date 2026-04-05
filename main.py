from pathlib import Path
import sys
import click
from agent.agent import Agent
from agent.events import AgentEventType
import asyncio
from config.config import Config
from config.loader import load_config
from ui.tui import TUI, get_console
from utils.file_attachments import (
    parse_attachments,
    format_message_with_attachments,
    format_multimodal_message,
)

from cli.factory import create_command_registry
from cli.command_handler import CommandHandler
from bot.commands import bot_group

# Get version from package metadata or fallback
try:
    from importlib.metadata import version

    __version__ = version("simhacli")
except Exception:
    __version__ = "1.5.1"

console = get_console()


class SimhaCLI:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.tui: TUI = TUI(console=console, config=config)
        self.agent: Agent | None = None
        self.command_handler = CommandHandler(create_command_registry())
        self._stop_requested = False

    async def run_single(self, message: str) -> str | None:
        try:
            async with Agent(config=self.config) as agent:
                self.agent = agent
                return await self._process_message(message)
        finally:
            self.agent = None

    async def run_interactive(self) -> str | None:
        self.tui.print_welcome(
            title="SimhaCLI 🦁 — AI Coding Agent",
            lines=[
                "Built by Narasimha Naidu Korrapati",
                "",
                "SimhaCLI is a powerful AI coding agent that runs inside your terminal.",
                "It connects to multiple large language models and uses tools to think, read, and act.",
                "",
                "Current Usage:",
                f"Model: {self.config.model.name}",
                f"CWD: {self.config.cwd}",
                "Commands: /help, /version, /exit, /config, /approval, /model, /credentials, /permissions, /init, /workflow, /undo, /run, /bot",
                "",
                "Shortcuts: @attach file | /commands | q=stop agent",
                "Input: Enter = submit | Esc+Enter = new line",
                "Type /exit or /quit to exit. Type 'q' to stop agent and wait for input.",
            ],
        )

        try:
            async with Agent(
                config=self.config,
                confirmation_callback=self.tui.handle_confirmation,
            ) as agent:
                self.agent = agent

                def get_tool_names():
                    if self.agent and self.agent.session:
                        tools = (
                            self.agent.session.tool_registry.get_all_registered_tools()
                        )
                        return sorted([t.name for t in tools])
                    return []

                def get_tool_status():
                    if not self.agent or not self.agent.session:
                        return {}
                    tools = self.agent.session.tool_registry.get_all_registered_tools()
                    denied_set = (
                        set(self.config.denied_tools)
                        if self.config.denied_tools
                        else set()
                    )
                    allowed_set = (
                        set(self.config.allowed_tools)
                        if self.config.allowed_tools
                        else None
                    )
                    status = {}
                    for tool in tools:
                        if tool.name in denied_set:
                            status[tool.name] = "denied"
                        elif allowed_set is not None and tool.name not in allowed_set:
                            status[tool.name] = "denied"
                        else:
                            status[tool.name] = "allowed"
                    return status

                self.tui.set_tool_getter(get_tool_names, get_tool_status)

                while True:
                    try:
                        self.tui.print_input_hint()
                        # Show context window usage
                        if self.agent and self.agent.session:
                            current_tokens = (
                                self.agent.session.context_manager.get_current_token_count()
                            )
                            max_tokens = self.config.model.context_window
                            self.tui.print_context_usage(current_tokens, max_tokens)
                        user_input = await self.tui.get_multiline_input("> ")
                        if user_input is None:
                            console.print(
                                "\n[dim]Use /exit, /quit, or 'q' to quit[/dim]"
                            )
                            continue
                        if not user_input:
                            continue

                        if user_input.strip().lower() == "q":
                            console.print(
                                "[dim]Agent stopped. Waiting for input...[/dim]"
                            )
                            continue

                        if user_input.startswith("/"):
                            result = await self.command_handler.handle_command(
                                user_input,
                                {
                                    "console": console,
                                    "config": self.config,
                                    "agent": self.agent,
                                    "tui": self.tui,
                                    "session": self.agent.session,
                                },
                            )
                            if result is False:  # Exit requested
                                return None
                            continue

                        self.agent.clear_undo_stack()
                        await self._process_message(user_input)

                        if self.agent.has_undo_changes():
                            count = self.agent.get_undo_count()
                            console.print(
                                f"[dim]  {count} file(s) changed. Type /undo to revert.[/dim]"
                            )

                    except KeyboardInterrupt:
                        console.print("\n[dim]Use /exit, /quit, or 'q' to quit[/dim]")
                    except EOFError:
                        break

        except KeyboardInterrupt:
            console.print(
                "\n[error]Interrupted! Use /exit or /quit to quit properly.[/error]"
            )
            return None
        finally:
            self.agent = None

        console.print("\n[brand]Thank You!... SIMHACLI 🦁[/brand]")

    async def _process_message(self, message: str) -> str | None:
        if self.agent is None:
            print("Agent is not initialized.")
            return None

        self._stop_requested = False
        cleaned, text_attachments, image_attachments = parse_attachments(
            message, self.config.cwd
        )

        # Show attachment summaries to user
        if text_attachments:
            self.tui.display_file_attachments(text_attachments)
        if image_attachments:
            for img in image_attachments:
                size = len(img.base64_data) * 3 // 4
                self.tui.console.print(
                    f"[cyan][Image] {img.relative_path} ({img.mime_type}, {size:,} bytes)[/cyan]"
                )

        # Check if model supports vision
        has_images = len(image_attachments) > 0
        model_supports_vision = getattr(self.config.model, 'supports_vision', True)
        
        if has_images and not model_supports_vision:
            self.tui.console.print(
                "[yellow]Warning: Current model does not support vision. "
                "Images will be described by filename only.[/yellow]"
            )

        # Build the message to send — multimodal if images present, else plain text
        if has_images and model_supports_vision:
            formatted_message = format_multimodal_message(
                message, text_attachments, image_attachments, self.config.cwd
            )
        else:
            formatted_message = format_message_with_attachments(
                message, text_attachments, self.config.cwd
            )

        response_content = ""
        text_started = False
        thinking_active = False
        self.tui.start_request_timer()

        try:
            async for event in self.agent.run(formatted_message):
                # Check for stop request
                if self._check_stop_input():
                    self._stop_requested = True
                    if thinking_active:
                        self.tui.end_thinking()
                    if text_started:
                        self.tui.end_assistant()
                    console.print("\n[yellow]Agent stopped by user (q).[/yellow]")
                    return "stopped"

                event_type = event.type

                if event_type == AgentEventType.THINKING_DELTA:
                    self._handle_thinking_delta(event, thinking_active)
                    thinking_active = True
                elif event_type == AgentEventType.THINKING_COMPLETE:
                    thinking_active = self._handle_thinking_complete(thinking_active)
                elif event_type == AgentEventType.TEXT_DELTA:
                    thinking_active, text_started = await self._handle_text_delta(
                        event, thinking_active, text_started
                    )
                elif event_type == AgentEventType.TEXT_COMPLETE:
                    text_started = self._handle_text_complete(text_started)
                    response_content = event.data.get("content", "")
                elif event_type == AgentEventType.AGENT_START:
                    msg = event.data.get("message", "")
                    self.tui.agent_start(msg)
                elif event_type == AgentEventType.AGENT_END:
                    usage = event.data.get("usage")
                    self.tui.agent_end(usage)
                elif event_type == AgentEventType.AGENT_ERROR:
                    error_msg = event.data.get("message", "Unknown error")
                    self.tui.display_error(error_message=error_msg)
                    return None
                elif event_type == AgentEventType.TOOL_CALL_START:
                    self._handle_tool_call_start(event)
                elif event_type == AgentEventType.TOOL_CALL_COMPLETE:
                    self._handle_tool_call_complete(event)
                else:
                    # Default case for any future/unknown event types
                    self._handle_unknown_event(event)
        except asyncio.CancelledError:
            console.print("\n[yellow]Agent execution cancelled.[/yellow]")
            return "cancelled"

        return response_content if response_content else "completed"

    def _check_stop_input(self) -> bool:
        """Check if 'q' was pressed to stop agent execution (non-blocking)."""
        import sys

        if sys.platform == "win32":
            import msvcrt

            if msvcrt.kbhit():
                key = msvcrt.getch()
                if key in (b"q", b"Q"):
                    return True
        else:
            import select

            if select.select([sys.stdin], [], [], 0.0)[0]:
                key = sys.stdin.read(1)
                if key.lower() == "q":
                    return True
        return False

    def _handle_thinking_delta(self, event: any, thinking_active: bool) -> None:
        """Handle thinking delta events."""
        if not thinking_active:
            self.tui.begin_thinking()
        self.tui.stream_thinking_delta(event.data.get("content", ""))

    def _handle_thinking_complete(self, thinking_active: bool) -> bool:
        """Handle thinking complete events. Returns whether thinking is active."""
        if thinking_active:
            self.tui.end_thinking()
            return False
        return thinking_active

    async def _handle_text_delta(
        self, event: any, thinking_active: bool, text_started: bool
    ) -> tuple[bool, bool]:
        """Handle text delta events. Returns (thinking_active, text_started)."""
        if thinking_active:
            self.tui.end_thinking()
            thinking_active = False
        if not text_started:
            self.tui.stop_loading()
            self.tui.begin_assistant()
            text_started = True
        content = event.data.get("content", "")
        self.tui.stream_assistant_delta(content)
        return thinking_active, text_started

    def _handle_text_complete(self, text_started: bool) -> bool:
        """Handle text complete events. Returns whether text has started."""
        if text_started:
            self.tui.end_assistant()
            return False
        return text_started

    def _handle_tool_call_start(self, event: any) -> None:
        """Handle tool call start events."""
        tool_name = event.data.get("name", "unknown")
        tool_kind = self._get_tool_kind(tool_name)
        self.tui.tool_call_start(
            event.data.get("call_id", ""),
            tool_name,
            tool_kind,
            event.data.get("arguments", {}),
        )

    def _handle_tool_call_complete(self, event: any) -> None:
        """Handle tool call complete events."""
        tool_name = event.data.get("name", "unknown")
        tool_kind = self._get_tool_kind(tool_name)
        self.tui.tool_call_complete(
            event.data.get("call_id", ""),
            tool_name,
            tool_kind,
            event.data.get("success", False),
            event.data.get("output", ""),
            event.data.get("error"),
            event.data.get("metadata"),
            event.data.get("diff"),
            event.data.get("truncated", False),
            event.data.get("exit_code"),
        )

    def _handle_unknown_event(self, event: any) -> None:
        """Handle unknown or future event types with a default action."""
        # Could log for debugging in the future
        event_type = getattr(event, "type", "unknown")
        # Default: silently ignore unknown events but could be extended to log
        pass

    def _get_tool_kind(self, tool_name: str) -> str | None:
        if not self.agent or not self.agent.session:
            return None
        tool = self.agent.session.tool_registry.get(tool_name)
        if not tool:
            return None
        kind = getattr(tool, "kind", None)
        return kind.value if kind else None


@click.group(
    invoke_without_command=True,
    context_settings=dict(allow_extra_args=True, allow_interspersed_args=False),
)
# @click.argument("prompt", required=False)
@click.option(
    "--cwd",
    "-c",
    type=click.Path(exists=True, file_okay=False, dir_okay=True, path_type=Path),
    help="Set the current working directory for the agent.",
    default=None,
)
@click.option(
    "--version",
    "-v",
    is_flag=True,
    help="Show SimhaCLI version and exit.",
)
@click.pass_context
def main(
    ctx,
    # prompt: str | None = None,
    cwd: Path | None = None,
    version: bool = False,
):

    if ctx.invoked_subcommand is not None:  # ← add this block
        return  #   (stops here for subcommands)
    prompt = " ".join(ctx.args) if ctx.args else None
    if version:
        console.print(f"SimhaCLI [cyan]{__version__}[/cyan]")
        console.print("Built by [cyan]Narasimha Naidu Korrapati[/cyan]")
        sys.exit(0)

    try:
        config = load_config(cwd=cwd)
    except Exception as e:
        console.print(f"[error]Failed to load config: {e}[/error]")
        sys.exit(1)

    errors = config.validate()
    if errors:
        console.print("[error]Configuration errors found:[/error]")
        for err in errors:
            console.print(f"[error]- {err}[/error]")
        sys.exit(1)

    cli = SimhaCLI(config=config)
    try:
        if prompt:
            result = asyncio.run(cli.run_single(prompt))
            if result is None:
                sys.exit(1)
        else:
            asyncio.run(cli.run_interactive())
    except KeyboardInterrupt:
        pass


main.add_command(bot_group)

if __name__ == "__main__":
    main()
