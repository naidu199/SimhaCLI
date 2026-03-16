"""
File attachment utility for SimhaCLI.

Parses @filename patterns in user input and attaches file content to messages.
"""

import re
from pathlib import Path
from typing import NamedTuple


class FileAttachment(NamedTuple):
    """Represents an attached file."""
    path: Path
    content: str
    relative_path: str


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


def _is_valid_file(path: Path, cwd: Path) -> bool:
    """Check if the path points to a valid, readable file."""
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
        
        # Check file size (limit to 1MB for safety)
        if resolved.stat().st_size > 1_000_000:
            return False
        
        # Try to read as text
        resolved.read_text(encoding="utf-8", errors="strict")
        return True
    except (OSError, UnicodeDecodeError, PermissionError):
        return False


def _read_file_safe(path: Path, cwd: Path) -> str | None:
    """Safely read file content. Returns None if unreadable."""
    try:
        if not path.is_absolute():
            path = cwd / path
        resolved = path.resolve()
        return resolved.read_text(encoding="utf-8", errors="replace")
    except (OSError, PermissionError):
        return None


def parse_attachments(input_text: str, cwd: Path) -> tuple[str, list[FileAttachment]]:
    """
    Parse @filename patterns from user input and read file contents.
    
    Args:
        input_text: The raw user input containing @filename references
        cwd: Current working directory for resolving relative paths
        
    Returns:
        Tuple of (cleaned_input, list_of_attachments)
        - cleaned_input: The user input with @filename replaced by a placeholder
        - list_of_attachments: List of FileAttachment objects with file content
    """
    attachments: list[FileAttachment] = []
    cleaned = input_text
    
    # Find all @filename matches
    for match in _FILE_PATTERN.finditer(input_text):
        full_match = match.group(0)
        # Get the path (either quoted or unquoted)
        file_path_str = match.group(1) if match.group(1) else match.group(2)
        
        if not file_path_str:
            continue
            
        # Normalize path separators
        file_path_str = file_path_str.strip()
        if not file_path_str:
            continue
        
        path = Path(file_path_str)
        
        # Validate and read the file
        if _is_valid_file(path, cwd):
            content = _read_file_safe(path, cwd)
            if content is not None:
                # Calculate relative path for display
                try:
                    if not path.is_absolute():
                        rel_path = file_path_str
                    else:
                        rel_path = str(path.relative_to(cwd))
                except ValueError:
                    rel_path = file_path_str
                
                attachments.append(FileAttachment(
                    path=path.resolve(),
                    content=content,
                    relative_path=rel_path,
                ))
    
    return cleaned, attachments


def format_message_with_attachments(
    user_input: str,
    attachments: list[FileAttachment],
    cwd: Path,
) -> str:
    """
    Format the user message with attached file contents for the LLM.
    
    Args:
        user_input: Original user input
        attachments: List of file attachments
        cwd: Current working directory
        
    Returns:
        Formatted message with file contents embedded
    """
    if not attachments:
        return user_input
    
    # Build the message with file contents
    parts: list[str] = []
    
    # Remove @filename references from the user input for the LLM
    # (they'll see the full file content instead)
    cleaned_input = _FILE_PATTERN.sub("", user_input).strip()
    
    if cleaned_input:
        parts.append(cleaned_input)
    
    # Add file contents
    for attachment in attachments:
        file_header = f"\n\n--- Attached File: `{attachment.relative_path}` ---"
        file_footer = f"--- End of `{attachment.relative_path}` ---\n"
        
        # Determine file extension for context
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


def get_attachment_summary(attachments: list[FileAttachment]) -> str:
    """Get a human-readable summary of attached files."""
    if not attachments:
        return ""
    
    if len(attachments) == 1:
        att = attachments[0]
        lines = att.content.count("\n") + 1
        size = len(att.content.encode("utf-8"))
        return f"[Attached] {att.relative_path} ({lines} lines, {size:,} bytes)"
    
    summaries = []
    total_lines = 0
    total_bytes = 0
    for att in attachments:
        lines = att.content.count("\n") + 1
        size = len(att.content.encode("utf-8"))
        total_lines += lines
        total_bytes += size
        summaries.append(f"  - {att.relative_path} ({lines} lines)")
    
    header = f"[Attached] {len(attachments)} files ({total_lines} lines, {total_bytes:,} bytes total)"
    return header + "\n" + "\n".join(summaries)
