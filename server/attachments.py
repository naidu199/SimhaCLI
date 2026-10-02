"""Build the agent message for ``chat/send`` (text + attached files)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from server.protocol import INVALID_PARAMS, ProtocolError
from utils.file_attachments import (
    MAX_ATTACHMENT_SIZE,
    FileAttachment,
    ImageAttachment,
    _is_image_file,
    _read_image_base64,
    format_message_with_attachments,
    format_multimodal_message,
    parse_attachments,
)


def _optional_line(value: Any, name: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ProtocolError(INVALID_PARAMS, f"{name} must be a positive integer")
    return value


def _display_path(path: Path, cwd: Path) -> str:
    try:
        return str(path.relative_to(cwd.resolve()))
    except ValueError:
        return str(path)


def _load_attachment(
    item: Any, cwd: Path, supports_vision: bool
) -> FileAttachment | ImageAttachment:
    if not isinstance(item, dict) or not isinstance(item.get("path"), str):
        raise ProtocolError(INVALID_PARAMS, "Each attachment needs a string 'path'")

    raw = Path(item["path"]).expanduser()
    path = (raw if raw.is_absolute() else cwd / raw).resolve()
    if not path.is_file():
        raise ProtocolError(INVALID_PARAMS, f"Attachment not found: {item['path']}")
    display = _display_path(path, cwd)

    start = _optional_line(item.get("startLine"), "startLine")
    end = _optional_line(item.get("endLine"), "endLine")
    if start is not None and end is not None and end < start:
        raise ProtocolError(INVALID_PARAMS, "endLine must not be before startLine")

    if _is_image_file(path):
        if start is not None or end is not None:
            raise ProtocolError(INVALID_PARAMS, f"Line ranges don't apply to images: {display}")
        if not supports_vision:
            raise ProtocolError(
                INVALID_PARAMS, f"The current model doesn't support images: {display}"
            )
        image = _read_image_base64(path)
        if image is None:
            raise ProtocolError(INVALID_PARAMS, f"Image is unreadable or too large: {display}")
        base64_data, mime_type = image
        return ImageAttachment(path, display, base64_data, mime_type)

    if path.stat().st_size > MAX_ATTACHMENT_SIZE:
        raise ProtocolError(
            INVALID_PARAMS,
            f"Attachment is larger than {MAX_ATTACHMENT_SIZE // 1_000_000} MB: {display}",
        )
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        raise ProtocolError(INVALID_PARAMS, f"Can't read {display}: {e}") from e

    if start is not None or end is not None:
        lines = content.splitlines(keepends=True)
        first = start or 1
        last = min(end or len(lines), len(lines))
        if first > len(lines):
            raise ProtocolError(
                INVALID_PARAMS,
                f"startLine {first} is past the end of {display} ({len(lines)} lines)",
            )
        content = "".join(lines[first - 1 : last])
        display = f"{display} (lines {first}-{last})"

    return FileAttachment(path, content, display)


def build_message(
    text: str,
    attachments: Any,
    cwd: Path,
    supports_vision: bool,
) -> str | list[dict[str, Any]]:
    """Combine the user's text, inline ``@path`` references and explicit
    attachments into the message passed to ``Agent.run``."""
    if attachments is None:
        attachments = []
    if not isinstance(attachments, list):
        raise ProtocolError(INVALID_PARAMS, "attachments must be a list")

    # Inline @path references work the same as in the CLI
    _, text_files, images = parse_attachments(text, cwd)
    if not supports_vision:
        images = []

    for item in attachments:
        loaded = _load_attachment(item, cwd, supports_vision)
        if isinstance(loaded, ImageAttachment):
            images.append(loaded)
        else:
            text_files.append(loaded)

    if images:
        return format_multimodal_message(text, text_files, images, cwd)
    return format_message_with_attachments(text, text_files, cwd)
