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

from config.config import Config
from tools.base import ToolConfirmation
from utils.paths import display_path_rel_to_cwd
import re

from utils.text import truncate_text


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

        # Setup multi-line input with prompt_toolkit
        self._prompt_session = self._create_prompt_session()

    def _create_prompt_session(self) -> PromptSession:
        """Create a prompt session with custom key bindings for multi-line input."""
        # Key bindings:
        # - Enter on empty line or Alt+Enter submits
        # - Enter with text adds newline (for multi-line editing)
        # - Escape then Enter also submits
        bindings = KeyBindings()

        @bindings.add(Keys.Enter)
        def _(event):
            """
            Enter behavior:
            - If buffer is empty or cursor is at end and line is empty: submit
            - Otherwise: insert newline for multi-line input
            """
            buffer = event.app.current_buffer
            text = buffer.text

            # Get current line
            document = buffer.document
            current_line = document.current_line

            # Submit if:
            # 1. Buffer is empty (just pressing enter without text)
            # 2. Current line is empty (double enter to submit)
            # 3. Text doesn't contain newlines (single line - submit immediately)
            if not text.strip() or current_line.strip() == "" or "\n" not in text:
                buffer.validate_and_handle()
            else:
                # Insert newline for multi-line editing
                buffer.insert_text("\n")

        @bindings.add(
            Keys.Escape, Keys.Enter
        )  # Escape then Enter (Alt+Enter equivalent)
        def _(event):
            """Force submit with Escape+Enter."""
            event.app.current_buffer.validate_and_handle()

        @bindings.add("c-j")  # Ctrl+J - common alternative for newline
        def _(event):
            """Insert newline with Ctrl+J."""
            event.app.current_buffer.insert_text("\n")

        # Custom style for the prompt
        style = PTStyle.from_dict(
            {
                "prompt": "#FFD700 bold",  # Gold color for prompt
                "input": "#FFFFFF",  # White for input text
            }
        )

        return PromptSession(
            key_bindings=bindings,
            style=style,
            multiline=True,
            prompt_continuation=lambda width, line_number, is_soft_wrap: "... ",
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
            # Only re-render every 50 chars to reduce flicker
            if len(self._buffered_content) - self._last_render_len > 50:
                self._last_render_len = len(self._buffered_content)
                self._live.update(Markdown(self._buffered_content + " ▌"))

    def display_error(self, error_message: str) -> None:
        # Stop loading indicator if it's running
        self.stop_loading()
        self.console.print(f"[error]Error: {error_message}[/error]")

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
        # Start loading indicator
        self._status = self.console.status(
            "[gold1]🦁 Simha is working...[/gold1]", spinner="dots"
        )
        self._status.start()

    def stop_loading(self) -> None:
        """Stop the loading indicator if it's running"""
        if self._status:
            self._status.stop()
            self._status = None

    def agent_end(self, usage: dict[str, Any] | None = None) -> None:
        # Stop loading indicator
        if self._status:
            self._status.stop()
            self._status = None

        # self.console.print()

        if usage:
            text = Text.assemble(
                ("SimhaCLI", "bold green"),
                ("🦁  ", "green"),
                ("  complete  ", "dim"),
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
                ("  complete", "dim"),
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
- `/undo` - Undo the last file edit made by the agent

## Input Controls

- **Enter** - Send message (single line) or add new line (in multi-line mode)
- **Enter on empty line** - Submit multi-line message
- **Escape then Enter** - Force submit message
- **Arrow keys** - Navigate within your text
- **Home/End** - Jump to start/end of line
- Multi-line paste is supported

## Tips

- Just type your message to chat with the agent
- The agent can read, write, and execute code
- Some operations require approval (can be configured)
"""
        self.console.print(Markdown(help_text))
