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


def _ensure_gitignore(cwd: Path) -> None:
    """Ensure .gitignore exists and includes .simhacli."""
    gitignore_path = cwd / ".gitignore"
    simhacli_entry = ".simhacli"

    if not gitignore_path.exists():
        # Create .gitignore with .simhacli entry
        gitignore_path.write_text(
            "# SimhaCLI config (contains API keys, do not commit)\n" ".simhacli/\n",
            encoding="utf-8",
        )
        logger.info(f"Created .gitignore with .simhacli entry at {gitignore_path}")
        return

    # Check if .simhacli is already in .gitignore
    content = gitignore_path.read_text(encoding="utf-8")
    lines = content.split("\n")

    for line in lines:
        stripped = line.strip()
        if (
            stripped == simhacli_entry
            or stripped == ".simhacli/"
            or stripped == "/.simhacli"
        ):
            return  # Already exists

    # Append .simhacli to existing .gitignore
    if content and not content.endswith("\n"):
        content += "\n"
    content += "\n# SimhaCLI config (contains API keys, do not commit)\n"
    content += ".simhacli/\n"
    gitignore_path.write_text(content, encoding="utf-8")
    logger.info(f"Added .simhacli to .gitignore at {gitignore_path}")


def _initialize_project_dir(cwd: Path) -> None:
    """Initialize .simhacli directory structure if it doesn't exist."""
    curdir = cwd.resolve()
    agent_dir = curdir / ".simhacli"

    # Ensure .gitignore includes .simhacli
    _ensure_gitignore(curdir)

    # Create .simhacli directory if it doesn't exist
    if not agent_dir.exists():
        agent_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"Initialized .simhacli directory at {agent_dir}")

        # Create a comprehensive config template
        config_file = agent_dir / CONFIG_FILE_NAME
        if not config_file.exists():
            # Create detailed config file with examples
            config_content = """# ═══════════════════════════════════════════════════════════════════════
# SimhaCLI Project Configuration
# ═══════════════════════════════════════════════════════════════════════
# This file allows you to customize SimhaCLI settings for THIS PROJECT ONLY
# Settings here override the global configuration (~/.simhacli/config.toml)
# Uncomment lines to activate them by removing the '#' at the beginning
# ═══════════════════════════════════════════════════════════════════════

# ───────────────────────────────────────────────────────────────────────
# MODEL CONFIGURATION
# ───────────────────────────────────────────────────────────────────────
# Override which AI model to use for this project
[model]
name = "openrouter/free"
# temperature = 1.0              # Creativity level (0.0-2.0, higher = more creative)
# context_window = 256000        # Maximum context size

# Popular free models on OpenRouter:
# - "openrouter/free" (access to multiple free models)
# - "openrouter/hunter-alpha" (specialized in code generation Recommended for coding tasks)
# - "openrouter/healer-alpha" (specialized in debugging and fixing code issues Recommended for debugging tasks)


# ───────────────────────────────────────────────────────────────────────
# PROJECT INSTRUCTIONS
# ───────────────────────────────────────────────────────────────────────
# Add custom instructions specific to this project
# user_instructions = "Always use 4 spaces for indentation in Python files"
# developer_instructions = "Follow PEP 8 style guide strictly"

# ───────────────────────────────────────────────────────────────────────
# APPROVAL POLICY
# ───────────────────────────────────────────────────────────────────────
# Control when to ask for permission before executing tools
# approval = "on_request"        # Ask for permission when needed (default)
# approval = "always"            # Ask before every tool execution
# approval = "auto_approve"      # Auto-approve safe operations
# approval = "yolo"              # Never ask (use with caution!)

# ───────────────────────────────────────────────────────────────────────
# BEHAVIOR SETTINGS
# ───────────────────────────────────────────────────────────────────────
# max_turns = 72                 # Maximum conversation turns per session
# max_tool_output_tokens = 50000 # Maximum tokens from tool outputs
# debug = false                  # Enable debug logging

# ───────────────────────────────────────────────────────────────────────
# HOOKS SYSTEM
# ───────────────────────────────────────────────────────────────────────
# Execute custom scripts/commands at specific points during execution
# hooks_enabled = true

# Example: Run tests before agent processes a request
# [[hooks]]
# name = "pre_check"
# trigger = "before_agent"       # Options: before_tool, after_tool, before_agent, after_agent, on_error
# command = "pytest tests/"
# enabled = true

# Example: Format code after file edits
# [[hooks]]
# name = "auto_format"
# trigger = "after_tool"
# command = "black ."
# enabled = true

# ───────────────────────────────────────────────────────────────────────
# SHELL ENVIRONMENT CUSTOMIZATION
# ───────────────────────────────────────────────────────────────────────
# [shell_environment]
# ignore_default_excludes = false
# exclude_patterns = ["*KEY*", "*TOKEN*", "*SECRET*"]  # Patterns to exclude from shell env
# set_vars = { "CUSTOM_VAR" = "value" }                # Set custom environment variables

# ───────────────────────────────────────────────────────────────────────
# MCP SERVERS (Model Context Protocol)
# ───────────────────────────────────────────────────────────────────────
# Connect to external tools and services via MCP protocol
# Uncomment and configure the servers you need, then restart SimhaCLI
#
# *** SECURITY: This file is inside .simhacli/ which is gitignored ***
# *** Your API keys and tokens will NOT be pushed to GitHub ***
# *** Never copy real keys into other files or share them ***

# GitHub MCP - Create repos, manage PRs, issues
# [mcp_servers.github]
# command = "npx"
# args = ["-y", "@modelcontextprotocol/server-github"]
# env = { GITHUB_PERSONAL_ACCESS_TOKEN = "ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx" }
# Get token at: https://github.com/settings/tokens (scopes: repo, workflow, gist)

# PostgreSQL MCP - Query and manage PostgreSQL databases
# [mcp_servers.postgresql]
# command = "npx"
# args = ["-y", "@modelcontextprotocol/server-postgres"]
# env = { DATABASE_URL = "postgresql://postgres:password@db.abcdef.supabase.co:5432/postgres" }

# Supabase MCP - Manage Supabase projects, databases, edge functions
# [mcp_servers.supabase]
# command = "npx"
# args = [
#   "-y",
#   "@supabase/mcp-server-supabase",
#   "--access-token", "sbp_xxxxxxxxxxxx",
#   "--project-ref", "abcdefghijklmnop"
# ]
# Get access token at: https://supabase.com/dashboard → Account → Access Tokens
# Get project ref from: https://supabase.com/dashboard → Project Settings → General

# Vercel MCP - Deploy to Vercel, manage projects
# [mcp_servers.vercel]
# command = "npx"
# args = ["-y", "vercel-mcp-adapter"]
# env = { VERCEL_TOKEN = "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxx" }
# Get token at: https://vercel.com/account/tokens
# After configuring, restart SimhaCLI and authorize access when prompted in browser

# Playwright MCP - Browser automation and E2E testing
# [mcp_servers.playwright]
# command = "npx"
# args = ["-y", "@playwright/mcp"]

# Filesystem MCP - Access project files (uses your project directory automatically)
# [mcp_servers.filesystem]
# command = "npx"
# args = ["-y", "@modelcontextprotocol/server-filesystem", "{cwd}"]
# enabled = true

# Example: HTTP-based MCP server
# [mcp_servers.custom_service]
# url = "http://localhost:3000/mcp"
# enabled = true

# ───────────────────────────────────────────────────────────────────────
# TOOL RESTRICTIONS
# ───────────────────────────────────────────────────────────────────────
# Limit which tools the agent can use in this project
# allowed_tools = ["read_file", "write_file", "edit_file", "shell", "grep"]

# ═══════════════════════════════════════════════════════════════════════
# For more information, visit: https://github.com/narasimhanaidukorrapati/simhacli
# ═══════════════════════════════════════════════════════════════════════
"""
            config_content = config_content.replace("{cwd}", str(curdir))
            config_file.write_text(config_content, encoding="utf-8")
            logger.info(f"Created project config template at {config_file}")


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


