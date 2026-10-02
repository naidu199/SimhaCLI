"""
bot/telegram_bot.py
-------------------
Telegram bot that mirrors the SimhaCLI REPL over Telegram.

Routing:
  /start            -> welcome (only bot-meta command)
  /tools, /stats,   -> your existing CommandHandler + create_command_registry()
  /clear, /model,     output captured via StringIO console, sent back as text
  /approval, etc.
  <plain text>      -> Agent.run() -> TEXT_COMPLETE content only
"""

from __future__ import annotations

import asyncio
import base64
import io
import logging
from pathlib import Path
from typing import Optional

import httpx
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
from utils.file_attachments import (
    format_message_with_attachments,
    format_multimodal_message,
    FileAttachment,
    ImageAttachment,
)

log = logging.getLogger(__name__)


# ─── Auth ─────────────────────────────────────────────────────────────────────


def _is_authorized(update: Update, cfg: Config) -> bool:
    # Edited messages, channel posts, etc. may have no message/user attached
    if update.effective_user is None or update.message is None:
        return False
    uid = update.effective_user.id
    if uid not in cfg.telegram.allowed_user_ids:
        log.warning(f"Unauthorized access: user_id={uid}")
        return False
    return True


# ─── /cmd routing via your existing CommandHandler ───────────────────────────

# Commands that require the terminal UI / host stdin prompts and would block
# or crash in bot mode.
_INTERACTIVE_ONLY_COMMANDS = {"/init", "/undo"}
# Interactive when called without arguments (prompts for the command)
_INTERACTIVE_WITHOUT_ARGS_COMMANDS = {"/run", "/!"}
# Interactive when called with arguments (update/key/url prompt for values)
_INTERACTIVE_WITH_ARGS_COMMANDS = {"/credentials", "/creds"}


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

    # Normalize "/cmd@BotName args" -> "/cmd args"
    parts = slash_input.strip().split(maxsplit=1)
    cmd_name = parts[0].split("@", 1)[0].lower() if parts else ""
    cmd_args = parts[1].strip() if len(parts) > 1 else ""
    slash_input = f"{cmd_name} {cmd_args}".strip()

    # Commands that need the terminal UI or prompt on the host's stdin
    if cmd_name in _INTERACTIVE_ONLY_COMMANDS or (
        cmd_name in _INTERACTIVE_WITHOUT_ARGS_COMMANDS and not cmd_args
    ) or (cmd_name in _INTERACTIVE_WITH_ARGS_COMMANDS and cmd_args):
        return (
            f"⛔ `{slash_input}` is interactive and only works in the terminal, "
            "not in bot mode."
        )

    # /clear: the bot keeps context in session_state between runs
    if cmd_name == "/clear":
        session_state.pop("messages", None)
        agent = session_state.get("agent")
        if agent and agent.session:
            agent.session.context_manager.clear()
            agent.session.loop_detector.clear()
        return "🦁 Conversation cleared."

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
        return f"🦁 Error running `{slash_input}`: {exc}"

    output = buf.getvalue().strip()

    # result == False means /exit or /quit — tell the user
    if result is False:
        return "⛔ `/exit` and `/quit` don't apply in bot mode."

    return output or f"🦁 `{slash_input}` executed."


# ─── Agent runner ─────────────────────────────────────────────────────────────


