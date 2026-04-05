"""
File attachment support for SimhaCLI.

Parses @filename patterns in user input and attaches file content to messages.
Supports both text files and image files (for vision-capable models).
"""

import base64
import mimetypes
import re
from pathlib import Path
from typing import NamedTuple

# ---------------------------------------------------------------------------
# File attachment (text files)
# ---------------------------------------------------------------------------

class FileAttachment(NamedTuple):
    """Represents a text file attached to a message."""
    path: Path
    content: str
    relative_path: str


# ---------------------------------------------------------------------------
# Image attachment (for vision models)
# ---------------------------------------------------------------------------

class ImageAttachment(NamedTuple):
    """Represents an image attached to a message."""
    path: Path
    relative_path: str
    base64_data: str
    mime_type: str


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

MAX_ATTACHMENT_SIZE = 1_000_000  # 1 MB max for text files
MAX_IMAGE_SIZE = 10_000_000  # 10 MB max for image files

# Common image file extensions
IMAGE_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg", ".ico",
}

# Pattern to match @filename references
# Supports:
#   @filename.py
#   @path/to/file.js
#   @"file with spaces.txt"
#   @./relative/path.py
#   @../parent/path.py
#   @C:\absolute\path.py (Windows)
#   @/absolute/path.py (Unix)
_FILE_PATTERN = re.compile(
    r'@"([^"]+)"'  # Quoted path: @"path with spaces.txt"
    r"|@([\w./\\][\w./\\-]*)"  # Unquoted path: @filename.py or @path/to/file
)


def _is_image_file(path: Path) -> bool:
    """Check if a file is an image by extension or MIME type."""
    suffix = path.suffix.lower()
    if suffix in IMAGE_EXTENSIONS:
        return True
    mime_type, _ = mimetypes.guess_type(str(path))
    if mime_type and mime_type.startswith("image/"):
        return True
    return False


def _read_image_base64(path: Path) -> tuple[str, str] | None:
    """Read an image file and return (base64_data, mime_type).
    
    Returns None if the file can't be read or is too large.
    """
    try:
        if not path.is_absolute():
            return None
        resolved = path.resolve()
        if resolved.stat().st_size > MAX_IMAGE_SIZE:
            return None
        with open(resolved, "rb") as f:
            image_bytes = f.read()
        b64 = base64.b64encode(image_bytes).decode("ascii")
        mime_type, _ = mimetypes.guess_type(str(resolved))
        if not mime_type or not mime_type.startswith("image/"):
            mime_type = "image/png"  # fallback
        return b64, mime_type
    except (OSError, PermissionError, ValueError):
        return None


def _is_valid_text_file(path: Path, cwd: Path) -> bool:
    """Check if the path points to a valid, readable text file."""
    try:
        # Resolve relative to cwd if not absolute
        if not path.is_absolute():
            path = cwd / path
        
        resolved = path.resolve()
        
        # Check if file exists and is a file (not directory)
        if not resolved.exists():
            return False
        if not resolved.is_file():
            return False
        
        # Don't treat images as text
        if _is_image_file(resolved):
            return False
        
        # Check file size (limit to 1MB for text)
        if resolved.stat().st_size > MAX_ATTACHMENT_SIZE:
            return False
        
        # Try to read as text
        resolved.read_text(encoding="utf-8", errors="strict")
        return True
    except (OSError, UnicodeDecodeError, PermissionError):
        return False


def _read_text_file_safe(path: Path, cwd: Path) -> str | None:
    """Safely read file content. Returns None if unreadable."""
    try:
        if not path.is_absolute():
            path = cwd / path
        resolved = path.resolve()
        return resolved.read_text(encoding="utf-8", errors="replace")
    except (OSError, PermissionError):
        return None


