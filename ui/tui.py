import time
from pathlib import Path
from typing import Any
from rich.console import Console
from rich.theme import Theme
from rich.rule import Rule
from rich.text import Text
from rich.panel import Panel
from rich.table import Table
from rich import box
from rich.prompt import Prompt
from rich.console import Group
from rich.syntax import Syntax
from rich.markdown import Markdown
from rich.status import Status
from rich.live import Live

from prompt_toolkit import PromptSession
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.keys import Keys
from prompt_toolkit.styles import Style as PTStyle
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.shortcuts import CompleteStyle

from config.config import Config
from tools.base import ToolConfirmation
from utils.paths import display_path_rel_to_cwd
import re
from pathlib import Path

from utils.text import truncate_text


class _TimerRenderable:
    """A renderable that shows a spinner + elapsed time on every refresh."""

    _BRAILLE = ["⠙", "⠸", "⠴", "⠦", "⠇", "⠏", "⠒", "⠱"]

    def __init__(self, label: str, start_time: float) -> None:
        self._label = label
        self._start = start_time
        self._frame = 0

    def __rich_console__(self, console, options):
        elapsed = time.monotonic() - self._start
        if elapsed < 60:
            ts = f"{elapsed:.1f}s"
        else:
            m, s = divmod(int(elapsed), 60)
            ts = f"{m}m {s}s"
        spinner = self._BRAILLE[self._frame % len(self._BRAILLE)]
        self._frame += 1
        yield Text.assemble(
            (f"{spinner} ", "gold1"),
            (f"🦁 {self._label} ", "gold1 bold"),
            (f"({ts})", "dim"),
        )


SIMHA_THEME = Theme(
    {
        # Core system
        "info": "bright_cyan",
        "warning": "yellow bold",
        "error": "bright_red bold",
        "success": "bright_green bold",
        "dim": "dim",
        "muted": "grey54",
        "border": "gold3",
        "highlight": "gold1 bold",
        # Identity
        "brand": "gold1 bold",
        "simha": "bright_yellow bold",
        # Roles
        "user": "gold1 bold",
        "assistant": "white bold",
        "system": "gold3",
        # Tools
        "tool": "gold1 bold",
        "tool.read": "cyan",
        "tool.write": "yellow",
        "tool.shell": "magenta",
        "tool.network": "bright_blue",
        "tool.memory": "bright_green",
        "tool.mcp": "bright_cyan",
        # Security & AI detection
        "security": "bright_red bold",
        "fraud": "red bold",
        "trust": "green bold",
        "risk.low": "green",
        "risk.medium": "yellow",
        "risk.high": "bright_red bold",
        # CLI / Output
        "prompt": "gold1 bold",
        "input": "bright_white",
        "output": "white",
        "response": "bright_white",
        "code": "grey93",
        "path": "cyan",
        "url": "bright_blue underline",
        # Panels & Boxes
        "panel.title": "gold1 bold",
        "panel.border": "gold3",
        "panel.text": "white",
    }
)


_console: Console | None = None


def get_console() -> Console:
    global _console
    if _console is None:
        _console = Console(theme=SIMHA_THEME, highlight=False)
    return _console


# TUI class to handle terminal user interface

_SLASH_COMMANDS: list[tuple[str, str]] = [
    ("/help", "show available commands"),
    ("/model", "change the active model"),
    ("/config", "show current configuration"),
    ("/clear", "clear conversation history"),
    ("/stats", "show session statistics"),
    ("/tools", "list available tools"),
    ("/mcp", "show MCP server status"),
    ("/approval", "change tool approval policy"),
    ("/save", "save current session"),
    ("/sessions", "list saved sessions"),
    ("/resume", "restore a saved session"),
    ("/checkpoint", "create a named checkpoint"),
    ("/restore", "restore a checkpoint"),
    ("/credentials", "manage API key / base URL"),
    ("/creds", "manage API key / base URL"),
    ("/undo", "selectively undo file changes"),
    ("/run", "run terminal command"),
    ("/!", "run terminal command (shortcut)"),
    ("/init", "analyze project & generate instruction files"),
    ("/permissions", "show current tool permissions"),
    ("/workflow", "run end-to-end development workflow"),
    ("/exit", "exit the session"),
    ("/quit", "exit the session"),
]


class _CommandCompleter(Completer):
    """Completer that activates only when the input starts with '/'."""

    def __init__(self, get_tools=None, get_tool_status=None):
        self._get_tools = get_tools
        self._get_tool_status = get_tool_status  # Returns dict of tool_name -> status

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor
        if not text.startswith("/"):
            return

        # Handle /permissions subcommands
        if text.startswith("/permissions"):
            parts = text.split()

            if len(parts) == 1:
                # "/permissions" or "/permissions "
                if text.endswith(" "):
                    # Suggest subcommands
                    subcommands = ["allow", "deny", "reset"]
                    for sub in subcommands:
                        yield Completion(
                            sub, start_position=0, display_meta="subcommand"
                        )
                    return
                # Else fall through to command completion logic below

            elif len(parts) == 2:
                # "/permissions allow" or "/permissions allow "
                subcommand = parts[1]

                if text.endswith(" "):
                    # Suggest tools if allow/deny
                    if subcommand in ["allow", "deny"]:
                        if self._get_tools:
                            tools = self._get_tools()
                            if self._get_tool_status:
                                status = self._get_tool_status()
                                for tool_name in tools:
                                    meta = status.get(tool_name, "tool")
                                    yield Completion(
                                        tool_name, start_position=0, display_meta=meta
                                    )
                            else:
                                for tool_name in tools:
                                    yield Completion(
                                        tool_name, start_position=0, display_meta="tool"
                                    )
                    return

                # Suggest matching subcommands
                subcommands = ["allow", "deny", "reset"]
                for sub in subcommands:
                    if sub.startswith(subcommand):
                        yield Completion(
                            sub,
                            start_position=-len(subcommand),
                            display_meta="subcommand",
                        )
                return

            elif len(parts) == 3:
                # "/permissions allow read_file"
                subcommand = parts[1]
                tool_prefix = parts[2]

                if subcommand in ["allow", "deny"]:
                    if self._get_tools:
                        tools = self._get_tools()
                        status = (
                            self._get_tool_status() if self._get_tool_status else {}
                        )
                        for tool_name in tools:
                            if tool_name.startswith(tool_prefix):
                                meta = status.get(tool_name, "tool")
                                yield Completion(
                                    tool_name,
                                    start_position=-len(tool_prefix),
                                    display_meta=meta,
                                )
                return

        # Default command completion
        for cmd, description in _SLASH_COMMANDS:
            if cmd.startswith(text):
                yield Completion(
                    cmd,
                    start_position=-len(text),
                    display=cmd,
                    display_meta=description,
                )


