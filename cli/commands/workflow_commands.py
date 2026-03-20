"""Workflow command: /workflow."""

from .base import Command, CommandResult
from typing import Any
from rich.panel import Panel
from rich.table import Table


class WorkflowCommand(Command):
    @property
    def name(self) -> str:
        return "/workflow"

    async def execute(self, args: str, context: dict[str, Any]) -> CommandResult:
        agent = context.get("agent")
        console = context.get("console")
        if not agent or not console:
            return CommandResult(success=False, message="Missing context")

        if not args:
            console.print()
            console.print(
                Panel(
                    "[bold]Available Workflows[/bold]\n\n"
                    "[cyan]fullstack[/cyan] - End-to-end app development:\n"
                    "  1. Create GitHub repository\n"
                    "  2. Setup PostgreSQL database\n"
                    "  3. Deploy to Vercel\n"
                    "  4. Run Playwright tests\n\n"
                    "[dim]Usage:[/dim]\n"
                    "  /workflow fullstack <repo_name> <db_name> <project_path>\n\n"
                    "[dim]Example:[/dim]\n"
                    "  /workflow fullstack my-app myapp_db ./my-app\n\n"
                    "[dim]Optional params:[/dim]\n"
                    "  --description <desc>  - Repo description\n"
                    "  --private             - Make repo private\n"
                    "  --test-url <url>      - Custom test URL",
                    title="[bold yellow]/workflow[/bold yellow]",
                    border_style="yellow",
                )
            )
            return CommandResult(success=True)

        parts = args.split()
        workflow_name = parts[0]

        if workflow_name == "fullstack":
            if len(parts) < 4:
                console.print(
                    "[error]Usage: /workflow fullstack <repo_name> <db_name> <project_path>[/error]"
                )
                console.print(
                    "[dim]Example: /workflow fullstack my-app myapp_db ./my-app[/dim]"
                )
                return CommandResult(success=False)

            repo_name = parts[1]
            db_name = parts[2]
            project_path = parts[3]

            repo_description = ""
            repo_private = False
            test_url = None

            i = 4
            while i < len(parts):
                if parts[i] == "--description" and i + 1 < len(parts):
                    repo_description = parts[i + 1]
                    i += 2
                elif parts[i] == "--private":
                    repo_private = True
                    i += 1
                elif parts[i] == "--test-url" and i + 1 < len(parts):
                    test_url = parts[i + 1]
                    i += 2
                else:
                    i += 1

            mcp_status = agent.session.mcp_manager.get_all_servers()
            console.print()
            console.print("[bold cyan]MCP Server Status:[/bold cyan]")

            table = Table(show_header=True, border_style="dim")
            table.add_column("Server", style="cyan")
            table.add_column("Status", style="green")
            table.add_column("Tools", justify="right")

            for server in mcp_status:
                status_style = "green" if server["status"] == "connected" else "red"
                table.add_row(
                    server["name"],
                    f"[{status_style}]{server['status']}[/{status_style}]",
                    str(server["tools"]),
                )

            console.print(table)

            workflow_tool = agent.session.tool_registry.get("workflow")
            if not workflow_tool:
                console.print("[error]Workflow tool not available[/error]")
                return CommandResult(success=False)

            console.print()
            console.print(f"[bold]Running fullstack workflow:[/bold]")
            console.print(f"  Repo: {repo_name}")
            console.print(f"  Database: {db_name}")
            console.print(f"  Project: {project_path}")

            from tools.base import ToolInvocation

            params = {
                "workflow": "fullstack",
                "repo_name": repo_name,
                "db_name": db_name,
                "project_path": project_path,
            }

            if repo_description:
                params["repo_description"] = repo_description
            if repo_private:
                params["repo_private"] = True
            if test_url:
                params["test_url"] = test_url

            invocation = ToolInvocation(
                params=params,
                cwd=context["config"].cwd,
            )

            try:
                result = await workflow_tool.execute(invocation)

                if result.success:
                    console.print()
                    console.print("[success]✅ Workflow completed successfully![/success]")
                    console.print(result.output)
                else:
                    console.print()
                    console.print(f"[error]❌ Workflow failed: {result.error}[/error]")
                    if result.output:
                        console.print(result.output)

            except Exception as e:
                console.print(f"[error]Error executing workflow: {e}[/error]")

            return CommandResult(success=result.success if 'result' in locals() else False)

        else:
            console.print(f"[error]Unknown workflow: {workflow_name}[/error]")
            console.print("[dim]Available workflows: fullstack[/dim]")
            return CommandResult(success=False)

    def get_help(self) -> str:
        return "Run development workflows. Usage: /workflow <workflow_name> [args]"