def parse_attachments(
    input_text: str,
    cwd: Path,
) -> tuple[
    str,
    list[FileAttachment],
    list[ImageAttachment],
]:
    """
    Parse @filename patterns from user input and read file contents.
    
    Automatically detects whether each @-referenced file is text or image.
    Images are base64-encoded; text files are read as strings.
    
    Returns:
        Tuple of (cleaned_input, text_attachments, image_attachments)
    """
    text_attachments: list[FileAttachment] = []
    image_attachments: list[ImageAttachment] = []
    cleaned = input_text
    
    # Find all @ filename matches
    for match in _FILE_PATTERN.finditer(input_text):
        full_match = match.group(0)
        file_path_str = match.group(1) if match.group(1) else match.group(2)
        
        if not file_path_str:
            continue
            
        file_path_str = file_path_str.strip()
        if not file_path_str:
            continue
        
        path = Path(file_path_str)
        # Resolve relative to cwd
        if not path.is_absolute():
            resolved = cwd / path
        else:
            resolved = path
        
        resolved = resolved.resolve()
        if not resolved.exists() or not resolved.is_file():
            continue
        
        # Check if image first
        if _is_image_file(resolved):
            if resolved.stat().st_size <= MAX_IMAGE_SIZE:
                result = _read_image_base64(resolved)
                if result is not None:
                    b64, mime = result
                    try:
                        rel_path = str(path.relative_to(cwd)) if not path.is_absolute() else file_path_str
                    except ValueError:
                        rel_path = file_path_str
                    image_attachments.append(ImageAttachment(
                        path=resolved,
                        relative_path=rel_path,
                        base64_data=b64,
                        mime_type=mime,
                    ))
            continue
        
        # Otherwise treat as text
        if _is_valid_text_file(path, cwd):
            content = _read_text_file_safe(path, cwd)
            if content is not None:
                try:
                    if not path.is_absolute():
                        rel_path = file_path_str
                    else:
                        rel_path = str(path.relative_to(cwd))
                except ValueError:
                    rel_path = file_path_str
                
                text_attachments.append(FileAttachment(
                    path=resolved,
                    content=content,
                    relative_path=rel_path,
                ))
    
    return cleaned, text_attachments, image_attachments


def format_message_with_attachments(
    user_input: str,
    attachments: list[FileAttachment],
    cwd: Path,
) -> str:
    """
    Format the user message with attached text file contents for the LLM.
    Only processes text (FileAttachment) — images use multimodal format below.
    """
    if not attachments:
        return user_input
    
    parts: list[str] = []
    cleaned_input = _FILE_PATTERN.sub("", user_input).strip()
    
    if cleaned_input:
        parts.append(cleaned_input)
    
    for attachment in attachments:
        file_header = f"\n\n--- Attached File: `{attachment.relative_path}` ---"
        file_footer = f"--- End of `{attachment.relative_path}` ---\n"
        
        suffix = attachment.path.suffix.lower()
        lang_map = {
            ".py": "python", ".js": "javascript", ".ts": "typescript",
            ".jsx": "jsx", ".tsx": "tsx", ".json": "json", ".toml": "toml",
            ".yaml": "yaml", ".yml": "yaml", ".md": "markdown", ".sh": "bash",
            ".rs": "rust", ".go": "go", ".java": "java", ".c": "c",
            ".cpp": "cpp", ".h": "c", ".hpp": "cpp", ".css": "css",
            ".html": "html", ".xml": "xml", ".sql": "sql", ".rb": "ruby",
            ".php": "php", ".swift": "swift", ".kt": "kotlin",
        }
        lang = lang_map.get(suffix, "")
        
        parts.append(file_header)
        if lang:
            parts.append(f"```{lang}")
        else:
            parts.append("```")
        parts.append(attachment.content)
        parts.append("```")
        parts.append(file_footer)
    
    return "\n".join(parts)


def format_multimodal_message(
    user_input: str,
    attachments: list[FileAttachment],
    images: list[ImageAttachment],
    cwd: Path,
) -> list[dict]:
    """
    Build an OpenAI-format multimodal content list for vision models.
    
    Returns a list like:
    [
        {"type": "text", "text": "fix the error in this file"},
        {"type": "text", "text": "\n\n--- Attached File: ..."},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}}
    ]
    """
    content_parts: list[dict] = []
    
    # Text part: user input + text file attachments
    text_body = format_message_with_attachments(user_input, attachments, cwd)
    if text_body.strip():
        content_parts.append({"type": "text", "text": text_body})
    
    # Image parts
    for img in images:
        content_parts.append({
            "type": "image_url",
            "image_url": {
                "url": f"data:{img.mime_type};base64,{img.base64_data}",
            },
        })
    
    return content_parts


def get_attachment_summary(
    text_attachments: list[FileAttachment],
    image_attachments: list[ImageAttachment] | None = None,
) -> str:
    """Get a human-readable summary of attached files."""
    summaries: list[str] = []
    
    for att in text_attachments:
        lines = att.content.count("\n") + 1
        size = len(att.content.encode("utf-8"))
        summaries.append(f"[Attached] {att.relative_path} ({lines} lines, {size:,} bytes)")
    
    if image_attachments:
        for img in image_attachments:
            size = len(img.base64_data) * 3 // 4  # approximate bytes
            summaries.append(f"[Image] {img.relative_path} ({img.mime_type}, {size:,} bytes)")
    
    if not summaries:
        return ""
    
    if len(summaries) == 1:
        return summaries[0]
    
    total = f"[Attached] {len(summaries)} files"
    return total + "\n" + "\n".join(f"  - {s}" for s in summaries)