class _FilePathCompleter(Completer):
    """Completer for @filename references with recursive search."""

    # Directories to skip during recursive search
    SKIP_DIRS = {
        ".git",
        ".svn",
        ".hg",
        "__pycache__",
        ".pytest_cache",
        "node_modules",
        ".venv",
        "venv",
        ".env",
        "env",
        ".idea",
        ".vscode",
        ".tox",
        ".mypy_cache",
        ".ruff_cache",
        "dist",
        "build",
        "*.egg-info",
        ".simhacli",
    }

    def __init__(self, cwd: Path):
        self.cwd = cwd
        self._file_cache: list[tuple[str, Path]] | None = None
        self._cache_time: float = 0

    def _should_skip_dir(self, dir_name: str) -> bool:
        """Check if directory should be skipped."""
        if dir_name.startswith("."):
            return True
        for pattern in self.SKIP_DIRS:
            if pattern.startswith("*"):
                if dir_name.endswith(pattern[1:]):
                    return True
            elif dir_name == pattern:
                return True
        return False

    def _build_file_cache(self) -> list[tuple[str, Path]]:
        """Build cache of all files with relative paths."""
        import time

        current_time = time.time()

        # Cache for 5 seconds
        if self._file_cache and (current_time - self._cache_time) < 5:
            return self._file_cache

        files: list[tuple[str, Path]] = []

        def scan_directory(dir_path: Path, prefix: str = ""):
            try:
                for entry in sorted(dir_path.iterdir()):
                    if entry.name.startswith("."):
                        continue

                    rel_path = f"{prefix}{entry.name}" if prefix else entry.name

                    if entry.is_dir():
                        if not self._should_skip_dir(entry.name):
                            # Add directory entry
                            files.append((rel_path + "/", entry))
                            # Recurse into subdirectory
                            scan_directory(entry, rel_path + "/")
                    else:
                        files.append((rel_path, entry))
            except (PermissionError, OSError):
                pass

        scan_directory(self.cwd)

        self._file_cache = files
        self._cache_time = current_time
        return files

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor

        # Find the last @ in the text
        at_pos = text.rfind("@")
        if at_pos == -1:
            return

        # Get the partial path after @
        partial = text[at_pos + 1 :]

        # Handle quoted paths
        is_quoted = partial.startswith('"')
        if is_quoted:
            partial = partial[1:]

        partial_lower = partial.lower()

        # Build file cache
        all_files = self._build_file_cache()

        # Calculate start position (replace from @ onwards)
        start_pos = -(len(text) - at_pos)

        # If user typed a path ending with /, show contents of that directory
        if partial and (partial.endswith("/") or partial.endswith("\\")):
            dir_prefix = partial
            for rel_path, entry in all_files:
                if rel_path.startswith(dir_prefix) and rel_path != dir_prefix:
                    # Show only immediate children
                    remainder = rel_path[len(dir_prefix) :]
                    if "/" not in remainder or (
                        remainder.endswith("/") and remainder.count("/") == 1
                    ):
                        if entry.is_dir():
                            display_name = remainder
                            completion_text = f"@{rel_path}"
                            meta = "directory"
                        else:
                            display_name = remainder
                            completion_text = f"@{rel_path}"
                            try:
                                size = entry.stat().st_size
                                if size < 1024:
                                    meta = f"{size} bytes"
                                elif size < 1024 * 1024:
                                    meta = f"{size / 1024:.1f} KB"
                                else:
                                    meta = f"{size / (1024 * 1024):.1f} MB"
                            except OSError:
                                meta = "file"

                        yield Completion(
                            completion_text,
                            start_position=start_pos,
                            display=display_name,
                            display_meta=meta,
                        )
            return

        # Match files by:
        # 1. Filename starts with partial
        # 2. Any path segment starts with partial
        # 3. Filename contains partial

        matches: list[tuple[int, str, Path]] = []  # (score, rel_path, entry)

        for rel_path, entry in all_files:
            # Skip directories in normal search (only show if partial matches dir name)
            is_dir = entry.is_dir()
            path_lower = rel_path.lower()
            name_lower = entry.name.lower()

            score = 0

            # Exact filename match
            if name_lower == partial_lower:
                score = 100
            # Filename starts with partial
            elif name_lower.startswith(partial_lower):
                score = 80
            # Path contains the partial as a complete segment
            elif f"/{partial_lower}" in f"/{path_lower}":
                score = 60
            # Filename contains partial
            elif partial_lower in name_lower:
                score = 40
            # Path contains partial anywhere
            elif partial_lower in path_lower:
                score = 20
            else:
                continue

            # Bonus for shorter paths (prefer root-level files)
            depth = rel_path.count("/")
            score += max(0, 10 - depth)  # Up to +10 for root files

            matches.append((score, rel_path, entry))

        # Sort by score (highest first), then alphabetically
        matches.sort(key=lambda x: (-x[0], x[1]))

        # Limit results to avoid overwhelming the user
        for score, rel_path, entry in matches[:20]:
            if entry.is_dir():
                display_name = rel_path
                completion_text = f"@{rel_path}"
                meta = "directory"
            else:
                display_name = rel_path
                completion_text = f"@{rel_path}"
                try:
                    size = entry.stat().st_size
                    if size < 1024:
                        meta = f"{size} bytes"
                    elif size < 1024 * 1024:
                        meta = f"{size / 1024:.1f} KB"
                    else:
                        meta = f"{size / (1024 * 1024):.1f} MB"
                except OSError:
                    meta = "file"

            yield Completion(
                completion_text,
                start_position=start_pos,
                display=display_name,
                display_meta=meta,
            )