def _update_config_value(config_path: Path, section: str, key: str, value: str) -> bool:
    """Update a single value in a TOML file while preserving comments and structure.

    Returns True if the value was updated, False if the file structure wasn't found.
    """
    if not config_path.exists():
        return False

    content = config_path.read_text(encoding="utf-8")
    lines = content.split("\n")

    in_section = False
    updated = False
    section_pattern = f"[{section}]"

    for i, line in enumerate(lines):
        stripped = line.strip()

        # Check if we're entering the target section
        if stripped == section_pattern:
            in_section = True
            continue

        # Check if we've entered a different section (exit target section)
        if stripped.startswith("[") and stripped.endswith("]") and in_section:
            in_section = False
            continue

        # If we're in the target section, look for the key
        if in_section and stripped.startswith(f"{key}"):
            # Check if it's a commented key like "# name = ..."
            if stripped.startswith("#"):
                # Uncomment and update the value
                lines[i] = f'{key} = "{value}"'
                updated = True
                break
            elif stripped.startswith(f"{key} =") or stripped.startswith(f'{key}="'):
                # Update existing uncommented key
                # Preserve the indentation
                indent = line[: len(line) - len(line.lstrip())]
                lines[i] = f'{indent}{key} = "{value}"'
                updated = True
                break

    if updated:
        config_path.write_text("\n".join(lines), encoding="utf-8")
        logger.info(f"Updated {section}.{key} in {config_path}")

    return updated


