"""
bot/telegram_bot.py
-------------------
Telegram bot that mirrors the SimhaCLI REPL over Telegram.

Routing:
  /start            → welcome (only bot-meta command)
  /tools, /stats,   → your existing CommandHandler + create_command_registry()
  /clear, /model,     output captured via StringIO console, sent back as text
  /approval, etc.
  <plain text>      → Agent.run() → TEXT_COMPLETE content only
"""

from __future__ import annotations

import asyncio
import io
import logging
from typing import Optional

from rich.console import Console
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
from telegram.error import BadRequest

from agent.agent import Agent
from agent.events import AgentEventType
from config.config import Config

log = logging.getLogger(__name__)


# ─── Auth ─────────────────────────────────────────────────────────────────────


def _is_authorized(update: Update, cfg: Config) -> bool:
    uid = update.effective_user.id
    if uid not in cfg.telegram.allowed_user_ids:
        log.warning(f"Unauthorized access: user_id={uid}")
        return False
    return True


# ─── /cmd routing via your existing CommandHandler ───────────────────────────


async def _dispatch_repl_command(
    slash_input: str, cfg: Config, session_state: dict
) -> str:
    """
    Route /cmd_name exactly like the REPL does — reuses your
    CommandHandler + create_command_registry() so all commands
    stay in sync automatically with future additions.

    Output is captured from a StringIO-backed Rich Console
    and returned as plain text to Telegram.
    """
    from cli.factory import create_command_registry
    from cli.command_handler import CommandHandler as SimhaCommandHandler

    buf = io.StringIO()
    capture_console = Console(
        file=buf,
        highlight=False,
        markup=False,
        width=72,
        no_color=True,
    )

    handler = SimhaCommandHandler(create_command_registry())

    # Reuse agent + session from state if available so /stats etc. have context
    agent = session_state.get("agent")
    session = agent.session if agent else None

    try:
        result = await handler.handle_command(
            slash_input,
            {
                "console": capture_console,
                "config": cfg,
                "agent": agent,
                "tui": None,  # TUI not available in bot context
                "session": session,
            },
        )
    except Exception as exc:
        log.exception(f"Error handling command: {slash_input!r}")
        return f"❌ Error running `{slash_input}`: {exc}"

    output = buf.getvalue().strip()

    # result == False means /exit or /quit — tell the user
    if result is False:
        return "⛔ `/exit` and `/quit` don't apply in bot mode."

    return output or f"✅ `{slash_input}` executed."


# ─── Agent runner ─────────────────────────────────────────────────────────────


async def _run_agent(prompt: str, cfg: Config, session_state: dict) -> str:
    """
    Run SimhaCLI's Agent with the given prompt.
    Only TEXT_COMPLETE content is returned — no tool call noise, no thinking.
    Conversation history is persisted in session_state between messages.
    """
    response_content: str = ""
    error_message: Optional[str] = None

    try:
        async with Agent(config=cfg) as agent:
            # Restore previous context so follow-up messages have memory
            saved_messages = session_state.get("messages", [])
            if saved_messages and agent.session:
                agent.session.context_manager.set_messages(saved_messages)

            # Persist agent ref for command handlers (/stats, /undo etc.)
            session_state["agent"] = agent

            async for event in agent.run(prompt):
                if event.type == AgentEventType.TEXT_COMPLETE:
                    response_content = event.data.get("content", "")

                elif event.type == AgentEventType.AGENT_ERROR:
                    error_message = event.data.get("message", "Unknown agent error.")
                    log.error(f"Agent error: {error_message}")
                    break

            # Save updated context for next message
            if agent.session:
                session_state["messages"] = agent.session.context_manager.get_messages()

        # Clear agent ref — context is closed now
        session_state.pop("agent", None)

    except Exception as exc:
        log.exception("Unexpected error running agent")
        session_state.pop("agent", None)
        error_message = f"{type(exc).__name__}: {exc}"

    if error_message:
        return f"❌ {error_message}"

    return response_content.strip() or "✅ Done. (No text output)"


# ─── Message helpers ──────────────────────────────────────────────────────────


def _truncate(text: str, limit: int = 4000) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n\n…(truncated — {len(text)} chars total)"


async def _safe_edit(msg, text: str) -> None:
    """Edit placeholder message; try Markdown first, fall back to plain text."""
    try:
        await msg.edit_text(_truncate(text), parse_mode="Markdown")
    except BadRequest:
        try:
            await msg.edit_text(_truncate(text))
        except Exception:
            pass


def _get_session(context: ContextTypes.DEFAULT_TYPE, uid: int) -> dict:
    """Get or create per-user session state stored in bot_data."""
    sessions = context.bot_data.setdefault("sessions", {})
    return sessions.setdefault(uid, {})


# ─── Handlers ─────────────────────────────────────────────────────────────────


def make_handlers(cfg: Config):

    async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not _is_authorized(update, cfg):
            await update.message.reply_text("⛔ You are not authorized.")
            return
        name = update.effective_user.first_name or "there"
        await update.message.reply_text(
            f"👋 Hey {name}! SimhaCLI is live on your laptop.\n\n"
            f"Model: `{cfg.model}`\n\n"
            "Send any prompt to run it through the agent.\n"
            "Use /help to see all /commands.",
            parse_mode="Markdown",
        )

    async def handle_slash_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        Catches every /cmd from Telegram (except /start) and routes it
        through SimhaCLI's own CommandHandler — same as the REPL.
        """
        if not _is_authorized(update, cfg):
            return

        uid = update.effective_user.id
        session_state = _get_session(context, uid)

        # Pass the raw slash message straight to CommandHandler
        slash_input = (update.message.text or "").strip()

        thinking = await update.message.reply_text(f"⏳ {slash_input}…")
        result = await _dispatch_repl_command(slash_input, cfg, session_state)
        await _safe_edit(thinking, result)

    async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Plain text → full agent run → final TEXT_COMPLETE content."""
        if not _is_authorized(update, cfg):
            return

        prompt = (update.message.text or "").strip()
        if not prompt:
            return

        uid = update.effective_user.id
        session_state = _get_session(context, uid)

        log.info(f"Agent prompt | user={uid} | prompt={prompt!r}")
        thinking = await update.message.reply_text("🧠 Running…")
        result = await _run_agent(prompt, cfg, session_state)
        await _safe_edit(thinking, result)

    return cmd_start, handle_slash_command, handle_message


# ─── Bot entry point ──────────────────────────────────────────────────────────


def run_bot(cfg: Config) -> None:
    if not cfg.telegram.bot_token:
        raise ValueError("No bot token. Run `simhacli bot setup` first.")
    if not cfg.telegram.allowed_user_ids:
        raise ValueError("No allowed_user_ids. Run `simhacli bot setup` first.")

    cmd_start, handle_slash_command, handle_message = make_handlers(cfg)

    app = ApplicationBuilder().token(cfg.telegram.bot_token).build()

    # /start → welcome
    app.add_handler(CommandHandler("start", cmd_start))

    # Every other /cmd → SimhaCLI's CommandHandler
    app.add_handler(
        MessageHandler(
            filters.COMMAND & ~filters.Regex(r"^/start"),
            handle_slash_command,
        )
    )

    # Plain text → agent
    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_message,
        )
    )

    log.info(
        f"SimhaCLI Telegram bot live | "
        f"model={cfg.model} | "
        f"users={cfg.telegram.allowed_user_ids}"
    )
    app.run_polling(drop_pending_updates=True)
