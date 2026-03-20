"""Init command: /init."""

from .base import Command, CommandResult
from typing import Any
from rich.prompt import Prompt
from rich.panel import Panel
from pathlib import Path


class InitCommand(Command):
    @property
    def name(self) -> str:
        return "/init"

    async def execute(self, args: str, context: dict[str, Any]) -> CommandResult:
        config = context.get("config")
        agent = context.get("agent")
        console = context.get("console")
        if not config or not agent or not console:
            return CommandResult(success=False, message="Missing context")

        project_dir = config.cwd

        console.print()
        console.print(
            Panel(
                f"[bold]Project:[/bold] {project_dir}",
                title="[bold yellow]/init — AI Project Analyzer[/bold yellow]",
                border_style="yellow",
            )
        )

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

        existing = [f for f in file_targets if (project_dir / f).exists()]
        if existing:
            console.print(
                f"[yellow]Existing files found: {', '.join(existing)} (will be overwritten)[/yellow]"
            )

        console.print()
        console.print(
            f"[dim]The agent will now deeply analyze the project and generate {target_desc}...[/dim]"
        )

        init_prompt = self._build_init_prompt(project_dir, file_targets)

        # Use the agent directly to process this message
        result = await self._process_message(agent, config, init_prompt)
        return CommandResult(success=True)

    def _build_init_prompt(self, project_dir: Path, file_targets: list[str]) -> str:
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

    async def _process_message(self, agent: Any, config: Any, message: str) -> str:
        """Process a message through the agent. Simplified version for /init."""
        from agent.events import AgentEventType
        import asyncio

        response_content = ""
        text_started = False
        thinking_active = False

        async for event in agent.run(message):
            if event.type == AgentEventType.THINKING_DELTA:
                if not thinking_active:
                    thinking_active = True
            elif event.type == AgentEventType.THINKING_COMPLETE:
                thinking_active = False
            elif event.type == AgentEventType.TEXT_DELTA:
                if thinking_active:
                    thinking_active = False
                if not text_started:
                    text_started = True
                content = event.data.get("content", "")
            elif event.type == AgentEventType.TEXT_COMPLETE:
                response_content = event.data.get("content", "")
            elif event.type == AgentEventType.AGENT_ERROR:
                return f"Error: {event.data.get('message', 'Unknown error')}"

        return response_content if response_content else "completed"

    def get_help(self) -> str:
        return "Analyze project and generate instruction files (AGENTS.md, SIMHACLI.md)"