def _add_commented_section(
    config_path: Path, section: str, commented_lines: list[str]
) -> None:
    """Add a commented-out section to the config file if it doesn't already exist."""
    if not config_path.exists():
        return

    content = config_path.read_text(encoding="utf-8")

    # Check if section already exists (commented or not)
    if f"[{section}]" in content or f"# [{section}]" in content:
        return

    # Append the commented section
    content += "\n" + "\n".join(commented_lines) + "\n"
    config_path.write_text(content, encoding="utf-8")
    logger.info(f"Added commented [{section}] section to {config_path}")


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
            console.print()

            # Show instructions for getting OpenRouter API key
            console.print(
                Panel(
                    "[bold cyan]How to Get Your OpenRouter API Key:[/bold cyan]\n\n"
                    "[bold]1.[/bold] Visit [link=https://openrouter.ai]https://openrouter.ai[/link]\n"
                    "[bold]2.[/bold] Click [bold green]'Sign In'[/bold green] or [bold green]'Get Started'[/bold green] in the top right\n"
                    "[bold]3.[/bold] Sign in with your Google, GitHub, or Discord account\n"
                    "[bold]4.[/bold] Go to [bold]'Keys'[/bold] section in your dashboard\n"
                    "[bold]5.[/bold] Click [bold green]'Create Key'[/bold green] to generate a new API key\n"
                    "[bold]6.[/bold] Copy the key and paste it below\n\n"
                    "[dim]💡 Tip: OpenRouter provides Free models to get started! (OR)[/dim]"
                    "[dim] provides $1 free credit to get started![/dim]",
                    title="[bold yellow]🔑 API Key Setup[/bold yellow]",
                    border_style="cyan",
                )
            )
            console.print()
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

    # Initialize .simhacli directory if it doesn't exist
    _initialize_project_dir(cwd)

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

        # If user chose OpenRouter on first setup and no model is configured, default to openrouter/free
        if api_base_url == DEFAULT_API_BASE_URL and not existing_config.get(
            "model", {}
        ).get("name"):
            existing_config.setdefault("model", {})["name"] = "openrouter/free"
            config_dict.setdefault("model", {})["name"] = "openrouter/free"

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
