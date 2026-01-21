from pathlib import Path
import os
import re
import tomllib
from typing import Any

from config.config import Config
from platformdirs import user_config_dir, user_data_dir
from utils.errors import ConfigError
import logging

logger = logging.getLogger(__name__)

CONFIG_FILE_NAME = "config.toml"

AGENT_MD_FILE = "AGENT.MD"

# Default API base URL for OpenRouter
DEFAULT_API_BASE_URL = "https://openrouter.ai/api/v1"


def get_config_dir() -> Path:
    # On Windows, user_config_dir returns something like:
    # C:\Users\<User>\AppData\Local\<appname>\<appname>
    # We want just C:\Users\<User>\AppData\Local\simhacli
    config_path = Path(user_config_dir("simhacli"))
    # Check if it has double simhacli and fix it
    if config_path.name == "simhacli" and config_path.parent.name == "simhacli":
        config_path = config_path.parent
    return config_path


def get_config_file_path() -> Path:
    config_dir = get_config_dir()
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir / CONFIG_FILE_NAME


def get_data_dir() -> Path:
    # On Windows, user_data_dir returns something like:
    # C:\Users\<User>\AppData\Local\<appname>\<appname>
    # We want just C:\Users\<User>\AppData\Local\simhacli
    data_path = Path(user_data_dir("simhacli"))
    # Check if it has double simhacli and fix it
    if data_path.name == "simhacli" and data_path.parent.name == "simhacli":
        data_path = data_path.parent
    return data_path


def _parse_toml(path: Path) -> dict:
    try:
        with path.open("rb") as f:
            return tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(
            f"Failed to parse config file: {path}: {e}",
            config_file=str(path),
            cause=e,
        )
    except Exception as e:
        raise ConfigError(
            f"Failed to read config file: {path}: {e}",
            config_file=str(path),
            cause=e,
        )


def _get_project_config_file(cwd: Path) -> Path | None:
    curdir = cwd.resolve()
    agent_dir = curdir / ".simhacli"
    if agent_dir.is_dir():
        config_file = agent_dir / CONFIG_FILE_NAME
        if config_file.is_file():
            return config_file
    return None


def _get_agent_md_file(cwd: Path) -> str | None:
    curdir = cwd.resolve()

    if curdir.is_dir():
        agent_md_file = curdir / AGENT_MD_FILE
        if agent_md_file.is_file():
            content = agent_md_file.read_text(encoding="utf-8")
            return content
    return None