async def _run_agent(
    prompt: str, cfg: Config, session_state: dict, thinking_msg
) -> str:
    """
    Run SimhaCLI's Agent with the given prompt and show loading indicators.
    Displays spinner, tool calls, and final response.
    """
    response_content: str = ""
    error_message: Optional[str] = None
    process_lines: list[str] = []
    last_update_time = 0
    update_interval = 0.3  # seconds between updates
    spinner_rotation = 0
    spinner_chars = ["⏳", "🔄", "🔃", "🔄"]
    current_spinner = spinner_chars[0]

    def format_tool_args(args: dict) -> str:
        """Format tool arguments as a compact string."""
        if not args:
            return ""
        parts = []
        for k, v in args.items():
            v_str = str(v)
            if len(v_str) > 50:
                v_str = v_str[:47] + "..."
            parts.append(f"{k}={v_str}")
        return "(" + ", ".join(parts) + ")"

    async def update_status(status: str, spinner: bool = True):
        """Update Telegram message with current status and optional spinner."""
        nonlocal last_update_time, spinner_rotation, current_spinner
        import time

        current_time = time.time()
        if current_time - last_update_time < update_interval:
            return
        last_update_time = current_time

        if spinner:
            spinner_rotation = (spinner_rotation + 1) % len(spinner_chars)
            current_spinner = spinner_chars[spinner_rotation]
            display_status = f"{current_spinner} **{status}**"
        else:
            display_status = status

        text = (
            display_status + "\n" + _recent_lines(process_lines)
            if process_lines
            else display_status
        )
        try:
            await thinking_msg.edit_text(_truncate(text), parse_mode="Markdown")
        except Exception:
            pass

    try:
        # No confirmation callback in bot mode: actions that need user
        # confirmation are denied unless the approval policy allows them.
        async with Agent(config=cfg) as agent:
            # Restore previous context
            saved_messages = session_state.get("messages", [])
            if saved_messages and agent.session:
                agent.session.context_manager.set_messages(saved_messages)

            session_state["agent"] = agent

            await update_status("SimhaCLI🦁 thinking", spinner=True)

            async for event in agent.run(prompt):
                if event.type == AgentEventType.TOOL_CALL_START:
                    name = event.data.get("name", "unknown")
                    args = event.data.get("arguments", {})
                    args_str = format_tool_args(args)
                    process_lines.append(f"🔧 **Invoking** `{name}`{args_str}")
                    await update_status(f"🛠️ **Running** `{name}`", spinner=True)

                elif event.type == AgentEventType.TOOL_CALL_COMPLETE:
                    name = event.data.get("name", "unknown")
                    success = event.data.get("success", False)
                    if success:
                        process_lines.append(f"🦁 `{name}` completed")
                    else:
                        error = str(event.data.get("error") or "").strip()
                        if len(error) > 100:
                            error = error[:97] + "..."
                        process_lines.append(
                            f"🦁 `{name}` failed" + (f": {error}" if error else "")
                        )
                    await update_status("🔄 **Processing results**", spinner=True)

                elif event.type == AgentEventType.TEXT_DELTA:
                    content = event.data.get("content", "")
                    response_content += content
                    await update_status("📝 Putting things together…", spinner=True)

                elif event.type == AgentEventType.AGENT_ERROR:
                    error_message = event.data.get("message", "Unknown agent error.")
                    process_lines.append(f"🦁 Error: {error_message}")
                    log.error(f"Agent error: {error_message}")
                    await update_status("🦁 **Error occurred**", spinner=False)
                    break

            # Save context
            if agent.session:
                session_state["messages"] = agent.session.context_manager.get_messages()

        session_state.pop("agent", None)

    except Exception as exc:
        log.exception("Unexpected error running agent")
        session_state.pop("agent", None)
        error_message = f"{type(exc).__name__}: {exc}"
        process_lines.append(f"🦁 Unexpected error: {error_message}")

    # Final result
    final_output = response_content.strip()
    steps = _recent_lines(process_lines)
    if error_message:
        final_text = steps + f"\n\n🦁 **Failed**: {error_message}"
    elif final_output:
        final_text = steps + f"\n\n🦁 **Response**:\n{final_output}"
    else:
        final_text = steps + "\n\n🦁 **Completed** (no text output)"

    # Telegram messages are limited to 4096 chars: edit the placeholder with the
    # first chunk and send the rest as follow-up messages.
    chunks = _split_message(final_text.strip())
    await _send_markdown_or_plain(thinking_msg.edit_text, chunks[0])
    for chunk in chunks[1:]:
        await _send_markdown_or_plain(thinking_msg.reply_text, chunk)

    if error_message:
        return f"🦁 {error_message}"

    return final_output.strip() or "🦁 Done."


# ─── Message helpers ──────────────────────────────────────────────────────────


def _truncate(text: str, limit: int = 4000) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n\n…(truncated — {len(text)} chars total)"


def _recent_lines(lines: list[str], max_lines: int = 20) -> str:
    """Join the most recent progress lines, summarizing older ones."""
    if len(lines) <= max_lines:
        return "\n".join(lines)
    hidden = len(lines) - max_lines
    return "\n".join([f"… ({hidden} earlier steps)"] + lines[-max_lines:])


def _split_message(text: str, limit: int = 4000) -> list[str]:
    """Split text into chunks that fit in a Telegram message (max 4096 chars)."""
    chunks: list[str] = []
    while len(text) > limit:
        cut = text.rfind("\n", 0, limit)
        if cut <= 0:
            cut = limit
        chunks.append(text[:cut])
        text = text[cut:].lstrip("\n")
    if text or not chunks:
        chunks.append(text or "🦁 Done.")
    return chunks


async def _send_markdown_or_plain(send, text: str) -> None:
    """Send/edit with Markdown, falling back to plain text if parsing fails."""
    try:
        await send(text, parse_mode="Markdown")
    except Exception:
        plain = text.replace("`", "").replace("*", "")
        try:
            await send(plain)
        except Exception:
            log.exception("Failed to deliver message to Telegram")


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


async def _download_photo_bytes(update: Update) -> Optional[bytes]:
    """Download the photo file from Telegram and return raw bytes."""
    if not update.message or not update.message.photo:
        return None
    photo = update.message.photo[-1]  # highest resolution
    file = await photo.get_file()
    file_bytes = await file.download_as_bytearray()
    return bytes(file_bytes)


