"""Model and approval commands: /model, /approval, /credentials."""

from .base import Command, CommandResult
from typing import Any
from config.config import ApprovalPolicy


class ModelCommand(Command):
    @property
    def name(self) -> str:
        return "/model"

    async def execute(self, args: str, context: dict[str, Any]) -> CommandResult:
        config = context.get("config")
        agent = context.get("agent")
        console = context.get("console")
        if not config or not console:
            return CommandResult(success=False, message="Missing context")

        if args:
            config.model_name = args
            console.print(f"[success]Model changed to: {args}[/success]")

            if agent and agent.session:
                tools = agent.session.tool_registry.get_tools()
                agent.session.context_manager.refresh_system_prompt(tools=tools)
                console.print("[dim]System prompt updated with new model info[/dim]")

                # Save to project config (local only, preserving comments)
                project_config_path = config.cwd / ".simhacli" / "config.toml"
                if project_config_path.parent.exists():
                    try:
                        from config.loader import set_config_value

                        set_config_value("model", "name", args, config_path=project_config_path)
                        console.print(f"[dim]Model saved to project config: {project_config_path}[/dim]")
                    except Exception as e:
                        console.print(f"[warning]Could not save to project config: {e}[/warning]")
        else:
            console.print(f"Current model: {config.model_name}")

        return CommandResult(success=True)

    def get_help(self) -> str:
        return "View or change the model. Usage: /model <model_name>"


class ApprovalCommand(Command):
    @property
    def name(self) -> str:
        return "/approval"

    async def execute(self, args: str, context: dict[str, Any]) -> CommandResult:
        config = context.get("config")
        console = context.get("console")
        if not config or not console:
            return CommandResult(success=False, message="Missing context")

        if args:
            try:
                approval = ApprovalPolicy(args)
                config.approval = approval
                console.print(f"[success]Approval policy changed to: {args}[/success]")
                
                # Save to project config (local only, preserving comments)
                project_config_path = config.cwd / ".simhacli" / "config.toml"
                if project_config_path.parent.exists():
                    try:
                        from config.loader import set_config_value
                        set_config_value("", "approval", args, config_path=project_config_path)
                        console.print(f"[dim]Approval saved to project config: {project_config_path}[/dim]")
                    except Exception as e:
                        console.print(f"[warning]Could not save to project config: {e}[/warning]")
            except ValueError:
                console.print(f"[error]Incorrect approval policy: {args}[/error]")
                console.print(f"Valid options: {', '.join(p.value for p in ApprovalPolicy)}")
        else:
            console.print(f"Current approval policy: {config.approval.value}")

        return CommandResult(success=True)

    def get_help(self) -> str:
        return "View or change approval policy. Usage: /approval <policy>"


class CredentialsCommand(Command):
    @property
    def name(self) -> str:
        return "/credentials"

    async def execute(self, args: str, context: dict[str, Any]) -> CommandResult:
        config = context.get("config")
        agent = context.get("agent")
        console = context.get("console")
        if not config or not console:
            return CommandResult(success=False, message="Missing context")

        from rich.prompt import Prompt, Confirm
        from rich.panel import Panel
        from config.loader import get_config_file_path, set_config_value, _mask_api_key

        config_path = get_config_file_path()

        if not args:
            api_key = config.get_api_key()
            api_base_url = config.get_api_base_url()

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
            return CommandResult(success=True)

        operation = args.strip()

        api_base_url = config.get_api_base_url()
        api_key = config.get_api_key()

        if operation == "update":
            console.print()
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
            set_config_value("auth", "api_base_url", api_base_url)
            config.api_base_url = api_base_url
            console.print(f"[green]✓ Base URL updated: {api_base_url}[/green]")

            console.print()
            new_key = Prompt.ask(
                "[bold yellow]Enter new API Key[/bold yellow]", password=True
            )
            if new_key.strip():
                api_key = new_key.strip()
                set_config_value("auth", "api_key", api_key)
                config.api_key = api_key
                console.print(f"[green]✓ API Key updated: {_mask_api_key(api_key)}[/green]")
            else:
                console.print("[dim]API Key unchanged[/dim]")

        elif operation == "key":
            console.print()
            new_key = Prompt.ask(
                "[bold yellow]Enter new API Key[/bold yellow]", password=True
            )
            if new_key.strip():
                api_key = new_key.strip()
                set_config_value("auth", "api_key", api_key)
                config.api_key = api_key
                console.print(f"[green]✓ API Key updated: {_mask_api_key(api_key)}[/green]")
            else:
                console.print("[dim]API Key unchanged[/dim]")

        elif operation == "url":
            console.print()
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
            set_config_value("auth", "api_base_url", api_base_url)
            config.api_base_url = api_base_url
            console.print(f"[green]✓ Base URL updated: {api_base_url}[/green]")

        else:
            console.print(f"[error]Unknown operation: {operation}[/error]")
            return CommandResult(success=False)

        console.print(f"\n[green]✓ Credentials saved to: {config_path}[/green]")

        if agent and agent.session:
            await agent.session.client.close_client()
            console.print("[dim]LLM client will use new credentials on next request[/dim]")

        return CommandResult(success=True)

    def get_help(self) -> str:
        return "View or update API credentials. Usage: /credentials [update|key|url]"


class CredsAliasCommand(CredentialsCommand):
    """Alias for /credentials."""

    @property
    def name(self) -> str:
        return "/creds"

