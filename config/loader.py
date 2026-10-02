from pathlib import Path
import os
import re
import sys
import tempfile
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # Python < 3.11
    import tomli as tomllib

from config.config import Config
from platformdirs import user_config_dir, user_data_dir
from utils.errors import ConfigError
import logging

logger = logging.getLogger(__name__)

CONFIG_FILE_NAME = "config.toml"

AGENT_MD_FILE = "AGENTS.md"
# Fallback names (matched case-insensitively) if AGENTS.md is not present
AGENT_MD_FALLBACK_NAMES = ("agents.md", "agent.md")

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


PROJECT_CONFIG_TEMPLATE = """# ═══════════════════════════════════════════════════════════════════════
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
# (by default the model from your global config is used)
# [model]
# name = "openrouter/free"
# temperature = 1.0              # Creativity level (0.0-2.0, higher = more creative)
# context_window = 256000        # Maximum context size
# supports_vision = false        # Set to true if your model can process images


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

# Example: Auto-format code after file edits
# [[hooks]]
# name = "format_on_write"
# trigger = "after_tool"       # Options: before_tool, after_tool, before_agent, after_agent, on_error
# command = "black {file}"     # {file} placeholder available for after_tool/after_agent
# time_out_sec = 30.0
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
# Core MCP servers are enabled by default. Uncomment additional servers as needed.
#
# *** SECURITY: This file is inside .simhacli/ which is gitignored ***
# *** Your API keys and tokens will NOT be pushed to GitHub ***
# *** Never copy real keys into other files or share them ***

# Filesystem MCP - Access project files (uses {cwd} placeholder automatically)
[mcp_servers.filesystem]
command = "npx"
args = ["-y", "@modelcontextprotocol/server-filesystem", "{cwd}"]
enabled = true

# Sequential Thinking MCP - Explicit reasoning scratchpad for complex multi-step tasks
[mcp_servers.sequential_thinking]
command = "npx"
args = ["-y", "@modelcontextprotocol/server-sequentialthinking"]
enabled = true

# Memory MCP - Persists knowledge graph across sessions
[mcp_servers.memory]
command = "npx"
args = ["-y", "@modelcontextprotocol/server-memory"]
enabled = true

# Fetch MCP - Pull live docs, READMEs, API refs mid-task
[mcp_servers.fetch]
command = "npx"
args = ["-y", "@modelcontextprotocol/server-fetch"]
enabled = true

# ───────────────────────────────────────────────────────────────────────
# OPTIONAL MCP SERVERS (uncomment to enable)
# ───────────────────────────────────────────────────────────────────────

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

# ───────────────────────────────────────────────────────────────────────
# TOOL RESTRICTIONS
# ───────────────────────────────────────────────────────────────────────
# Limit which tools the agent can use in this project
# allowed_tools = ["read_file", "write_file", "edit_file", "shell", "grep"]

# ═══════════════════════════════════════════════════════════════════════
# For more information, visit: https://github.com/narasimhanaidukorrapati/simhacli
# ═══════════════════════════════════════════════════════════════════════
"""


def _initialize_project_dir(cwd: Path) -> None:
    """Initialize .simhacli directory structure if it doesn't exist.

    Failures (read-only directories, undecodable .gitignore, ...) are logged
    and ignored so they never prevent SimhaCLI from starting.
    """
    try:
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
                # DO NOT replace {cwd} placeholder - keep it as is for portability
                # The MCP server will substitute it at runtime
                _atomic_write_text(config_file, PROJECT_CONFIG_TEMPLATE)
                logger.info(f"Created project config template at {config_file}")
    except Exception as e:
        logger.warning(f"Could not initialize project directory at {cwd}: {e}")


def _get_project_config_file(cwd: Path) -> Path | None:
    curdir = cwd.resolve()
    agent_dir = curdir / ".simhacli"
    if agent_dir.is_dir():
        config_file = agent_dir / CONFIG_FILE_NAME
        if config_file.is_file():
            return config_file
    return None


