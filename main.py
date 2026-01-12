from pathlib import Path
import sys
import click
from agent.agent import Agent
from agent.events import AgentEventType
import asyncio
from config.config import Config
from config.loader import load_config
from ui.tui import TUI, get_console

console = get_console()  # Initialize console for TUI output


class SimhaCLI:
    def __init__(self, config: Config) -> None:
        self.agent: Agent | None = None
        self.tui: TUI = TUI(console=console, config=config)
        self.config = config

    async def run_single(self, message: str) -> str | None:
        async with Agent(config=self.config) as agent:
            self.agent = agent
            return await self._process_message(message)

    async def run_interactive(
        self,
    ) -> str | None:
        self.tui.print_welcome(
            title="SimhaCLI 🦁 — AI Coding Agent",
            lines=[
                "Built by Narasimha Naidu Korrapti",
                "",
                "SimhaCLI is a powerful AI coding agent that runs inside your terminal.",
                "It connects to multiple large language models and uses tools to think, read, and act.",
                "",
                "Current Usage::",
                f"Model: {self.config.model.name}",
                f"CWD: {self.config.cwd}",
                "Commands: /help for help, /exit to exit, /config, /approval, /model",
                "Type your commands below to get started!",
                "Type /exit or /quit to exit.",
            ],
        )
        try:
            async with Agent(config=self.config) as agent:
                self.agent = agent
                while True:
                    try:
                        user_input = console.input("\n[user]>[/user] ").strip()
                        if not user_input:
                            continue

                        if user_input.startswith("/"):

                            command = user_input[1:].strip().lower()
                            if command in ("exit", "quit"):
                                break
                            else:
                                console.print("\n[red]Use /exit or /quit to quit[/red]")
                            continue

                        await self._process_message(user_input)
                    except KeyboardInterrupt:
                        console.print("\n[dim]Use /exit or /quit to quit[/dim]")
                    except EOFError:
                        break
        except KeyboardInterrupt:
            console.print(
                "\n[error]Interrupted! Use /exit or /quit to quit properly.[/error]"
            )
            return None

        console.print("\n[brand]Thank You!... SIMHACLI 🦁[/brand]")

    def _get_tool_kind(self, tool_name: str) -> str | None:
        tool_kind = None
        tool = self.agent.session.tool_registry.get(tool_name)
        if not tool:
            tool_kind = None

        tool_kind = tool.kind.value if tool else None

        return tool_kind

    async def _process_message(self, message: str) -> str | None:
        if self.agent is None:
            print("Agent is not initialized.")
            return None

        response_content = ""
        async for event in self.agent.run(message):
            # print(event)
            if event.type == AgentEventType.TEXT_DELTA:
                content = event.data.get("content", "")

                self.tui.stream_assistant_delta(content)

            elif event.type == AgentEventType.TEXT_COMPLETE:
                response_content = event.data.get("content", "")
            elif event.type == AgentEventType.AGENT_START:
                message = event.data.get("message", "")
                self.tui.agent_start(message)
            elif event.type == AgentEventType.AGENT_END:
                usage = event.data.get("usage")
                self.tui.agent_end(usage)
            elif event.type == AgentEventType.AGENT_ERROR:
                error_msg = event.data.get("message", "Unknown error")
                self.tui.display_error(error_message=error_msg)
                return None
            elif event.type == AgentEventType.TOOL_CALL_START:
                tool_name = event.data.get("name", "unknown")
                tool_kind = self._get_tool_kind(tool_name)
                self.tui.tool_call_start(
                    event.data.get("call_id", ""),
                    tool_name,
                    tool_kind,
                    event.data.get("arguments", {}),
                )
            elif event.type == AgentEventType.TOOL_CALL_COMPLETE:
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

        return response_content if response_content else "completed"


@click.command()
@click.argument("prompt", required=False)
@click.option(
    "--cwd",
    "-c",
    type=click.Path(exists=True, file_okay=False, dir_okay=True, path_type=Path),
    help="Set the current working directory for the agent.",
    default=None,
)
def main(
    prompt: str | None = None,
    cwd: Path | None = None,
):

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
        pass  # Silently handle, our inner handlers already displayed messages


main()