def _merge_dicts(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _merge_dicts(result[key], value)
        else:
            result[key] = value
    return result


def _save_config_toml(config_path: Path, config_dict: dict[str, Any]) -> None:
    """Save configuration dictionary to a TOML file."""
    import tomli_w

    config_path.parent.mkdir(parents=True, exist_ok=True)

    # Filter out None values and non-serializable items
    serializable = {}
    for key, value in config_dict.items():
        if value is not None and not key.startswith("_"):
            if isinstance(value, Path):
                serializable[key] = str(value)
            elif isinstance(value, (str, int, float, bool, list, dict)):
                serializable[key] = value

    with config_path.open("wb") as f:
        tomli_w.dump(serializable, f)

    logger.info(f"Saved config to {config_path}")


def _mask_api_key(api_key: str) -> str:
    """Mask API key for display, showing only first 4 and last 4 characters."""
    if len(api_key) <= 12:
        return api_key[:4] + "*" * (len(api_key) - 4)
    return api_key[:4] + "*" * (len(api_key) - 8) + api_key[-4:]


def _prompt_for_api_credentials(
    config_dict: dict[str, Any], config_path: Path
) -> tuple[str | None, str | None]:
    """Prompt user for API credentials if not configured."""
    from rich.console import Console
    from rich.prompt import Prompt, Confirm
    from rich.panel import Panel

    console = Console()

    api_key = config_dict.get("api_key") or os.environ.get("API_KEY")
    api_base_url = config_dict.get("api_base_url") or os.environ.get("API_BASE_URL")

    if api_key and api_base_url:
        return api_key, api_base_url

    # Show setup panel
    console.print()
    console.print(
        Panel(
            "[bold yellow]🔑 API Configuration Required[/bold yellow]\n\n"
            "SimhaCLI needs an API key and base URL to connect to an LLM provider.\n"
            "These will be saved to your config file for future use.\n\n"
            f"[dim]Config file location: {config_path}[/dim]\n"
            "[dim]Tip: You can use OpenRouter (https://openrouter.ai) for access to multiple models.[/dim]",
            title="[bold]First Time Setup[/bold]",
            border_style="yellow",
        )
    )
    console.print()

    # Step 1: Ask about base URL first
    if not api_base_url:
        console.print(
            f"[bold cyan]Default API Base URL:[/bold cyan] {DEFAULT_API_BASE_URL}"
        )
        use_default = Confirm.ask(
            "[bold yellow]Do you want to use OpenRouter as your API provider?[/bold yellow]",
            default=True,
        )

        if use_default:
            api_base_url = DEFAULT_API_BASE_URL
            console.print(f"[green]✓ Using OpenRouter: {api_base_url}[/green]")
        else:
            api_base_url = Prompt.ask(
                "[bold yellow]Enter your custom API Base URL[/bold yellow]"
            )
            if not api_base_url.strip():
                console.print("[red]API Base URL is required.[/red]")
                raise ConfigError("API Base URL is required", config_file="")
            api_base_url = api_base_url.strip()
            console.print(f"[green]✓ Using custom URL: {api_base_url}[/green]")

        console.print()

    # Step 2: Ask for API key
    if not api_key:
        api_key = Prompt.ask(
            "[bold yellow]Enter your API Key[/bold yellow]",
            password=True,  # Hide the input
        )
        if not api_key.strip():
            console.print("[red]API Key is required to use SimhaCLI.[/red]")
            raise ConfigError("API Key is required", config_file="")
        api_key = api_key.strip()

    console.print()
    console.print("[green]✓ API credentials configured successfully![/green]")
    console.print()
    console.print(f"[dim]API Key: {_mask_api_key(api_key)}[/dim]")
    console.print(f"[dim]Base URL: {api_base_url}[/dim]")
    console.print(f"[dim]Saved to: {config_path}[/dim]")
    console.print()

    return api_key, api_base_url


def load_config(cwd: Path | None = None) -> Config:
    cwd = cwd or Path.cwd()

    # C:\Users\Naidu\AppData\Local\simhacli\config.toml ( it is platform dependent, from platformdirs when users setup simhacli first time)

    # \SimhaCLI\.simhacli\config.toml (project config file in the current working directory if exists)

    system_path = get_config_file_path()
    config_dict: dict[str, Any] = {}
    if system_path.is_file():
        try:
            config_dict = _parse_toml(system_path)
            logger.info(f"Loaded system config from {system_path}")
        except ConfigError as e:
            logger.warning(f"Skipping invalid config file: {system_path}: {e}")
    project_path = _get_project_config_file(cwd)
    if project_path:
        try:
            project_config_dict = _parse_toml(project_path)
            config_dict = _merge_dicts(config_dict, project_config_dict)
        except ConfigError:
            logger.warning(f"Skipping invalid system config: {system_path}")

    if "cwd" not in config_dict:
        config_dict["cwd"] = cwd

    if "developer_instructions" not in config_dict:
        agent_md_content = _get_agent_md_file(cwd)
        if agent_md_content:
            config_dict["developer_instructions"] = agent_md_content

    # Check for API credentials and prompt if missing
    api_key, api_base_url = _prompt_for_api_credentials(config_dict, system_path)

    # Update config_dict with credentials
    credentials_updated = False
    if api_key and config_dict.get("api_key") != api_key:
        config_dict["api_key"] = api_key
        credentials_updated = True
    if api_base_url and config_dict.get("api_base_url") != api_base_url:
        config_dict["api_base_url"] = api_base_url
        credentials_updated = True

    # Save credentials to system config if they were updated (not from env vars)
    if credentials_updated:
        # Load existing system config to preserve other settings
        existing_config: dict[str, Any] = {}
        if system_path.is_file():
            try:
                existing_config = _parse_toml(system_path)
            except ConfigError:
                pass

        # Update with new credentials
        existing_config["api_key"] = api_key
        existing_config["api_base_url"] = api_base_url

        # Save to system config file
        _save_config_toml(system_path, existing_config)

    try:
        config = Config(**config_dict)
    except Exception as e:
        raise ConfigError(
            f"Failed to validate configuration: {e}",
            config_file=str(system_path),
            cause=e,
        )
    return config
