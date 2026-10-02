"""Model and approval commands: /model, /approval, /credentials."""

from typing import Any

from rich.markup import escape

from config.config import ApprovalPolicy
from services import settings
from .base import Command, CommandResult


def _print_save_result(console: Any, what: str, result: settings.SaveResult) -> None:
    if result.path:
        console.print(f"[dim]{what} saved to project config: {escape(str(result.path))}[/dim]")
    elif result.error:
        console.print(f"[warning]Could not save to project config: {escape(result.error)}[/warning]")


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

        args = args.strip()
        if args:
            result = settings.set_model(agent, config, args)
            console.print(f"[success]Model changed to: {escape(args)}[/success]")
            if agent and agent.session:
                console.print("[dim]System prompt updated with new model info[/dim]")
            _print_save_result(console, "Model", result)
        else:
            console.print(f"Current model: {escape(str(config.model_name))}")

        return CommandResult(success=True)

    def get_help(self) -> str:
        return "View or change the model. Usage: /model <model_name>"


class ApprovalCommand(Command):
    @property
    def name(self) -> str:
        return "/approval"

    async def execute(self, args: str, context: dict[str, Any]) -> CommandResult:
        config = context.get("config")
        agent = context.get("agent")
        console = context.get("console")
        if not config or not console:
            return CommandResult(success=False, message="Missing context")

        args = args.strip().lower()
        if args:
            try:
                _, result = settings.set_approval(agent, config, args)
                console.print(f"[success]Approval policy changed to: {escape(args)}[/success]")
                _print_save_result(console, "Approval", result)
            except ValueError:
                console.print(f"[error]Incorrect approval policy: {escape(args)}[/error]")
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
        from config.loader import get_config_file_path, _mask_api_key

        config_path = get_config_file_path()

        if not args:
            api_key = config.get_api_key()
            api_base_url = config.get_api_base_url()

            console.print()
            console.print(
                Panel(
                    f"[bold]API Base URL:[/bold] {escape(api_base_url) if api_base_url else '[dim]Not set[/dim]'}\n"
                    f"[bold]API Key:[/bold] {escape(_mask_api_key(api_key)) if api_key else '[dim]Not set[/dim]'}\n\n"
                    f"[dim]Config file: {escape(str(config_path))}[/dim]",
                    title="[bold yellow]🔑 Current Credentials[/bold yellow]",
                    border_style="yellow",
                )
            )
            console.print()
            console.print("[dim]Use '/credentials update' to change credentials[/dim]")
            console.print("[dim]Use '/credentials key' to update only API key[/dim]")
            console.print("[dim]Use '/credentials url' to update only base URL[/dim]")
            return CommandResult(success=True)

        operation = args.strip().lower()

        api_base_url = config.get_api_base_url()
        new_url: str | None = None
        new_key: str | None = None

        def ask_base_url() -> str:
            console.print()
            use_openrouter = Confirm.ask(
                "[bold yellow]Use OpenRouter (https://openrouter.ai/api/v1)?[/bold yellow]",
                default=True,
            )
            if use_openrouter:
                return "https://openrouter.ai/api/v1"
            return Prompt.ask(
                "[bold yellow]Enter new API Base URL[/bold yellow]",
                default=api_base_url or "",
            )

        def ask_api_key() -> str | None:
            console.print()
            entered = Prompt.ask(
                "[bold yellow]Enter new API Key[/bold yellow]", password=True
            )
            return entered.strip() or None

        if operation == "update":
            new_url = ask_base_url()
            new_key = ask_api_key()
        elif operation == "key":
            new_key = ask_api_key()
        elif operation == "url":
            new_url = ask_base_url()
        else:
            console.print(f"[error]Unknown operation: {escape(operation)}[/error]")
            return CommandResult(success=False)

        config_path = await settings.set_credentials(
            agent, config, api_key=new_key, base_url=new_url
        )
        if new_url:
            console.print(f"[green]✓ Base URL updated: {escape(new_url)}[/green]")
        if new_key:
            console.print(f"[green]✓ API Key updated: {escape(_mask_api_key(new_key))}[/green]")
        elif operation in ("update", "key"):
            console.print("[dim]API Key unchanged[/dim]")

        console.print(f"\n[green]✓ Credentials saved to: {escape(str(config_path))}[/green]")
        if agent and agent.session:
            console.print("[dim]LLM client will use new credentials on next request[/dim]")

        return CommandResult(success=True)

    def get_help(self) -> str:
        return "View or update API credentials. Usage: /credentials [update|key|url]"


class CredsAliasCommand(CredentialsCommand):
    """Alias for /credentials."""

    @property
    def name(self) -> str:
        return "/creds"

