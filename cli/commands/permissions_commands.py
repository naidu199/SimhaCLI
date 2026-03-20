"""Permissions command: /permissions."""

from .base import Command, CommandResult
from typing import Any


class PermissionsCommand(Command):
    @property
    def name(self) -> str:
        return "/permissions"

    async def execute(self, args: str, context: dict[str, Any]) -> CommandResult:
        agent = context.get("agent")
        config = context.get("config")
        console = context.get("console")
        if not agent or not config or not console:
            return CommandResult(success=False, message="Missing context")

        from rich.table import Table

        registry = agent.session.tool_registry
        all_tools = registry.get_all_registered_tools()
        allowed_set = set(config.allowed_tools) if config.allowed_tools else None
        denied_set = set(config.denied_tools) if config.denied_tools else set()

        if not args:
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

            tool_names = [t.name for t in sorted_tools]
            console.print("[dim]Available tools:[/dim]")
            console.print(f"[dim]  {', '.join(tool_names)}[/dim]")
            console.print()
            console.print("[dim]Usage:[/dim]")
            console.print("[dim]  /permissions allow <tool_name>  — Allow a tool[/dim]")
            console.print("[dim]  /permissions deny <tool_name>   — Deny a tool[/dim]")
            console.print("[dim]  /permissions reset              — Reset to all allowed[/dim]")
            return CommandResult(success=True)

        parts = args.split(maxsplit=1)
        subcmd = parts[0]
        tool_name = parts[1].strip() if len(parts) > 1 else ""

        if subcmd == "allow":
            if not tool_name:
                return CommandResult(success=False, message="Missing tool name")
            tool = registry.get(tool_name) or self._find_tool_in_all(all_tools, tool_name)
            if not tool:
                available = [t.name for t in sorted(all_tools, key=lambda t: t.name)]
                console.print(f"[error]Unknown tool: {tool_name}[/error]")
                console.print(f"[dim]Available: {', '.join(available)}[/dim]")
                return CommandResult(success=False)

            if tool.name in denied_set:
                config.denied_tools.remove(tool.name)
            if allowed_set is not None and tool.name not in allowed_set:
                config.allowed_tools.append(tool.name)

            console.print(f"[green]Allowed:[/green] {tool.name}")
            self._refresh_tools_after_permission_change(agent, config, console)

        elif subcmd == "deny":
            if not tool_name:
                return CommandResult(success=False, message="Missing tool name")
            tool = registry.get(tool_name) or self._find_tool_in_all(all_tools, tool_name)
            if not tool:
                available = [t.name for t in sorted(all_tools, key=lambda t: t.name)]
                console.print(f"[error]Unknown tool: {tool_name}[/error]")
                console.print(f"[dim]Available: {', '.join(available)}[/dim]")
                return CommandResult(success=False)

            if tool.name not in config.denied_tools:
                config.denied_tools.append(tool.name)
            if allowed_set is not None and tool.name in allowed_set:
                config.allowed_tools.remove(tool.name)

            console.print(f"[red]Denied:[/red] {tool.name}")
            self._refresh_tools_after_permission_change(agent, config, console)

        elif subcmd == "reset":
            config.allowed_tools = None
            config.denied_tools = []
            console.print("[green]All tool permissions reset to allowed.[/green]")
            self._refresh_tools_after_permission_change(agent, config, console)

        else:
            console.print(f"[error]Unknown subcommand: {subcmd}[/error]")
            tool_names = [t.name for t in sorted(all_tools, key=lambda t: t.name)]
            console.print(
                f"[dim]Usage: /permissions [allow <tool_name>|deny <tool_name>|reset][/dim]"
            )
            console.print(f"[dim]Available tools: {', '.join(tool_names)}[/dim]")
            return CommandResult(success=False)

        return CommandResult(success=True)

    def get_help(self) -> str:
        return "View and manage tool permissions"

    def _find_tool_in_all(self, all_tools: list, name: str):
        for tool in all_tools:
            if tool.name == name:
                return tool
        return None

    def _refresh_tools_after_permission_change(
        self, agent: Any, config: Any, console: Any
    ) -> None:
        tools = agent.session.tool_registry.get_tools()
        agent.session.context_manager.refresh_system_prompt(tools=tools)
        active = len(tools)
        console.print(f"[dim]Active tools: {active}[/dim]")
