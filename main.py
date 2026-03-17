from pathlib import Path
import sys
import time
import click
from agent.agent import Agent
from agent.events import AgentEventType
import asyncio
import json
from agent.session import Session
from agent.state import SessionSnapshot, StateManager
from config.config import ApprovalPolicy, Config
from config.loader import (
    load_config,
    get_config_file_path,
    _save_config_toml,
    _parse_toml,
    _mask_api_key,
)
from ui.tui import TUI, get_console
from utils.file_attachments import (
    parse_attachments,
    format_message_with_attachments,
    get_attachment_summary,
)

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
                "Commands: /help, /exit, /config, /approval, /model, /credentials, /permissions, /init",
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
                
                # Setup tool name getter for completions
                def get_tool_names():
                    if self.agent and self.agent.session:
                        tools = self.agent.session.tool_registry.get_all_registered_tools()
                        return sorted([t.name for t in tools])
                    return []
                
                def get_tool_status():
                    """Get the current permission status of all tools."""
                    if not self.agent or not self.agent.session:
                        return {}
                    
                    tools = self.agent.session.tool_registry.get_all_registered_tools()
                    denied_set = set(self.config.denied_tools) if self.config.denied_tools else set()
                    allowed_set = set(self.config.allowed_tools) if self.config.allowed_tools else None
                    
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
                        # Show input hint below the prompt
                        self.tui.print_input_hint()
                        # Use multi-line input with better text editing support
                        # Enter to send, Ctrl+J for new line
                        user_input = await self.tui.get_multiline_input("> ")
                        if user_input is None:
                            console.print(
                                "\n[dim]Use /exit, /quit, or 'q' to quit[/dim]"
                            )
                            continue
                        if not user_input:
                            continue

                        # Handle 'q' as stop agent / back to prompt (not exit)
                        if user_input.strip().lower() == "q":
                            console.print(
                                "[dim]Agent stopped. Waiting for input...[/dim]"
                            )
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
                        console.print("\n[dim]Use /exit, /quit, or 'q' to quit[/dim]")
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

        # Parse @filename attachments from user input
        _, attachments = parse_attachments(message, self.config.cwd)

        # Display file attachment feedback if files were found
        if attachments:
            self.tui.display_file_attachments(attachments)

        # Format message with file contents for the LLM
        formatted_message = format_message_with_attachments(
            message, attachments, self.config.cwd
        )

        response_content = ""
        text_started = False
        thinking_active = False
        self.tui.start_request_timer()
        async for event in self.agent.run(formatted_message):
            # print(event)

            # ── Thinking (reasoning tokens) ──────────────────────
            if event.type == AgentEventType.THINKING_DELTA:
                if not thinking_active:
                    self.tui.begin_thinking()
                    thinking_active = True
                self.tui.stream_thinking_delta(event.data.get("content", ""))

            elif event.type == AgentEventType.THINKING_COMPLETE:
                if thinking_active:
                    self.tui.end_thinking()
                    thinking_active = False

            # ── Text output ──────────────────────────────────────
            elif event.type == AgentEventType.TEXT_DELTA:
                # Close thinking if still active when text begins
                if thinking_active:
                    self.tui.end_thinking()
                    thinking_active = False
                if not text_started:
                    # Stop working spinner when text starts streaming
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

    async def _handle_credentials_command(self, cmd_args: str) -> None:
        """Handle /credentials command to view or update API credentials."""
        from rich.prompt import Prompt, Confirm
        from rich.panel import Panel

        config_path = get_config_file_path()

        if cmd_args == "":
            # Show current credentials
            api_key = self.config.get_api_key()
            api_base_url = self.config.get_api_base_url()

            console.print()
            console.print(
                Panel(
                    f"[bold]API Base URL:[/bold] {api_base_url or '[dim]Not set[/dim]'}\n"
                    f"[bold]API Key:[/bold] {_mask_api_key(api_key) if api_key else '[dim]Not set[/dim]'}\n\n"
                    f"[dim]Config file: {config_path}[/dim]",
                    title="[bold yellow]🔑 Current Credentials[/bold yellow]",
                    border_style="yellow",
                )
            )
            console.print()
            console.print("[dim]Use '/credentials update' to change credentials[/dim]")
            console.print("[dim]Use '/credentials key' to update only API key[/dim]")
            console.print("[dim]Use '/credentials url' to update only base URL[/dim]")

        elif cmd_args == "update":
            # Update both credentials
            await self._update_credentials(update_url=True, update_key=True)

        elif cmd_args == "key":
            # Update only API key
            await self._update_credentials(update_url=False, update_key=True)

        elif cmd_args == "url":
            # Update only base URL
            await self._update_credentials(update_url=True, update_key=False)

        else:
            console.print(f"[error]Unknown subcommand: {cmd_args}[/error]")
            console.print("[dim]Usage: /credentials [update|key|url][/dim]")

    async def _update_credentials(
        self, update_url: bool = False, update_key: bool = False
    ) -> None:
        """Update API credentials interactively."""
        from rich.prompt import Prompt, Confirm

        config_path = get_config_file_path()

        # Load existing config
        existing_config = {}
        if config_path.is_file():
            try:
                existing_config = _parse_toml(config_path)
            except Exception:
                pass

        api_base_url = self.config.get_api_base_url()
        api_key = self.config.get_api_key()

        if update_url:
            console.print()
            console.print(f"[dim]Current Base URL: {api_base_url or 'Not set'}[/dim]")
            use_openrouter = Confirm.ask(
                "[bold yellow]Use OpenRouter (https://openrouter.ai/api/v1)?[/bold yellow]",
                default=True,
            )

            if use_openrouter:
                api_base_url = "https://openrouter.ai/api/v1"
            else:
                api_base_url = Prompt.ask(
                    "[bold yellow]Enter new API Base URL[/bold yellow]",
                    default=api_base_url or "",
                )

            existing_config["api_base_url"] = api_base_url
            self.config.api_base_url = api_base_url
            console.print(f"[green]✓ Base URL updated: {api_base_url}[/green]")

        if update_key:
            console.print()
            console.print(
                f"[dim]Current API Key: {_mask_api_key(api_key) if api_key else 'Not set'}[/dim]"
            )
            new_key = Prompt.ask(
                "[bold yellow]Enter new API Key[/bold yellow]", password=True
            )

            if new_key.strip():
                api_key = new_key.strip()
                existing_config["api_key"] = api_key
                self.config.api_key = api_key
                console.print(
                    f"[green]✓ API Key updated: {_mask_api_key(api_key)}[/green]"
                )
            else:
                console.print("[dim]API Key unchanged[/dim]")

        # Save to config file
        _save_config_toml(config_path, existing_config)
        console.print(f"\n[green]✓ Credentials saved to: {config_path}[/green]")

        # Recreate the LLM client with new credentials
        if self.agent and self.agent.session:
            await self.agent.session.client.close_client()
            console.print(
                "[dim]LLM client will use new credentials on next request[/dim]"
            )

    async def _handle_init_command(self, cmd_args: str) -> None:
        """Handle /init command — use the AI agent to deeply analyze the project and generate instruction files."""
        from rich.prompt import Prompt
        from rich.panel import Panel

        project_dir = self.config.cwd

        console.print()
        console.print(
            Panel(
                f"[bold]Project:[/bold] {project_dir}",
                title="[bold yellow]/init — AI Project Analyzer[/bold yellow]",
                border_style="yellow",
            )
        )

        # Ask user which files to generate
        console.print()
        console.print("[bold]Which file(s) would you like to generate?[/bold]")
        console.print("  [cyan]1[/cyan] — AGENTS.md  (standard AI agent instructions)")
        console.print(
            "  [cyan]2[/cyan] — SIMHACLI.md (SimhaCLI-specific project config)"
        )
        console.print("  [cyan]3[/cyan] — Both")
        console.print()

        choice = Prompt.ask(
            "[bold yellow]Select[/bold yellow]",
            choices=["1", "2", "3"],
            default="3",
        )

        file_targets = []
        if choice in ("1", "3"):
            file_targets.append("AGENTS.md")
        if choice in ("2", "3"):
            file_targets.append("SIMHACLI.md")

        target_desc = " and ".join(file_targets)

        # Check for existing files
        existing = [f for f in file_targets if (project_dir / f).exists()]
        if existing:
            console.print(
                f"[yellow]Existing files found: {', '.join(existing)} (will be overwritten)[/yellow]"
            )

        console.print()
        console.print(
            f"[dim]The agent will now deeply analyze the project and generate {target_desc}...[/dim]"
        )

        # Build the prompt and send through the normal agent pipeline
        init_prompt = self._build_init_prompt(project_dir, file_targets)
        await self._process_message(init_prompt)

    def _build_init_prompt(self, project_dir: Path, file_targets: list[str]) -> str:
        """Build the prompt that instructs the agent to use its tools to analyze and generate files."""

        target_instructions = []
        for target in file_targets:
            if target == "AGENTS.md":
                target_instructions.append(
                    f"""
**{target}** — Write a comprehensive AI agent instruction file containing:
- Project description and purpose (based on what you read)
- Build, lint, test, and run commands (discovered from config files)
- Architecture overview: key modules/packages, how they connect, data flow, entry points
- Code conventions and patterns actually used in the project
- Key files and directories with brief descriptions
- Any pitfalls or important setup steps you discover"""
                )
            elif target == "SIMHACLI.md":
                target_instructions.append(
                    f"""
**{target}** — Write a SimhaCLI-specific project instruction file containing:
- Project overview: what the project does, its purpose
- Languages, frameworks, and key dependencies
- Build, test, lint, and run commands
- Architecture: modules, packages, entry points, how components interact
- Code conventions: naming patterns, file organization, import style, error handling
- Key files with descriptions
- Development workflow notes and environment setup
- Any project-specific rules the agent should follow"""
                )

        targets_block = "\n".join(target_instructions)

        return f"""You are running the /init command. Your job is to **deeply analyze this project** and generate high-quality, project-specific instruction file(s).

**Project directory:** {project_dir}

## Step-by-step instructions:

1. **Explore the project structure** — Use `list_dir` to see the top-level layout. Use `glob` to find source files, config files, and key directories.
2. **Read config files** — Read README.md, package.json, pyproject.toml, setup.py, setup.cfg, Cargo.toml, go.mod, Makefile, Dockerfile, requirements.txt, tsconfig.json, and any other config files that exist.
3. **Read source code** — Read the main entry points, key modules, and representative source files to understand the actual architecture, patterns, and conventions used.
4. **Check for existing instruction files** — Read any existing AGENTS.md, CLAUDE.md, SIMHACLI.md, .cursorrules, .github/copilot-instructions.md if they exist, and incorporate their useful content.
5. **Write the file(s)** — Use `write_file` to write the following file(s) to the project root:

{targets_block}

## Critical rules:
- **You MUST use your tools** (list_dir, glob, read_file, grep) to explore the project. Do NOT guess or generate generic content.
- **Be specific.** Include actual file paths, actual command names, actual module names, actual patterns you observed in the code.
- **Be concise but comprehensive.** Focus on information that helps an AI agent be immediately productive in this codebase.
- **Do NOT include generic advice** like "write clean code" or "follow best practices". Only include project-specific information you discovered.
- **Do NOT include obvious instructions** like "never include API keys in code".
- **Write the file(s) using `write_file`.** Do not just output the content as text.

Begin by exploring the project structure."""

    async def _handle_permissions_command(self, cmd_args: str) -> None:
        """Handle /permissions command to view and toggle tool permissions."""
        from rich.table import Table
        from rich.prompt import Prompt
        from rich.panel import Panel

        registry = self.agent.session.tool_registry
        all_tools = registry.get_all_registered_tools()
        allowed_set = (
            set(self.config.allowed_tools) if self.config.allowed_tools else None
        )
        denied_set = (
            set(self.config.denied_tools) if self.config.denied_tools else set()
        )

        if cmd_args == "":
            # Display current permissions table
            table = Table(
                title="Tool Permissions", border_style="cyan", show_lines=False
            )
            table.add_column("#", style="dim", width=4)
            table.add_column("Tool", style="bold")
            table.add_column("Kind", style="dim")
            table.add_column("Status", justify="center")

            sorted_tools = sorted(all_tools, key=lambda t: t.name)
            for i, tool in enumerate(sorted_tools, 1):
                if tool.name in denied_set:
                    status = "[red]denied[/red]"
                elif allowed_set is not None and tool.name not in allowed_set:
                    status = "[red]denied[/red]"
                else:
                    status = "[green]allowed[/green]"
                kind = tool.kind.value if hasattr(tool, "kind") else "unknown"
                table.add_row(str(i), tool.name, kind, status)

            console.print()
            console.print(table)
            console.print()
            
            # Show available tool names for allow/deny commands
            tool_names = [t.name for t in sorted_tools]
            console.print("[dim]Available tools:[/dim]")
            console.print(f"[dim]  {', '.join(tool_names)}[/dim]")
            console.print()
            console.print("[dim]Usage:[/dim]")
            console.print("[dim]  /permissions allow <tool_name>  — Allow a tool[/dim]")
            console.print("[dim]  /permissions deny <tool_name>   — Deny a tool[/dim]")
            console.print(
                "[dim]  /permissions reset              — Reset to all allowed[/dim]"
            )

        elif cmd_args.startswith("allow "):
            tool_name = cmd_args[6:].strip()
            tool = registry.get(tool_name) or self._find_tool_in_all(
                all_tools, tool_name
            )
            if not tool:
                available = [t.name for t in sorted(all_tools, key=lambda t: t.name)]
                console.print(f"[error]Unknown tool: {tool_name}[/error]")
                console.print(f"[dim]Available: {', '.join(available)}[/dim]")
                return

            # Remove from denied list
            if tool.name in denied_set:
                self.config.denied_tools.remove(tool.name)
            # Add to allowed list if allowlist mode is active
            if (
                self.config.allowed_tools is not None
                and tool.name not in self.config.allowed_tools
            ):
                self.config.allowed_tools.append(tool.name)

            console.print(f"[green]Allowed:[/green] {tool.name}")
            self._refresh_tools_after_permission_change()

        elif cmd_args.startswith("deny "):
            tool_name = cmd_args[5:].strip()
            tool = registry.get(tool_name) or self._find_tool_in_all(
                all_tools, tool_name
            )
            if not tool:
                available = [t.name for t in sorted(all_tools, key=lambda t: t.name)]
                console.print(f"[error]Unknown tool: {tool_name}[/error]")
                console.print(f"[dim]Available: {', '.join(available)}[/dim]")
                return

            # Add to denied list
            if tool.name not in self.config.denied_tools:
                self.config.denied_tools.append(tool.name)
            # Remove from allowed list if allowlist mode is active
            if (
                self.config.allowed_tools is not None
                and tool.name in self.config.allowed_tools
            ):
                self.config.allowed_tools.remove(tool.name)

            console.print(f"[red]Denied:[/red] {tool.name}")
            self._refresh_tools_after_permission_change()

        elif cmd_args == "reset":
            self.config.allowed_tools = None
            self.config.denied_tools = []
            console.print("[green]All tool permissions reset to allowed.[/green]")
            self._refresh_tools_after_permission_change()

        else:
            console.print(f"[error]Unknown subcommand: {cmd_args}[/error]")
            tool_names = [t.name for t in sorted(all_tools, key=lambda t: t.name)]
            console.print(
                f"[dim]Usage: /permissions [allow <tool_name>|deny <tool_name>|reset][/dim]"
            )
            console.print(f"[dim]Available tools: {', '.join(tool_names)}[/dim]")

    def _find_tool_in_all(self, all_tools: list, name: str):
        """Find a tool by name in the unfiltered tool list."""
        for tool in all_tools:
            if tool.name == name:
                return tool
        return None

    def _refresh_tools_after_permission_change(self) -> None:
        """Refresh the system prompt after tool permissions change."""
        if self.agent and self.agent.session:
            tools = self.agent.session.tool_registry.get_tools()
            self.agent.session.context_manager.refresh_system_prompt(tools=tools)
            active = len(tools)
            console.print(f"[dim]Active tools: {active}[/dim]")

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

                # Refresh system prompt with new model info
                if self.agent and self.agent.session:
                    tools = self.agent.session.tool_registry.get_tools()
                    self.agent.session.context_manager.refresh_system_prompt(
                        tools=tools
                    )
                    console.print(
                        "[dim]System prompt updated with new model info[/dim]"
                    )

                # Save to project config file
                project_config_path = self.config.cwd / ".simhacli" / "config.toml"
                if project_config_path.parent.exists():
                    try:
                        # Load existing project config
                        existing_config = {}
                        if project_config_path.is_file():
                            existing_config = _parse_toml(project_config_path)

                        # Update model name
                        if "model" not in existing_config:
                            existing_config["model"] = {}
                        existing_config["model"]["name"] = cmd_args

                        # Save back to file
                        _save_config_toml(project_config_path, existing_config)
                        console.print(
                            f"[dim]Model saved to project config: {project_config_path}[/dim]"
                        )
                    except Exception as e:
                        console.print(
                            f"[warning]Could not save to project config: {e}[/warning]"
                        )
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
                console.print(f"[error]Usage: /restore <checkpoint_id> [/error]")
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
                        f"[success]Restored checkpoint for session: {session.session_id}[/success]"
                    )
        elif cmd_name == "/credentials" or cmd_name == "/creds":
            await self._handle_credentials_command(cmd_args)
        elif cmd_name == "/init":
            await self._handle_init_command(cmd_args)
        elif cmd_name == "/permissions":
            await self._handle_permissions_command(cmd_args)
        elif cmd_name == "/undo":
            if not self.agent._undo_stack:
                console.print("[warning]Nothing to undo.[/warning]")
            else:
                path_str, old_content, new_content = self.agent._undo_stack.pop()
                try:
                    file_path = Path(path_str)
                    if old_content == "" and file_path.exists():
                        # File was newly created — delete it
                        file_path.unlink()
                        console.print(
                            f"[success]Undo: deleted newly created file {path_str}[/success]"
                        )
                    elif file_path.exists():
                        current = file_path.read_text(encoding="utf-8")
                        if current == new_content:
                            file_path.write_text(old_content, encoding="utf-8")
                            console.print(
                                f"[success]Undo: reverted {path_str}[/success]"
                            )
                        else:
                            console.print(
                                f"[warning]File {path_str} has been modified since the last edit. "
                                f"Undo skipped to avoid data loss.[/warning]"
                            )
                            # Push it back since we didn't undo
                            self.agent._undo_stack.append(
                                (path_str, old_content, new_content)
                            )
                    else:
                        console.print(
                            f"[warning]File {path_str} no longer exists.[/warning]"
                        )
                except Exception as e:
                    console.print(f"[error]Undo failed: {e}[/error]")
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