async def _handle_photo(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    caption: str,
    thinking_msg,
    cfg: Config,
) -> str:
    """Handle a photo message from Telegram."""
    photo_bytes = await _download_photo_bytes(update)
    if not photo_bytes:
        await _safe_edit(thinking_msg, "Failed to download photo.")
        return ""

    # Determine MIME type from Telegram
    mime_type = "image/jpeg"  # Telegram photos are always JPEG
    # Encode as base64
    b64 = base64.b64encode(photo_bytes).decode("ascii")
    size = len(b64) * 3 // 4  # approximate bytes

    img = ImageAttachment(
        path=Path("telegram_photo.jpg"),
        relative_path="telegram_photo.jpg",
        base64_data=b64,
        mime_type=mime_type,
    )

    # Build the message to send — multimodal if images present, else plain text
    add_photo_info = f"\n\n[Photo attached: {mime_type}, {size:,} bytes]"

    # Check if model supports vision
    model_supports_vision = getattr(cfg.model, 'supports_vision', True)

    if not model_supports_vision:
        add_photo_info = f"\n\n[Image attached: {img.relative_path} - model does not support vision]"

    caption_with_info = (
        f"{caption}{add_photo_info}"
        if caption
        else add_photo_info.strip()
    )

    if model_supports_vision:
        # Send full multimodal message with image
        multimodal = format_multimodal_message(caption_with_info, [], [img], Path.cwd())
        status_msg = f"📷 [Photo attached: {mime_type}, {size:,} bytes]\n\n⏳ Analyzing image with vision model..."
    else:
        # Fallback: just describe the image by name
        multimodal = format_message_with_attachments(caption_with_info, [], Path.cwd())
        status_msg = f"📷 [Photo attached: {mime_type}, {size:,} bytes]\n\n⚠️ Model does not support vision, image described by name only."

    await _safe_edit(thinking_msg, status_msg)

    uid = update.effective_user.id
    session_state = _get_session(context, uid)
    result = await _run_agent(multimodal, cfg, session_state, thinking_msg)
    return result

# ─── Handlers ─────────────────────────────────────────────────────────────────


def make_handlers(cfg: Config):

    async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not _is_authorized(update, cfg):
            if update.message is not None:
                await update.message.reply_text("⛔ You are not authorized.")
            return
        name = update.effective_user.first_name or "there"
        await update.message.reply_text(
            f"👋 Hey {name}! SimhaCLI is ready.\n\n"
            f"🤖 **Model**: `{cfg.model.name}`\n\n"
            "📝 Send a message to run the agent\n"
            "⚙️ Use `/tools` to see available tools\n"
            "ℹ️ Use `/stats` for session info\n"
            "❓ Use `/help` for all commands",
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

        thinking = await update.message.reply_text(
            f"⏳ **Executing** `{slash_input}`..."
        )
        result = await _dispatch_repl_command(slash_input, cfg, session_state)
        await _safe_edit(thinking, result)

    async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Plain text -> full agent run -> simplified progress updates."""
        if not _is_authorized(update, cfg):
            return

        prompt = (update.message.text or "").strip()
        if not prompt:
            return

        uid = update.effective_user.id
        session_state = _get_session(context, uid)

        log.info(f"Agent prompt | user={uid} | prompt={prompt!r}")
        thinking = await update.message.reply_text("SimhaCLI🦁 starting...")
        result = await _run_agent(prompt, cfg, session_state, thinking)
        # The _run_agent already updates the message progressively and sets final text

    async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Photo message -> download photo -> run agent with vision."""
        if not _is_authorized(update, cfg):
            return

        caption = (update.message.caption or "").strip()
        uid = update.effective_user.id
        session_state = _get_session(context, uid)

        log.info(f"Photo received | user={uid} | caption={caption!r}")
        thinking = await update.message.reply_text("📷 Downloading photo...")
        result = await _handle_photo(update, context, caption, thinking, cfg)



    return cmd_start, handle_slash_command, handle_message, handle_photo


# ─── Bot entry point ──────────────────────────────────────────────────────────


def run_bot(cfg: Config) -> None:
    if not cfg.telegram.bot_token:
        raise ValueError("No bot token. Run `simhacli bot setup` first.")
    if not cfg.telegram.allowed_user_ids:
        raise ValueError("No allowed_user_ids. Run `simhacli bot setup` first.")

    cmd_start, handle_slash_command, handle_message, handle_photo = make_handlers(cfg)

    app = ApplicationBuilder().token(cfg.telegram.bot_token).build()

    # /start -> welcome
    app.add_handler(CommandHandler("start", cmd_start))

    # Every other /cmd -> SimhaCLI's CommandHandler
    app.add_handler(
        MessageHandler(
            filters.COMMAND & ~filters.Regex(r"^/start"),
            handle_slash_command,
        )
    )

    # Photo -> vision agent (must be before text handler)
    app.add_handler(
        MessageHandler(
            filters.PHOTO | (filters.PHOTO & filters.CAPTION),
            handle_photo,
        )
    )

    # Plain text -> agent
    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_message,
        )
    )

    log.info(
        f"SimhaCLI Telegram bot live | "
        f"model={cfg.model.name} | "
        f"users={cfg.telegram.allowed_user_ids}"
    )
    app.run_polling(drop_pending_updates=True)
