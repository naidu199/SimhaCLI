from rich.theme import Theme
from rich.console import Console
from rich.rule import Rule
from rich.text import Text

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
        "user": "bright_blue bold",
        "assistant": "white bold",
        "system": "gold3",
        # Tools
        "tool": "bright_magenta bold",
        "tool.read": "cyan",
        "tool.write": "yellow",
        "tool.shell": "bright_white",
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
        console: Console | None = None,
    ) -> None:
        self.console = console or get_console()
        self.__assistant_stream_open = False

    def begin_assistant(self) -> None:
        self.console.print()
        self.console.print(
            Rule(Text("Assistant Begin", style="assistant"), style="border")
        )
        self.__assistant_stream_open = True

    def end_assistant(self) -> None:
        if self.__assistant_stream_open:
            self.console.print()
            self.console.print(
                Rule(Text("Assistant End", style="assistant"), style="border")
            )
            self.__assistant_stream_open = False

    def stream_assistant_delta(self, content: str) -> None:
        self.console.print(content, end="", markup=False)

    def display_error(self, error_message: str) -> None:
        self.console.print(f"[error]Error: {error_message}[/error]")
