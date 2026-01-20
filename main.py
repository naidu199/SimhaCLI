from pathlib import Path
import sys
import click
from agent.agent import Agent
from agent.events import AgentEventType
import asyncio
from agent.session import Session
from agent.state import SessionSnapshot, StateManager
from config.config import ApprovalPolicy, Config
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
            async with Agent(
                config=self.config,
                confirmation_callback=self.tui.handle_confirmation,
            ) as agent:
                self.agent = agent
                while True:
                    try:
                        user_input = console.input("\n[user]>[/user] ").strip()
                        if not user_input:
                            continue

                        if user_input.startswith("/"):

                            should_continue = await self._handle_command(user_input)
                            if not should_continue:
                                break
                            continue

                            # command = user_input[1:].strip().lower()
                            # if command in ("exit", "quit"):
                            #     break
                            # else:
                            #     console.print("\n[red]Use /exit or /quit to quit[/red]")
                            # continue

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
        text_started = False
        async for event in self.agent.run(message):
            # print(event)
            if event.type == AgentEventType.TEXT_DELTA:
                if not text_started:
                    # Stop spinner when text starts
                    self.tui.stop_loading()
                    self.tui.begin_assistant()
                    text_started = True
                content = event.data.get("content", "")

                self.tui.stream_assistant_delta(content)

            elif event.type == AgentEventType.TEXT_COMPLETE:
                if text_started:
                    self.tui.end_assistant()
                    text_started = False
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

    async def _handle_command(self, command: str) -> bool:
        cmd = command.lower().strip()
        parts = cmd.split(maxsplit=1)
        cmd_name = parts[0]
        cmd_args = parts[1] if len(parts) > 1 else ""
        if cmd_name == "/exit" or cmd_name == "/quit":
            return False
        elif cmd_name == "/help":
            self.tui.show_help()
        elif cmd_name == "/clear":
            self.agent.session.context_manager.clear()
            self.agent.session.loop_detector.clear()
            console.print("[success]Conversation cleared [/success]")
        elif cmd_name == "/config":
            console.print("\n[bold]Current Configuration[/bold]")
            console.print(f"  Model: {self.config.model_name}")
            console.print(f"  Temperature: {self.config.temperature}")
            console.print(f"  Approval: {self.config.approval.value}")
            console.print(f"  Working Dir: {self.config.cwd}")
            console.print(f"  Max Turns: {self.config.max_turns}")
            console.print(f"  Hooks Enabled: {self.config.hooks_enabled}")
        elif cmd_name == "/model":
            if cmd_args:
                self.config.model_name = cmd_args
                console.print(f"[success]Model changed to: {cmd_args} [/success]")
            else:
                console.print(f"Current model: {self.config.model_name}")
        elif cmd_name == "/approval":
            if cmd_args:
                try:
                    approval = ApprovalPolicy(cmd_args)
                    self.config.approval = approval
                    console.print(
                        f"[success]Approval policy changed to: {cmd_args} [/success]"
                    )
                except:
                    console.print(
                        f"[error]Incorrect approval policy: {cmd_args} [/error]"
                    )
                    console.print(
                        f"Valid options: {', '.join(p for p in ApprovalPolicy)}"
                    )
            else:
                console.print(f"Current approval policy: {self.config.approval.value}")
        elif cmd_name == "/stats":
            stats = self.agent.session.get_stats()
            console.print("\n[bold]Session Statistics [/bold]")
            for key, value in stats.items():
                console.print(f"   {key}: {value}")
        elif cmd_name == "/tools":
            tools = self.agent.session.tool_registry.get_tools()
            console.print(f"\n[bold]Available tools ({len(tools)}) [/bold]")
            for tool in tools:
                console.print(f"  • {tool.name}")
        elif cmd_name == "/mcp":
            mcp_servers = self.agent.session.mcp_manager.get_all_servers()
            console.print(f"\n[bold]MCP Servers ({len(mcp_servers)}) [/bold]")
            for server in mcp_servers:
                status = server["status"]
                status_color = "green" if status == "connected" else "red"
                console.print(
                    f"  • {server['name']}: [{status_color}]{status}[/{status_color}] ({server['tools']} tools)"
                )
        elif cmd_name == "/save":
            state_manager = StateManager()
            session_snapshot = SessionSnapshot(
                session_id=self.agent.session.session_id,
                created_at=self.agent.session.created_at,
                updated_at=self.agent.session.updated_at,
                turn_count=self.agent.session.turn_count,
                messages=self.agent.session.context_manager.get_messages(),
                total_usage=self.agent.session.context_manager.total_usage,
            )
            state_manager.save_session(session_snapshot)
            console.print(
                f"[success]Session saved: {self.agent.session.session_id}[/success]"
            )
        elif cmd_name == "/sessions":
            state_manager = StateManager()
            sessions = state_manager.list_sessions()
            console.print("\n[bold]Saved Sessions[/bold]")
            for s in sessions:
                console.print(
                    f"  • {s['session_id']} (turns: {s['turn_count']}, updated: {s['updated_at']})"
                )
        elif cmd_name == "/resume":
            if not cmd_args:
                console.print(f"[error]Usage: /resume <session_id> [/error]")
            else:
                state_manager = StateManager()
                snapshot = state_manager.load_session(cmd_args)
                if not snapshot:
                    console.print(f"[error]Session does not exist [/error]")
                else:
                    session = Session(
                        config=self.config,
                    )
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
                            session.context_manager.add_user_message(
                                msg.get("content", "")
                            )
                        elif msg["role"] == "assistant":
                            session.context_manager.add_assistant_message(
                                msg.get("content", ""), msg.get("tool_calls")
                            )
                        elif msg["role"] == "tool":
                            session.context_manager.add_tool_result(
                                msg.get("tool_call_id", ""), msg.get("content", "")
                            )

                    await self.agent.session.client.close_client()
                    await self.agent.session.mcp_manager.shutdown_mcp()

                    self.agent.session = session
                    console.print(
                        f"[success]Resumed session: {session.session_id}[/success]"
                    )
        elif cmd_name == "/checkpoint":
            state_manager = StateManager()
            session_snapshot = SessionSnapshot(
                session_id=self.agent.session.session_id,
                created_at=self.agent.session.created_at,
                updated_at=self.agent.session.updated_at,
                turn_count=self.agent.session.turn_count,
                messages=self.agent.session.context_manager.get_messages(),
                total_usage=self.agent.session.context_manager.total_usage,
            )
            checkpoint_id = state_manager.save_checkpoint(session_snapshot)
            console.print(f"[success]Checkpoint created: {checkpoint_id}[/success]")
        elif cmd_name == "/restore":
            if not cmd_args:
                console.print(f"[error]Usage: /restire <checkpoint_id> [/error]")
            else:
                state_manager = StateManager()
                snapshot = state_manager.load_checkpoint(cmd_args)
                if not snapshot:
                    console.print(f"[error]Checkpoint does not exist [/error]")
                else:
                    session = Session(
                        config=self.config,
                    )
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
                            session.context_manager.add_user_message(
                                msg.get("content", "")
                            )
                        elif msg["role"] == "assistant":
                            session.context_manager.add_assistant_message(
                                msg.get("content", ""), msg.get("tool_calls")
                            )
                        elif msg["role"] == "tool":
                            session.context_manager.add_tool_result(
                                msg.get("tool_call_id", ""), msg.get("content", "")
                            )

                    await self.agent.session.client.close_client()
                    await self.agent.session.mcp_manager.shutdown_mcp()

                    self.agent.session = session
                    console.print(
                        f"[success]Resumed session: {session.session_id}, checkpoint: {checkpoint_id}[/success]"
                    )
        else:
            console.print(f"[error]Unknown command: {cmd_name}[/error]")

        return True


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
