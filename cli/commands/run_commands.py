"""Run command: /run or /! - Execute terminal commands directly."""

import asyncio
import subprocess

from rich.markup import escape

from .base import Command, CommandResult
from typing import Any


class RunCommand(Command):
    @property
    def name(self) -> str:
        return "/run"

    async def execute(self, args: str, context: dict[str, Any]) -> CommandResult:
        config = context.get("config")
        tui = context.get("tui")
        console = context.get("console")
        if not config or not console:
            return CommandResult(success=False, message="Missing context")

        cmd_args = args.strip()
        if not cmd_args:
            try:
                cmd_args = await tui.get_multiline_input("Enter command: ")
                cmd_args = (cmd_args or "").strip()
            except (KeyboardInterrupt, EOFError):
                console.print("[dim]Cancelled.[/dim]")
                return CommandResult(success=True)

        if not cmd_args:
            console.print("[warning]No command provided.[/warning]")
            return CommandResult(success=False)

        console.print(f"[dim]$ {escape(cmd_args)}[/dim]")
        try:
            result = await asyncio.to_thread(
                subprocess.run,
                cmd_args,
                shell=True,
                capture_output=True,
                text=True,
                cwd=str(config.cwd),
                timeout=120,
            )
            # Print raw output without Rich markup so "[project]"-style lines
            # are not swallowed and "[/x]" does not raise MarkupError
            if result.stdout:
                console.print(result.stdout.rstrip(), markup=False, highlight=False)
            if result.stderr:
                console.print(
                    result.stderr.rstrip(),
                    style="yellow",
                    markup=False,
                    highlight=False,
                )
            if result.returncode != 0:
                console.print(f"[dim]Exit code: {result.returncode}[/dim]")
            return CommandResult(success=True)
        except subprocess.TimeoutExpired:
            console.print("[error]Command timed out (120s)[/error]")
            return CommandResult(success=False)
        except Exception as e:
            console.print(f"[error]Error: {escape(str(e))}[/error]")
            return CommandResult(success=False)

    def get_help(self) -> str:
        return "Execute a terminal command directly. Usage: /run <command>"


class BangCommand(RunCommand):
    """Alias for /run using ! notation."""

    @property
    def name(self) -> str:
        return "/!"
