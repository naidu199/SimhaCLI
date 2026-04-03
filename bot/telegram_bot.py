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


async def _run_agent(
    prompt: str, cfg: Config, session_state: dict, thinking_msg
) -> str:
    """
    Run SimhaCLI's Agent with the given prompt and show real-time processing.
    The Telegram message (thinking_msg) is updated progressively with thinking,
    tool calls, etc. Returns final TEXT_COMPLETE content after showing full process.
    """
    response_content: str = ""
    error_message: Optional[str] = None
    process_lines: list[str] = []
    thinking_buffer: str = ""
    last_update_time = 0
    update_interval = 0.5  # seconds between Telegram message edits

    def format_tool_args(args: dict) -> str:
        """Format tool arguments as a compact string."""
        if not args:
            return "()"
        # Show arguments in one line if possible
        parts = []
        for k, v in args.items():
            # Truncate long values
            v_str = str(v)
            if len(v_str) > 100:
                v_str = v_str[:97] + "..."
            parts.append(f"{k}={v_str}")
        return "(" + ", ".join(parts) + ")"

    async def update_message(prefix: str = "🦁 Processing..."):
        """Throttled Telegram message update."""
        nonlocal last_update_time
        import time

        current_time = time.time()
        if current_time - last_update_time < update_interval:
            return  # Skip to avoid too many edits
        last_update_time = current_time

        text = prefix + "\n" + "\n".join(process_lines)
        try:
            await thinking_msg.edit_text(text, parse_mode="Markdown")
        except Exception:
            pass  # Ignore edit failures (message may be too long, etc.)

    try:
        async with Agent(config=cfg) as agent:
            # Restore previous context so follow-up messages have memory
            saved_messages = session_state.get("messages", [])
            if saved_messages and agent.session:
                agent.session.context_manager.set_messages(saved_messages)

            # Persist agent ref for command handlers (/stats, /undo etc.)
            session_state["agent"] = agent

            # Initial update
            process_lines.append("**Agent started**")
            await update_message()

            async for event in agent.run(prompt):
                if event.type == AgentEventType.AGENT_START:
                    process_lines.append("SimhaCLI🦁 started")
                    await update_message()

                elif event.type == AgentEventType.THINKING_DELTA:
                    delta = event.data.get("content", "")
                    thinking_buffer += delta
                    # Show partial thinking in muted text
                    preview = thinking_buffer[-200:].replace("\n", " ")
                    # Update or add thinking line
                    if process_lines and process_lines[-1].startswith(
                        "💭 *SimhaCLI🦁 Thinking"
                    ):
                        process_lines[-1] = f"💭 *SimhaCLI🦁 Thinking*: {preview}..."
                    else:
                        process_lines.append(f"💭 *SimhaCLI🦁 Thinking*: {preview}...")
                    await update_message()

                elif event.type == AgentEventType.THINKING_COMPLETE:
                    if thinking_buffer:
                        thought_text = thinking_buffer.strip()
                        if len(thought_text) > 300:
                            thought_text = thought_text[:297] + "..."
                        # Replace recent thinking line with complete thought
                        if process_lines and process_lines[-1].startswith(
                            "💭 *SimhaCLI🦁 Thinking"
                        ):
                            process_lines[-1] = (
                                f"💭 *SimhaCLI🦁 Thought*: {thought_text}"
                            )
                        else:
                            process_lines.append(
                                f"💭 *SimhaCLI🦁 Thought*: {thought_text}"
                            )
                        thinking_buffer = ""
                    await update_message()

                elif event.type == AgentEventType.TOOL_CALL_START:
                    name = event.data.get("name", "unknown")
                    args = event.data.get("arguments", {})
                    args_str = format_tool_args(args)
                    process_lines.append(f"🔧 **Tool**: `{name}`{args_str}")
                    await update_message()

                elif event.type == AgentEventType.TOOL_CALL_COMPLETE:
                    name = event.data.get("name", "unknown")
                    success = event.data.get("success", False)
                    result = event.data.get("result")
                    error = event.data.get("error")
                    if success:
                        output = result.output if result else ""
                        if output and len(output) > 100:
                            output = output[:97] + "..."
                        process_lines.append(f"🔧 **Tool completed**: `{name}`")
                        if output:
                            process_lines.append(f"   ↳ Output: {output}")
                    else:
                        err_msg = error or "Unknown error"
                        process_lines.append(f"🔧 **Tool failed**: `{name}`")
                        process_lines.append(f"   ↳ Error: {err_msg}")
                    await update_message()

                elif event.type == AgentEventType.TOOL_CALL_ERROR:
                    error_msg = event.data.get("message", "Tool error")
                    process_lines.append(f"🔧 **Tool error**: {error_msg}")
                    await update_message()

                elif event.type == AgentEventType.TEXT_DELTA:
                    content = event.data.get("content", "")
                    response_content += content
                    # Don't update on every delta - accumulate and update after complete

                elif event.type == AgentEventType.AGENT_ERROR:
                    error_message = event.data.get("message", "Unknown agent error.")
                    process_lines.append(f"🦁 **Agent error**: {error_message}")
                    await update_message()
                    log.error(f"Agent error: {error_message}")
                    break

                elif event.type == AgentEventType.AGENT_END:
                    # Will be handled after loop
                    pass

            # Save updated context for next message
            if agent.session:
                session_state["messages"] = agent.session.context_manager.get_messages()

        # Clear agent ref — context is closed now
        session_state.pop("agent", None)

    except Exception as exc:
        log.exception("Unexpected error running agent")
        session_state.pop("agent", None)
        error_message = f"{type(exc).__name__}: {exc}"
        process_lines.append(f"🦁 **Unexpected error**: {error_message}")

    # Final update - show process + final result
    final_output = response_content.strip()
    if error_message:
        final_text = "\n".join(process_lines) + f"\n\n🦁 {error_message}"
    elif final_output:
        final_text = "\n".join(process_lines) + f"\n\n✨ **Result**:\n{final_output}"
    else:
        final_text = "\n".join(process_lines) + "\n\n🦁 Done. (No output)"

    try:
        await thinking_msg.edit_text(final_text, parse_mode="Markdown")
    except Exception:
        # Fallback to plain text if Markdown fails
        plain = final_text.replace("`", "").replace("*", "")
        await thinking_msg.edit_text(plain)

    if error_message:
        return f"🦁 {error_message}"

    return final_output.strip() or "🦁 Done. (No text output)"


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
            await update.message.reply_text("🦁 You are not authorized.")
            return
        name = update.effective_user.first_name or "there"
        await update.message.reply_text(
            f"👋 Hey {name}! SimhaCLI🦁 is live on your laptop.\n\n"
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
        """Plain text → full agent run → real-time progress updates."""
        if not _is_authorized(update, cfg):
            return

        prompt = (update.message.text or "").strip()
        if not prompt:
            return

        uid = update.effective_user.id
        session_state = _get_session(context, uid)

        log.info(f"Agent prompt | user={uid} | prompt={prompt!r}")
        thinking = await update.message.reply_text(" Starting SimhaCLI🦁...")
        result = await _run_agent(prompt, cfg, session_state, thinking)
        # The _run_agent already updates the message progressively and sets final text

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