class _CombinedCompleter(Completer):
    """Combines slash command and file path completers."""

    def __init__(self, cwd: Path, get_tools=None, get_tool_status=None):
        self._command_completer = _CommandCompleter(get_tools, get_tool_status)
        self._file_completer = _FilePathCompleter(cwd)

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor

        # Check if we're completing a slash command
        if text.startswith("/"):
            yield from self._command_completer.get_completions(document, complete_event)

        # Check if we're completing a @filename
        if "@" in text:
            yield from self._file_completer.get_completions(document, complete_event)


class TUI:
    def __init__(
        self,
        config: Config,
        console: Console | None = None,
    ) -> None:
        self.console = console or get_console()
        self.__assistant_stream_open = False
        self._tool_args_by_call_id: dict[str, dict[str, Any]] = {}
        self.config = config
        self.cwd: Path = config.cwd
        self._max_block_tokens = 3200
        self._buffered_content = ""
        self._status: Status | None = None
        self._live: Live | None = None
        self._last_render_len = 0
        self._get_tools = None  # Function to get tool names for completion
        self._get_tool_status = None  # Function to get tool status (allowed/denied)

        # Thinking display state
        self._thinking_live: Live | None = None
        self._thinking_content = ""
        self._thinking_started = False
        self._thinking_start_time: float = 0.0

        # Request timer
        self._request_start_time: float = 0.0

        # Working indicator (Live with timer)
        self._working_live: Live | None = None

        # Setup multi-line input with prompt_toolkit
        self._prompt_session = self._create_prompt_session()

    def set_tool_getter(self, get_tools, get_tool_status=None):
        """Set the function that returns tool names for completion."""
        self._get_tools = get_tools
        self._get_tool_status = get_tool_status
        # Recreate prompt session with updated completer
        self._prompt_session = self._create_prompt_session()

    def _create_prompt_session(self) -> PromptSession:
        """Create a prompt session with custom key bindings for multi-line input."""
        # Key bindings:
        # - Enter: submit if buffer has text, else do nothing
        # - Escape then Enter: insert newline (for multi-line input)
        bindings = KeyBindings()

        @bindings.add(Keys.Enter)
        def _(event):
            """Enter: submit message if text is present."""
            buffer = event.app.current_buffer
            text = buffer.text

            if text.strip():
                buffer.validate_and_handle()
            # If buffer is empty, do nothing - user must type something or use /exit

        @bindings.add(Keys.Escape, Keys.Enter)  # Escape then Enter
        def _(event):
            """Esc+Enter: Insert newline for multi-line messages."""
            event.app.current_buffer.insert_text("\n")

        # Custom style for the prompt
        style = PTStyle.from_dict(
            {
                "prompt": "#FFD700 bold",  # Gold color for prompt
                "input": "#FFFFFF",  # White for input text
                # Completion dropdown
                "completion-menu.completion": "bg:#1e1e2e #cccccc",
                "completion-menu.completion.current": "bg:#4a4aaa bold #ffffff",
                "completion-menu.meta.completion": "bg:#1e1e2e #666666",
                "completion-menu.meta.completion.current": "bg:#4a4aaa #aaaaaa",
            }
        )

        return PromptSession(
            key_bindings=bindings,
            style=style,
            multiline=True,
            prompt_continuation=lambda width, line_number, is_soft_wrap: "... ",
            completer=_CombinedCompleter(
                self.cwd, self._get_tools, self._get_tool_status
            ),
            complete_style=CompleteStyle.MULTI_COLUMN,
            complete_while_typing=True,
        )

    async def get_multiline_input(self, prompt_text: str = "> ") -> str | None:
        """
        Get multi-line input from user.

        - Enter: Submit (single line) or add newline (multi-line mode)
        - Enter on empty line: Submit the message
        - Escape+Enter: Force submit

        - Arrow keys: Navigate within text
        - Standard text editing (Home, End, Delete, Backspace, etc.)

        Returns:
            The user input string, or None if cancelled (Ctrl+C/Ctrl+D)
        """
        try:
            self.console.print()  # Add spacing before prompt
            result = await self._prompt_session.prompt_async(
                HTML(f"<prompt>{prompt_text}</prompt>"),
            )
            return result.strip() if result else None
        except KeyboardInterrupt:
            return None
        except EOFError:
            return None

    def print_input_hint(self) -> None:
        """Print hint text showing available input shortcuts."""
        self.console.print(
            Text.assemble(
                ("  [", "dim"),
                ("@", "cyan bold"),
                (" attach file", "dim"),
                (" | ", "dim"),
                ("/", "cyan bold"),
                (" commands", "dim"),
                (" | ", "dim"),
                ("/undo", "cyan bold"),
                (" revert", "dim"),
                (" | ", "dim"),
                ("q", "cyan bold"),
                (" stop", "dim"),
                (" | ", "dim"),
                ("Esc+Enter", "cyan bold"),
                (" newline", "dim"),
                ("]", "dim"),
            )
        )

    def print_context_usage(self, current_tokens: int, max_tokens: int) -> None:
        """Print context window usage below input hint."""
        if max_tokens <= 0:
            return

        percentage = (current_tokens / max_tokens) * 100

        # Color based on usage
        if percentage < 50:
            color = "green"
        elif percentage < 75:
            color = "yellow"
        else:
            color = "red"

        # Format numbers with commas
        current_fmt = f"{current_tokens:,}"
        max_fmt = f"{max_tokens:,}"

        self.console.print(
            Text.assemble(
                ("  Context: ", "dim"),
                (current_fmt, color),
                (" / ", "dim"),
                (max_fmt, "dim"),
                (" tokens ", "dim"),
                (f"({percentage:.1f}%)", color),
            )
        )

    def print_welcome(self, title: str, lines: list[str]) -> None:
        body = "\n".join(lines)
        BANNER = """
        ╔═══════════════════════════════════════════════════════════════╗
        ║                                                               ║
        ║   ██████╗ ██╗███╗   ███╗██╗  ██╗ █████╗  ██████╗██╗     ██╗   ║
        ║  ██╔════╝ ██║████╗ ████║██║  ██║██╔══██╗██╔════╝██║     ██║   ║
        ║  ╚█████╗  ██║██╔████╔██║███████║███████║██║     ██║     ██║   ║
        ║   ╚═══██╗ ██║██║╚██╔╝██║██╔══██║██╔══██║██║     ██║     ██║   ║
        ║  ██████╔╝ ██║██║ ╚═╝ ██║██║  ██║██║  ██║╚██████╗███████╗██║   ║
        ║  ╚═════╝  ╚═╝╚═╝     ╚═╝╚═╝  ╚═╝╚═╝  ╚═╝ ╚═════╝╚══════╝╚═╝   ║
        ║                                                               ║
        ║               SIMHACLI AI Coding Agent!.                      ║
        ║                                                               ║
        ╚═══════════════════════════════════════════════════════════════╝
    """

        self.console.print(Text(BANNER, style="bold yellow"))

        self.console.print(
            Panel(
                Text(body, style="cyan"),
                title=Text(f"> {title}", style="highlight"),
                title_align="left",
                border_style="bright_blue",
                box=box.ROUNDED,
                padding=(1, 2),
            )
        )

    def begin_assistant(self) -> None:
        # self.console.print()
        self.__assistant_stream_open = True
        self._buffered_content = ""
        self._last_render_len = 0
        # Start live display for streaming Markdown
        self._live = Live(
            Text("▌", style="bright_yellow"),
            console=self.console,
            refresh_per_second=4,
        )
        self._live.start()

    def end_assistant(self) -> None:
        if self.__assistant_stream_open:
            if self._live:
                # Final render with complete Markdown
                if self._buffered_content.strip():
                    self._live.update(Markdown(self._buffered_content))
                self._live.stop()
                self._live = None
            # self.console.print()
            self.__assistant_stream_open = False
            self._buffered_content = ""

    def stream_assistant_delta(self, content: str) -> None:
        self._buffered_content += content
        if self._live:
            # Re-render every 15 chars for responsive streaming feel
            if len(self._buffered_content) - self._last_render_len > 15:
                self._last_render_len = len(self._buffered_content)
                self._live.update(Markdown(self._buffered_content + " ▌"))

    # ── Thinking display (grey/dim text like Copilot) ─────────────

    @staticmethod
    def _fmt_elapsed(seconds: float) -> str:
        """Format elapsed seconds as a human-readable string."""
        if seconds < 60:
            return f"{seconds:.1f}s"
        mins = int(seconds) // 60
        secs = seconds - mins * 60
        return f"{mins}m {secs:.1f}s"

    def begin_thinking(self) -> None:
        """Start thinking display — dim text with a running timer."""
        self.stop_loading()  # stop spinner if running
        self._thinking_content = ""
        self._thinking_started = True
        self._thinking_start_time = time.monotonic()
        self._thinking_live = Live(
            Text("💭 SimhaCLI thinking… 0.0s", style="dim italic"),
            console=self.console,
            refresh_per_second=4,
        )
        self._thinking_live.start()

    def stream_thinking_delta(self, content: str) -> None:
        """Append a reasoning token and refresh the dim display with timer."""
        if not self._thinking_started:
            self.begin_thinking()
        self._thinking_content += content
        if self._thinking_live:
            elapsed = self._fmt_elapsed(time.monotonic() - self._thinking_start_time)
            # Truncate display to last 800 chars to keep it compact
            display = self._thinking_content
            if len(display) > 800:
                display = "…" + display[-800:]
            self._thinking_live.update(
                Text.assemble(
                    ("💭 ", "dim"),
                    (f"SimhaCLI thinking ({elapsed}) ", "dim italic"),
                    (display, "grey54 italic"),
                    (" ▌", "dim"),
                )
            )

    def end_thinking(self) -> None:
        """Close the thinking Live display."""
        elapsed = (
            self._fmt_elapsed(time.monotonic() - self._thinking_start_time)
            if self._thinking_started
            else ""
        )
        # Stop the Live display (clears the animated line)
        if self._thinking_live:
            # Update final frame with elapsed time before stopping
            if elapsed and self._thinking_content.strip():
                display = self._thinking_content.strip().replace("\n", " ")
                if len(display) > 500:
                    display = display[:500] + "…"
                self._thinking_live.update(
                    Text.assemble(
                        ("💭 ", "dim"),
                        (f"thought for {elapsed}  ", "grey54 italic bold"),
                        (display, "grey54 italic"),
                    )
                )
            elif elapsed:
                self._thinking_live.update(
                    Text(f"💭 thought for {elapsed}", style="grey54 italic")
                )
            self._thinking_live.stop()
            self._thinking_live = None

        self._thinking_content = ""
        self._thinking_started = False
        self._thinking_start_time = 0.0

    def display_error(self, error_message: str) -> None:
        # Stop loading indicator if it's running
        self.stop_loading()
        self.console.print(f"[error]Error: {error_message}[/error]")

    def display_file_attachments(self, attachments: list) -> None:
        """Display visual feedback for attached files."""
        if not attachments:
            return

        from rich.table import Table

        table = Table(
            show_header=True,
            header_style="bold cyan",
            border_style="dim",
            box=box.SIMPLE,
            padding=(0, 1),
        )
        table.add_column("File", style="path")
        table.add_column("Lines", justify="right", style="dim")
        table.add_column("Size", justify="right", style="dim")

        for att in attachments:
            lines = att.content.count("\n") + 1
            size = len(att.content.encode("utf-8"))

            if size < 1024:
                size_str = f"{size} B"
            elif size < 1024 * 1024:
                size_str = f"{size / 1024:.1f} KB"
            else:
                size_str = f"{size / (1024 * 1024):.1f} MB"

            table.add_row(att.relative_path, str(lines), size_str)

        self.console.print(table)

    def start_request_timer(self) -> None:
        """Start the overall request timer."""
        self._request_start_time = time.monotonic()

    def start_working(self) -> None:
        """Start (or restart) the working spinner with a running timer."""
        # Don't start if already running
        if self._working_live:
            return
        self._working_live = Live(
            _TimerRenderable("Simha is working...", time.monotonic()),
            console=self.console,
            refresh_per_second=2,
        )
        self._working_live.start()

    def agent_start(self, message: str) -> None:
        self.console.print()
        self.console.print(
            Text.assemble(
                ("SimhaCLI", "gold1 bold"),
                ("🦁  ", "gold1"),
                ("  starting  ", "dim"),
                (message, "cyan"),
            )
        )
        # Start loading indicator with running timer
        self.start_working()

    def stop_loading(self) -> None:
        """Stop the loading indicator if it's running"""
        if self._working_live:
            self._working_live.stop()
            self._working_live = None
        if self._status:
            self._status.stop()
            self._status = None

    def agent_end(self, usage: dict[str, Any] | None = None) -> None:
        # Stop loading indicators
        if self._working_live:
            self._working_live.stop()
            self._working_live = None
        if self._status:
            self._status.stop()
            self._status = None

        # Calculate total elapsed time
        elapsed_str = ""
        if self._request_start_time:
            elapsed = time.monotonic() - self._request_start_time
            elapsed_str = f" in {self._fmt_elapsed(elapsed)}"
            self._request_start_time = 0.0

        if usage:
            text = Text.assemble(
                ("SimhaCLI", "bold green"),
                ("🦁  ", "green"),
                (f"  complete{elapsed_str}  ", "dim"),
                (
                    f"{usage.get('total_tokens', 0)} tokens "
                    f"({usage.get('prompt_tokens', 0)} prompt + "
                    f"{usage.get('completion_tokens', 0)} completion)",
                    "muted",
                ),
            )
        else:
            text = Text.assemble(
                ("SimhaCLI", "bold green"),
                ("🦁  ", "green"),
                (f"  complete{elapsed_str}", "dim"),
            )

        self.console.print(text)

    def _ordered_args(self, tool_name: str, args: dict[str, Any]) -> list[tuple]:
        _PREFERRED_ORDER = {
            "read_file": ["path", "offset", "limit"],
            "write_file": ["path", "create_directories", "content"],
            "edit": ["path", "replace_all", "old_string", "new_string"],
            "shell": ["command", "timeout", "cwd"],
            "list_dir": ["path", "include_hidden"],
            "grep": ["path", "case_insensitive", "pattern"],
            "glob": ["path", "pattern"],
            "todos": ["action", "id", "content", "priority"],
            "memory": ["action", "key", "value"],
        }

        preferred = _PREFERRED_ORDER.get(tool_name, [])
        ordered: list[tuple[str, Any]] = []
        seen = set()

        for key in preferred:
            if key in args:
                ordered.append((key, args[key]))
                seen.add(key)

        remaining_keys = set(args.keys() - seen)
        ordered.extend((key, args[key]) for key in remaining_keys)

        return ordered

    def _render_args_table(self, tool_name: str, args: dict[str, Any]) -> Table:
        table = Table.grid(padding=(0, 1))
        table.add_column(style="muted", justify="right", no_wrap=True)
        table.add_column(style="code", overflow="fold")

        for key, value in self._ordered_args(tool_name, args):
            if isinstance(value, str):
                if key in {"content", "old_string", "new_string"}:
                    line_count = len(value.splitlines()) or 0
                    byte_count = len(value.encode("utf-8", errors="replace"))
                    value = f"<{line_count} lines • {byte_count} bytes>"
            else:
                # Convert non-string values to string
                value = str(value)

            table.add_row(key, value)

        return table

    def _guess_language(self, path: str | None) -> str:
        if not path:
            return "text"
        suffix = Path(path).suffix.lower()
        return {
            ".py": "python",
            ".js": "javascript",
            ".jsx": "jsx",
            ".ts": "typescript",
            ".tsx": "tsx",
            ".json": "json",
            ".toml": "toml",
            ".yaml": "yaml",
            ".yml": "yaml",
            ".md": "markdown",
            ".sh": "bash",
            ".bash": "bash",
            ".zsh": "bash",
            ".rs": "rust",
            ".go": "go",
            ".java": "java",
            ".kt": "kotlin",
            ".swift": "swift",
            ".c": "c",
            ".h": "c",
            ".cpp": "cpp",
            ".hpp": "cpp",
            ".css": "css",
            ".html": "html",
            ".xml": "xml",
            ".sql": "sql",
        }.get(suffix, "text")

    def tool_call_start(
        self,
        call_id: str,
        name: str,
        tool_kind: str | None,
        arguments: dict[str, Any],
    ) -> None:
        self._tool_args_by_call_id[call_id] = arguments
        border_style = f"tool.{tool_kind}" if tool_kind else "tool"

        title = Text.assemble(
            ("▶ ", "gold1"),
            (name, "tool"),
            ("  ", "muted"),
            (f"#{call_id[:8]}", "muted"),
        )

        display_args = dict(arguments)
        for key in ("path", "cwd"):
            val = display_args.get(key)
            if isinstance(val, str) and self.cwd:
                display_args[key] = str(display_path_rel_to_cwd(val, self.cwd))

        panel = Panel(
            (
                self._render_args_table(name, display_args)
                if display_args
                else Text(
                    "(no args)",
                    style="muted",
                )
            ),
            title=title,
            title_align="left",
            subtitle=Text("running", style="muted"),
            subtitle_align="right",
            border_style=border_style,
            box=box.ROUNDED,
            padding=(1, 2),
        )
        self.console.print()
        self.console.print(panel)

    def _extract_read_file_code(self, text: str) -> tuple[int, str] | None:
        body = text
        header_match = re.match(r"^Showing lines (\d+)-(\d+) of (\d+)\n\n", text)

        if header_match:
            body = text[header_match.end() :]

        code_lines: list[str] = []
        start_line: int | None = None

        for line in body.splitlines():
            # 1|def main():
            # 2| print()
            m = re.match(r"^\s*(\d+)\|(.*)$", line)
            if not m:
                return None
            line_no = int(m.group(1))
            if start_line is None:
                start_line = line_no
            code_lines.append(m.group(2))

        if start_line is None:
            return None

        return start_line, "\n".join(code_lines)

    def tool_call_complete(
        self,
        call_id: str,
        name: str,
        tool_kind: str | None,
        success: bool,
        output: str,
        error: str | None,
        metadata: dict[str, Any] | None,
        diff: str | None,
        truncated: bool,
        exit_code: int | None,
    ) -> None:
        border_style = f"tool.{tool_kind}" if tool_kind else "tool"
        status_icon = "✓" if success else "✗"
        status_style = "success" if success else "error"

        title = Text.assemble(
            (f"{status_icon} ", status_style),
            (name, "tool"),
            ("  ", "muted"),
            (f"#{call_id[:8]}", "muted"),
        )

        args = self._tool_args_by_call_id.get(call_id, {})

        primary_path = None
        blocks = []
        if isinstance(metadata, dict) and isinstance(metadata.get("path"), str):
            primary_path = metadata.get("path")

        if name == "read_file" and success:
            if primary_path:
                start_line, code = self._extract_read_file_code(output)

                shown_start = metadata.get("shown_start")
                shown_end = metadata.get("shown_end")
                total_lines = metadata.get("total_lines")
                pl = self._guess_language(primary_path)

                header_parts = [display_path_rel_to_cwd(primary_path, self.cwd)]
                header_parts.append(" • ")

                if shown_start and shown_end and total_lines:
                    header_parts.append(
                        f"lines {shown_start}-{shown_end} of {total_lines}"
                    )

                header = "".join(header_parts)
                blocks.append(Text(header, style="muted"))
                blocks.append(
                    Syntax(
                        code,
                        pl,
                        theme="monokai",
                        line_numbers=True,
                        start_line=start_line,
                        word_wrap=False,
                    )
                )
            else:
                output_display = truncate_text(
                    output,
                    "",
                    self._max_block_tokens,
                )
                blocks.append(
                    Syntax(
                        output_display,
                        "text",
                        theme="monokai",
                        word_wrap=False,
                    )
                )
        elif name in {"write_file", "edit_file"} and success and diff:
            output_line = output.strip() if output.strip() else "Completed"
            blocks.append(Text(output_line, style="muted"))
            diff_text = diff
            diff_display = truncate_text(
                diff_text,
                self.config.model_name,
                self._max_block_tokens,
            )
            blocks.append(
                Syntax(
                    diff_display,
                    "diff",  # syntax highlighting for diffs
                    theme="monokai",
                    word_wrap=True,
                )
            )
        elif name == "shell" and success:
            command = args.get("command")
            if isinstance(command, str) and command.strip():
                blocks.append(Text(f"$ {command.strip()}", style="muted"))

            if exit_code is not None:
                blocks.append(Text(f"exit_code={exit_code}", style="muted"))

            output_display = truncate_text(
                output,
                self.config.model_name,
                self._max_block_tokens,
            )
            blocks.append(
                Syntax(
                    output_display,
                    "text",
                    theme="monokai",
                    word_wrap=True,
                )
            )
        elif name == "list_dir" and success:
            entries = metadata.get("entries")
            path = metadata.get("path")
            summary = []
            if isinstance(path, str):
                summary.append(path)

            if isinstance(entries, int):
                summary.append(f"{entries} entries")

            if summary:
                blocks.append(Text(" • ".join(summary), style="muted"))

            output_display = truncate_text(
                output,
                self.config.model_name,
                self._max_block_tokens,
            )
            blocks.append(
                Syntax(
                    output_display,
                    "text",
                    theme="monokai",
                    word_wrap=True,
                )
            )
        elif name == "grep" and success:
            matches = metadata.get("matches")
            files_searched = metadata.get("files_searched")
            summary = []
            if isinstance(matches, int):
                summary.append(f"{matches} matches")
            if isinstance(files_searched, int):
                summary.append(f"searched {files_searched} files")

            if summary:
                blocks.append(Text(" • ".join(summary), style="muted"))

            output_display = truncate_text(
                output, self.config.model_name, self._max_block_tokens
            )
            blocks.append(
                Syntax(
                    output_display,
                    "text",
                    theme="monokai",
                    word_wrap=True,
                )
            )
        elif name == "glob" and success:
            matches = metadata.get("matches")
            if isinstance(matches, int):
                blocks.append(Text(f"{matches} matches", style="muted"))

            output_display = truncate_text(
                output,
                self.config.model_name,
                self._max_block_tokens,
            )
            blocks.append(
                Syntax(
                    output_display,
                    "text",
                    theme="monokai",
                    word_wrap=True,
                )
            )
        elif name == "web_search" and success:
            results = metadata.get("results")
            query = args.get("query")
            summary = []
            if isinstance(query, str):
                summary.append(query)
            if isinstance(results, int):
                summary.append(f"{results} results")

            if summary:
                blocks.append(Text(" • ".join(summary), style="muted"))

            output_display = truncate_text(
                output,
                self.config.model_name,
                self._max_block_tokens,
            )
            blocks.append(
                Syntax(
                    output_display,
                    "text",
                    theme="monokai",
                    word_wrap=True,
                )
            )
        elif name == "web_fetch" and success:
            status_code = metadata.get("status_code")
            content_length = metadata.get("content_length")
            url = args.get("url")
            summary = []
            if isinstance(status_code, int):
                summary.append(str(status_code))
            if isinstance(content_length, int):
                summary.append(f"{content_length} bytes")
            if isinstance(url, str):
                summary.append(url)

            if summary:
                blocks.append(Text(" • ".join(summary), style="muted"))

            output_display = truncate_text(
                output,
                self.config.model_name,
                self._max_block_tokens,
            )
            blocks.append(
                Syntax(
                    output_display,
                    "text",
                    theme="monokai",
                    word_wrap=True,
                )
            )
        elif name == "todos" and success:
            action = args.get("action", "")

            # Special rendering for list action
            if action == "list" and metadata:
                total = metadata.get("total", 0)
                in_progress_count = metadata.get("in_progress", 0)
                not_started_count = metadata.get("not_started", 0)
                completed_count = metadata.get("completed", 0)
                progress = metadata.get("progress_percent", 0)

                # Create overall status header
                bar_length = 30
                filled = int((progress / 100) * bar_length)
                progress_bar = "█" * filled + "░" * (bar_length - filled)

                header = Text.assemble(
                    ("📊 Overall Progress: ", "bold cyan"),
                    (f"{completed_count}/{total} ", "bold green"),
                    (f"({progress}%) ", "bold yellow"),
                    (progress_bar, "green"),
                )
                blocks.append(header)
                blocks.append(Text(""))  # Empty line

                # Create summary stats
                stats = Text.assemble(
                    ("▶️  In Progress: ", "yellow"),
                    (f"{in_progress_count}  ", "bold yellow"),
                    ("⏸️  Not Started: ", "cyan"),
                    (f"{not_started_count}  ", "bold cyan"),
                    ("✅ Completed: ", "green"),
                    (f"{completed_count}", "bold green"),
                )
                blocks.append(stats)
                blocks.append(Text(""))  # Empty line

                # Parse and render todos from output
                # The output has sections: In Progress, Not Started, Completed
                lines = output.split("\n")
                current_section = None

                for line in lines:
                    if not line.strip():
                        continue

                    # Detect section headers
                    if "In Progress:" in line:
                        current_section = "in_progress"
                        blocks.append(Text(line, style="bold yellow"))
                    elif "Not Started:" in line:
                        current_section = "not_started"
                        blocks.append(Text(line, style="bold cyan"))
                    elif "Completed:" in line:
                        current_section = "completed"
                        blocks.append(Text(line, style="bold green"))
                    elif "Summary:" in line or "Task List:" in line:
                        # Skip these as we already have our custom header
                        continue
                    else:
                        # Render individual todo items with appropriate styling
                        if current_section == "in_progress":
                            blocks.append(Text(line, style="yellow"))
                        elif current_section == "not_started":
                            blocks.append(Text(line, style="cyan"))
                        elif current_section == "completed":
                            blocks.append(Text(line, style="dim green"))
            else:
                # For non-list actions (add, start, complete, remove, clear)
                todo_id = args.get("id")
                summary_parts = []

                if isinstance(action, str) and action:
                    action_icons = {
                        "add": "➕",
                        "start": "▶️",
                        "complete": "✅",
                        "remove": "🗑️",
                        "clear": "🧹",
                    }
                    icon = action_icons.get(action.lower(), "")
                    summary_parts.append(f"{icon} {action}")

                if isinstance(todo_id, str) and todo_id:
                    summary_parts.append(f"#{todo_id}")

                # Add progress for complete action
                if metadata and action == "complete":
                    completed = metadata.get("completed")
                    total = metadata.get("total")
                    progress = metadata.get("progress_percent")

                    if progress is not None:
                        bar_length = 20
                        filled = int((progress / 100) * bar_length)
                        bar = "█" * filled + "░" * (bar_length - filled)
                        summary_parts.append(f"{progress}% {bar}")

                if summary_parts:
                    blocks.append(Text(" • ".join(summary_parts), style="muted"))

                # Render the output
                output_display = truncate_text(
                    output,
                    self.config.model_name,
                    self._max_block_tokens,
                )
                blocks.append(Text(output_display, style="white"))
        elif name == "memory" and success:
            action = args.get("action")
            key = args.get("key")
            found = metadata.get("found")
            summary = []
            if isinstance(action, str) and action:
                summary.append(action)
            if isinstance(key, str) and key:
                summary.append(key)
            if isinstance(found, bool):
                summary.append("found" if found else "missing")

            if summary:
                blocks.append(Text(" • ".join(summary), style="muted"))
            output_display = truncate_text(
                output,
                self.config.model_name,
                self._max_block_tokens,
            )
            blocks.append(
                Syntax(
                    output_display,
                    "text",
                    theme="monokai",
                    word_wrap=True,
                )
            )
        else:
            if error and not success:
                blocks.append(Text(error, style="error"))

            output_display = truncate_text(
                output, self.config.model_name, self._max_block_tokens
            )
            if output_display.strip():
                blocks.append(
                    Syntax(
                        output_display,
                        "text",
                        theme="monokai",
                        word_wrap=True,
                    )
                )
            else:
                blocks.append(Text("(no output)", style="muted"))

        if truncated:
            blocks.append(Text("note: tool output was truncated", style="warning"))

        panel = Panel(
            Group(
                *blocks,
            ),
            title=title,
            title_align="left",
            subtitle=Text("done" if success else "failed", style=status_style),
            subtitle_align="right",
            border_style=border_style,
            box=box.ROUNDED,
            padding=(1, 2),
        )
        self.console.print()
        self.console.print(panel)

    def handle_confirmation(self, confirmation: ToolConfirmation) -> bool:
        # Stop any active status/spinner to allow user input
        was_status_active = self._status is not None
        if self._status:
            self._status.stop()
            self._status = None

        output = [
            Text(confirmation.tool_name, style="tool"),
            Text(confirmation.description, style="code"),
        ]

        if confirmation.command:
            output.append(Text(f"$ {confirmation.command}", style="warning"))

        if confirmation.diff:
            diff_text = confirmation.diff.to_diff()
            output.append(
                Syntax(
                    diff_text,
                    "diff",
                    theme="monokai",
                    word_wrap=True,
                )
            )

        self.console.print()
        self.console.print(
            Panel(
                Group(*output),
                title=Text("Approval required", style="warning"),
                title_align="left",
                border_style="warning",
                box=box.ROUNDED,
                padding=(1, 2),
            )
        )

        response = Prompt.ask(
            "\nApprove?", choices=["y", "n", "yes", "no"], default="n"
        )

        # Restart status if it was active before
        if was_status_active:
            self._status = self.console.status(
                "[gold1]🦁 Simha is working...[/gold1]", spinner="dots"
            )
            self._status.start()

        return response.lower() in {"y", "yes"}

    def show_help(self) -> None:
        help_text = """
## Commands

- `/help` - Show this help
- `/exit` or `/quit` - Exit the agent
- `q` - Stop agent & return to input (Ctrl+C also works)
- `/clear` - Clear conversation history
- `/config` - Show current configuration
- `/model <name>` - Change the model
- `/approval <mode>` - Change approval mode
- `/stats` - Show session statistics
- `/tools` - List available tools
- `/mcp` - Show MCP server status
- `/save` - Save current session
- `/checkpoint [name]` - Create a checkpoint
- `/checkpoints` - List available checkpoints
- `/restore <checkpoint_id>` - Restore a checkpoint
- `/sessions` - List saved sessions
- `/resume <session_id>` - Resume a saved session
- `/undo` - Selectively undo file changes (menu to choose which files)
- `/run <cmd>` or `/! <cmd>` - Run terminal command directly
- `/permissions` - View and toggle tool permissions
- `/workflow` - Run end-to-end development workflow (GitHub -> DB -> Deploy -> Test)
- `/init` - Analyze project and generate AGENTS.md / SIMHACLI.md

## Input Controls

- **Enter** - Submit message (when text is present)
- **Escape then Enter** - Insert new line (for multi-line messages)
- **Arrow keys** - Navigate within your text
- **Home/End** - Jump to start/end of line
- Multi-line paste is supported

## File Attachments

- **@filename** - Attach a file to your message
  - `@app.py` - Attach app.py from current directory
  - `@src/main.js` - Attach from subdirectory
  - `@"file with spaces.txt"` - Attach file with spaces in name
  - `@./relative/path.py` - Explicit relative path
- File contents are included in the message for the AI to analyze
- Max file size: 1MB (text files only)

## Tips

- Just type your message to chat with the agent
- The agent can read, write, and execute code
- Some operations require approval (can be configured)
- Use @filename to quickly share code context with the AI
"""
        self.console.print(Markdown(help_text))
