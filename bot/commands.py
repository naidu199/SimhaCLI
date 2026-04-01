"""
bot/commands.py
---------------
Click command group that plugs into the main simhacli CLI.

Usage:
    simhacli bot start          # start the Telegram bot
    simhacli bot setup          # interactive first-time config
    simhacli bot status         # show current bot config
"""

from __future__ import annotations

import click
from rich.console import Console
from rich.table import Table
from rich import box
import sys
import io

# Configure Rich console for Windows to handle encoding properly
if sys.platform == "win32":
    # On Windows, use UTF-8 encoding for the console
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

console = Console()


@click.group("bot")
def bot_group():
    """Manage the SimhaCLI Telegram bot (remote access from your phone)."""
    pass


@bot_group.command("start")
@click.option(
    "--token",
    "-t",
    default=None,
    envvar="SIMHACLI_BOT_TOKEN",
    help="Telegram bot token (overrides config).",
)
def bot_start(token: str | None):
    """Start the Telegram bot. Keep this running on your laptop."""
    from config.loader import load_config

    try:
        cfg = load_config(prompt_api=False)
    except Exception as e:
        console.print(f"[red]Config error:[/red] {e}")
        raise SystemExit(1)

    # Allow CLI override of token
    if token:
        cfg.telegram.bot_token = token

    if not cfg.telegram.bot_token:
        console.print(
            "[red]No bot token found.[/red] Run [bold]simhacli bot setup[/bold] first, "
            "or pass [bold]--token[/bold]."
        )
        raise SystemExit(1)

    if not cfg.telegram.allowed_user_ids:
        console.print(
            "[red]No allowed_user_ids set.[/red] Run [bold]simhacli bot setup[/bold] first."
        )
        raise SystemExit(1)

    console.print(
        f"[bold green]Starting SimhaCLI Telegram bot...[/bold green]\n"
        f"  Model      : [cyan]{cfg.model}[/cyan]\n"
        f"  Allowed IDs: [cyan]{cfg.telegram.allowed_user_ids}[/cyan]\n"
        f"\nPress [bold]Ctrl-C[/bold] to stop.\n"
    )

    from bot.telegram_bot import run_bot

    try:
        run_bot(cfg)
    except ValueError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise SystemExit(1)
    except KeyboardInterrupt:
        console.print("\n[yellow]Bot stopped.[/yellow]")


@bot_group.command("setup")
def bot_setup():
    """Interactive setup: save Telegram token and your user ID to config."""
    from config.loader import load_config, save_config

    console.print(
        "\n[bold]SimhaCLI Telegram Bot Setup[/bold]\n"
        "==============================\n"
        "You'll need:\n"
        "  1. A bot token from [link=https://t.me/botfather]@BotFather[/link]\n"
        "  2. Your Telegram user ID from [link=https://t.me/userinfobot]@userinfobot[/link]\n"
    )

    try:
        cfg = load_config(prompt_api=False)
    except Exception as e:
        console.print(f"[red]Config error:[/red] {e}")
        raise SystemExit(1)

    # Token
    existing_token = cfg.telegram.bot_token
    token_display = (
        f"[dim](current: ...{existing_token[-8:]})[/dim]" if existing_token else ""
    )
    token = click.prompt(
        f"Bot token {token_display}",
        default=existing_token or "",
        show_default=False,
    ).strip()

    if not token:
        console.print("[red]Token cannot be empty.[/red]")
        raise SystemExit(1)

    # Allowed user IDs
    existing_ids = cfg.telegram.allowed_user_ids
    existing_display = ", ".join(str(i) for i in existing_ids) if existing_ids else ""
    ids_raw = click.prompt(
        "Your Telegram user ID(s) (comma-separated)",
        default=existing_display or "",
        show_default=bool(existing_display),
    ).strip()

    try:
        allowed_ids = [int(x.strip()) for x in ids_raw.split(",") if x.strip()]
    except ValueError:
        console.print("[red]Invalid user ID - must be integers.[/red]")
        raise SystemExit(1)

    if not allowed_ids:
        console.print("[red]At least one user ID is required.[/red]")
        raise SystemExit(1)

    # Persist using set_config_value to preserve file structure
    from config.loader import set_config_value

    try:
        set_config_value("telegram", "bot_token", token)
        set_config_value("telegram", "allowed_user_ids", allowed_ids)
    except Exception as e:
        console.print(f"[red]Failed to save config:[/red] {e}")
        raise SystemExit(1)

    console.print(
        f"\n[bold green]Saved to config.[/bold green]\n"
        f"  Token      : [cyan]...{token[-8:]}[/cyan]\n"
        f"  Allowed IDs: [cyan]{allowed_ids}[/cyan]\n\n"
        f"Run [bold]simhacli bot start[/bold] to go live.\n"
    )


@bot_group.command("status")
def bot_status():
    """Show current Telegram bot configuration."""
    from config.loader import load_config

    try:
        cfg = load_config(prompt_api=False)
    except Exception as e:
        console.print(f"[red]Config error:[/red] {e}")
        raise SystemExit(1)

    tg = cfg.telegram
    token_ok = bool(tg.bot_token)
    ids_ok = bool(tg.allowed_user_ids)

    table = Table(box=box.ROUNDED, show_header=False, padding=(0, 2))
    table.add_column("Key", style="bold")
    table.add_column("Value", style="cyan")

    table.add_row(
        "Bot token",
        f"...{tg.bot_token[-8:]}" if token_ok else "[red]not set[/red]",
    )
    table.add_row(
        "Allowed user IDs",
        (
            ", ".join(str(i) for i in tg.allowed_user_ids)
            if ids_ok
            else "[red]not set[/red]"
        ),
    )
    table.add_row("Model", cfg.model)
    table.add_row("Approval", str(cfg.approval))
    table.add_row(
        "Ready?",
        (
            "[green]yes - run simhacli bot start[/green]"
            if (token_ok and ids_ok)
            else "[red]no - run simhacli bot setup[/red]"
        ),
    )

    console.print()
    console.print("[bold]SimhaCLI Telegram Bot[/bold]")
    console.print(table)
    console.print()