def _get_agent_md_file(cwd: Path) -> str | None:
    """Return the project instructions file content (AGENTS.md), if any.

    Looks for AGENTS.md first, then falls back to a case-insensitive match
    of agents.md / agent.md in the project directory.
    """
    try:
        curdir = cwd.resolve()
        if not curdir.is_dir():
            return None

        agent_md_file: Path | None = curdir / AGENT_MD_FILE
        if not agent_md_file.is_file():
            agent_md_file = None
            entries = {
                entry.name.lower(): entry
                for entry in curdir.iterdir()
                if entry.is_file()
            }
            for name in AGENT_MD_FALLBACK_NAMES:
                if name in entries:
                    agent_md_file = entries[name]
                    break

        if agent_md_file is not None:
            return agent_md_file.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        logger.warning(f"Could not read project instructions file in {cwd}: {e}")
    return None


def _merge_dicts(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _merge_dicts(result[key], value)
        else:
            result[key] = value
    return result


def _atomic_write_text(path: Path, content: str) -> None:
    """Atomically write text to a config file with owner-only permissions.

    Config files may contain API keys and tokens, so the content is written to
    a temp file in the same directory (created with mode 0o600) and then moved
    into place with os.replace. chmod is skipped on Windows.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        if sys.platform != "win32":
            os.chmod(tmp_name, 0o600)
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def _save_config_toml(config_path: Path, config_dict: dict[str, Any]) -> None:
    """Save configuration dictionary to a TOML file."""
    import tomli_w

    # Filter out None values and non-serializable items
    serializable = {}
    for key, value in config_dict.items():
        if value is not None and not key.startswith("_"):
            if isinstance(value, Path):
                serializable[key] = str(value)
            elif isinstance(value, (str, int, float, bool, list, dict)):
                serializable[key] = value

    _atomic_write_text(config_path, tomli_w.dumps(serializable))

    logger.info(f"Saved config to {config_path}")


# Runtime/project-specific fields that must never be written to the global config
_RUNTIME_ONLY_FIELDS = {"cwd"}


def save_config(config: Config, exclude: set[str] | None = None) -> None:
    """Save the given Config object to the system config file.

    Runtime-only fields (like ``cwd``) are never saved; ``exclude`` can name
    additional top-level fields to leave out.
    """
    system_path = get_config_file_path()

    # Use Pydantic's model_dump to convert to dict, excluding None and private attrs
    config_dict = config.model_dump(
        exclude_none=True,
        exclude_unset=True,
        mode="json",
        exclude=_RUNTIME_ONLY_FIELDS | set(exclude or ()),
    )

    # Convert Path objects to strings
    def convert_paths(obj):
        if isinstance(obj, dict):
            return {k: convert_paths(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [convert_paths(item) for item in obj]
        elif isinstance(obj, Path):
            return str(obj)
        return obj

    config_dict = convert_paths(config_dict)

    _save_config_toml(system_path, config_dict)


_TABLE_HEADER_RE = re.compile(r"^\s*(\[\[?[^\[\]]*\]\]?)\s*(#.*)?$")


def _table_header(line: str) -> str | None:
    """Return the normalized table header (e.g. ``[model]``) if line is one."""
    m = _TABLE_HEADER_RE.match(line)
    return m.group(1).replace(" ", "") if m else None


def _assignment_key(line: str) -> tuple[str, bool] | None:
    """Return (key, is_commented) if the line is a (possibly commented) assignment."""
    stripped = line.strip()
    commented = stripped.startswith("#")
    if commented:
        stripped = stripped.lstrip("#").strip()
    if "=" not in stripped:
        return None
    return stripped.split("=", 1)[0].strip(), commented


def _value_block_end(lines: list[str], start: int, limit: int, commented: bool) -> int:
    """Return the exclusive end index of the ``key = value`` block at ``start``.

    The extent is found by accumulating lines until the fragment parses as TOML,
    which correctly handles multi-line arrays, inline tables and strings
    regardless of indentation (tomli_w puts the closing ``]`` at column 0).
    Falls back to the single key line if no prefix parses.
    """
    chunk: list[str] = []
    for j in range(start, limit):
        line = lines[j]
        if commented:
            stripped = line.strip()
            if not stripped.startswith("#"):
                break
            line = stripped[1:]
        chunk.append(line)
        try:
            tomllib.loads("\n".join(chunk))
            return j + 1
        except tomllib.TOMLDecodeError:
            continue
    return start + 1


def _set_key_in_region(
    lines: list[str],
    region_start: int,
    region_end: int,
    key: str,
    assignment_lines: list[str],
    is_top_level: bool,
) -> None:
    """Replace (or insert) ``key`` within lines[region_start:region_end] in place."""
    active_idx = None
    commented_idx = None
    for i in range(region_start, region_end):
        parsed = _assignment_key(lines[i])
        if parsed is None or parsed[0] != key:
            continue
        if not parsed[1]:
            active_idx = i
            break
        if commented_idx is None:
            commented_idx = i

    # Prefer the active assignment; only uncomment a commented example if there is none
    key_start_idx = active_idx if active_idx is not None else commented_idx
    if key_start_idx is not None:
        key_end_idx = _value_block_end(
            lines, key_start_idx, region_end, commented=active_idx is None
        )
        line = lines[key_start_idx]
        indent = line[: len(line) - len(line.lstrip())]
        replaced_lines = [f"{indent}{assignment_lines[0]}"] + assignment_lines[1:]
        lines[key_start_idx:key_end_idx] = replaced_lines
        return

    # Insert new key after the last real (non-blank, non-comment) line of the region
    insert_at = None
    for i in range(region_end - 1, region_start - 1, -1):
        stripped = lines[i].strip()
        if stripped and not stripped.startswith("#"):
            insert_at = i + 1
            break
    if insert_at is None:
        if is_top_level and region_end < len(lines):
            # Region has only comments: insert right before the first table header
            lines[region_end:region_end] = assignment_lines + [""]
            return
        insert_at = region_start if not is_top_level else region_end
    lines[insert_at:insert_at] = assignment_lines


def set_config_value(
    section: str, key: str, value: Any, config_path: Path | None = None
) -> None:
    """Set a configuration value in a TOML config file, preserving other content.

    If config_path is None, uses the system config file.
    Creates the file if it doesn't exist. If the section doesn't exist, it will be added.
    If section is "", the key is set at the top level (before the first table).
    If the key exists, it will be updated. If it's commented, it will be uncommented.
    Properly handles multi-line values (like lists) by replacing the entire value block.
    None values are not saved (TOML has no null).
    """
    import tomli_w

    if value is None:
        logger.info(f"Not saving {section}.{key}: value is None")
        return

    if config_path is None:
        config_path = get_config_file_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)

    # Generate the assignment line(s) using tomli_w
    assignment_lines = tomli_w.dumps({key: value}).strip().splitlines()

    section_header = f"[{section}]" if section else None

    # If file doesn't exist, create it with the section (if any) and assignment
    if not config_path.exists():
        header_lines = [section_header] if section_header else []
        content = "\n".join(header_lines + assignment_lines) + "\n"
        _atomic_write_text(config_path, content)
        logger.info(f"Created config with {section}.{key}")
        return

    # Read existing content as lines
    content = config_path.read_text(encoding="utf-8")
    original_valid = True
    try:
        tomllib.loads(content)
    except tomllib.TOMLDecodeError:
        original_valid = False

    # Drop bare "[]" headers written by older versions (never valid TOML)
    lines = [line for line in content.splitlines() if line.strip() != "[]"]

    if section_header:
        section_idx = None
        for i, line in enumerate(lines):
            if _table_header(line) == section_header:
                section_idx = i
                break

        if section_idx is not None:
            # Find the extent of the section (lines until next table header or end)
            section_start = section_idx + 1
            section_end = len(lines)
            for i in range(section_start, len(lines)):
                if _table_header(lines[i]) is not None:
                    section_end = i
                    break
            _set_key_in_region(
                lines, section_start, section_end, key, assignment_lines, False
            )
        else:
            # Section does not exist, append it at the end
            if lines and lines[-1].strip() != "":
                lines.append("")  # blank line separator
            lines.append(section_header)
            lines.extend(assignment_lines)
    else:
        # Top-level key — must live before the first table header
        first_table = len(lines)
        for i, line in enumerate(lines):
            if _table_header(line) is not None:
                first_table = i
                break
        _set_key_in_region(lines, 0, first_table, key, assignment_lines, True)

    new_content = "\n".join(lines) + "\n"

    # Never turn a valid config file into an invalid one
    try:
        tomllib.loads(new_content)
    except tomllib.TOMLDecodeError as e:
        if original_valid:
            raise ConfigError(
                f"Refusing to write invalid TOML while setting {section}.{key} "
                f"in {config_path}: {e}",
                config_file=str(config_path),
                cause=e,
            )
        logger.warning(f"Config file {config_path} is not valid TOML: {e}")

    _atomic_write_text(config_path, new_content)
    logger.info(f"Set {section}.{key} in {config_path}")


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
    _atomic_write_text(config_path, content)
    logger.info(f"Added commented [{section}] section to {config_path}")


def _mask_api_key(api_key: str) -> str:
    """Mask API key for display, showing only first 4 and last 4 characters."""
    if len(api_key) <= 12:
        return api_key[:4] + "*" * (len(api_key) - 4)
    return api_key[:4] + "*" * (len(api_key) - 8) + api_key[-4:]


def _prompt_for_api_credentials(
    config_dict: dict[str, Any], config_path: Path, prompt: bool = True
) -> tuple[str | None, str | None]:
    """Prompt user for API credentials if not configured.

    Args:
        config_dict: Configuration dictionary
        config_path: Path to config file (for display/saving)
        prompt: If True, interactively prompt for missing credentials.
                If False, just return what's available without prompting.

    Returns:
        Tuple of (api_key, api_base_url) - may be None if not configured and prompt=False
    """
    from rich.console import Console
    from rich.prompt import Prompt, Confirm
    from rich.panel import Panel

    console = Console()

    api_key = config_dict.get("api_key") or os.environ.get("API_KEY")
    api_base_url = config_dict.get("api_base_url") or os.environ.get("API_BASE_URL")

    # If credentials are available or we're not prompting, return early
    if (api_key and api_base_url) or not prompt:
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


def _template_mcp_servers() -> dict[str, Any]:
    """MCP servers enabled by default in the auto-generated project template."""
    try:
        return tomllib.loads(PROJECT_CONFIG_TEMPLATE).get("mcp_servers", {})
    except tomllib.TOMLDecodeError:
        return {}


def _warn_about_risky_project_config(
    project_path: Path, project_config: dict[str, Any]
) -> None:
    """Warn when a project config can run code or disable approvals.

    A cloned repository may commit its own .simhacli/config.toml; hooks and MCP
    servers execute commands at startup, and permissive approval policies skip
    confirmation. This only warns - it does not block.
    """
    risky: list[str] = []

    if project_config.get("hooks"):
        risky.append("defines hooks (commands run automatically)")

    mcp_servers = project_config.get("mcp_servers")
    if isinstance(mcp_servers, dict) and mcp_servers:
        template_servers = _template_mcp_servers()
        custom = sorted(
            name
            for name, server in mcp_servers.items()
            if template_servers.get(name) != server
        )
        if custom:
            risky.append(
                "defines MCP servers (commands run at startup): " + ", ".join(custom)
            )

    approval = project_config.get("approval")
    if isinstance(approval, str) and approval.lower() in ("yolo", "auto_approve"):
        risky.append(f'sets approval = "{approval}" (tool calls run without asking)')

    if risky:
        logger.warning(
            f"Project config {project_path} "
            + "; ".join(risky)
            + ". Review this file if you did not create it."
        )


def load_config(cwd: Path | None = None, prompt_api: bool = True) -> Config:
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
            # Filter out global-only keys that should NOT be overridden by project config
            GLOBAL_ONLY_KEYS = {"api_key", "api_base_url", "telegram"}
            filtered_project_config = {
                k: v
                for k, v in project_config_dict.items()
                if k not in GLOBAL_ONLY_KEYS
            }
            _warn_about_risky_project_config(project_path, filtered_project_config)
            global_mcp_servers = config_dict.get("mcp_servers")
            config_dict = _merge_dicts(config_dict, filtered_project_config)
            # A project MCP server entry replaces a global entry of the same name
            # wholesale (deep-merging could leave both `command` and `url` set)
            project_mcp_servers = filtered_project_config.get("mcp_servers")
            if isinstance(project_mcp_servers, dict) and isinstance(
                global_mcp_servers, dict
            ):
                config_dict["mcp_servers"] = {
                    **global_mcp_servers,
                    **project_mcp_servers,
                }
        except ConfigError as e:
            logger.warning(f"Skipping invalid project config: {project_path}: {e}")

    if "cwd" not in config_dict:
        config_dict["cwd"] = cwd

    if "developer_instructions" not in config_dict:
        agent_md_content = _get_agent_md_file(cwd)
        if agent_md_content:
            config_dict["developer_instructions"] = agent_md_content

    # Values already provided by the config file or environment variables
    configured_api_key = config_dict.get("api_key")
    configured_api_base_url = config_dict.get("api_base_url")
    env_api_key = os.environ.get("API_KEY")
    env_api_base_url = os.environ.get("API_BASE_URL")

    # Check for API credentials and prompt if missing (only if prompt_api=True)
    api_key, api_base_url = _prompt_for_api_credentials(
        config_dict, system_path, prompt=prompt_api
    )

    # Update in-memory config with credentials (including env-provided ones)
    if api_key:
        config_dict["api_key"] = api_key
    if api_base_url:
        config_dict["api_base_url"] = api_base_url

    # Only persist values the user typed at the prompt: never write None, never
    # copy credentials from environment variables to disk.
    save_api_key = bool(api_key) and api_key not in (configured_api_key, env_api_key)
    save_api_base_url = bool(api_base_url) and api_base_url not in (
        configured_api_base_url,
        env_api_base_url,
    )

    if save_api_key or save_api_base_url:
        # Load existing system config to check for a configured model
        existing_config: dict[str, Any] = {}
        if system_path.is_file():
            try:
                existing_config = _parse_toml(system_path)
            except ConfigError:
                pass

        # Save credentials to system config file (preserve comments by updating individual keys)
        try:
            if save_api_key:
                set_config_value("", "api_key", api_key)
            if save_api_base_url:
                set_config_value("", "api_base_url", api_base_url)

            # If user chose OpenRouter on first setup and no model is configured, default to openrouter/free
            existing_model = existing_config.get("model")
            if (
                save_api_base_url
                and api_base_url == DEFAULT_API_BASE_URL
                and not (isinstance(existing_model, dict) and existing_model.get("name"))
            ):
                set_config_value("model", "name", "openrouter/free")
                if not config_dict.get("model", {}).get("name"):
                    config_dict.setdefault("model", {})["name"] = "openrouter/free"
        except (OSError, ConfigError) as e:
            logger.warning(f"Could not save API credentials to {system_path}: {e}")

    try:
        config = Config(**config_dict)
    except Exception as e:
        raise ConfigError(
            f"Failed to validate configuration: {e}",
            config_file=str(system_path),
            cause=e,
        )
    return config
