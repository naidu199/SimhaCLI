"""Utility functions and classes."""

from utils.errors import AgentError, ConfigError
from utils.file_attachments import (
    FileAttachment,
    parse_attachments,
    format_message_with_attachments,
    get_attachment_summary,
)
from utils.git import GitContext, get_git_context, format_git_context
from utils.paths import (
    resolve_path,
    display_path_rel_to_cwd,
    ensure_parent_directory,
    is_binary_file,
)
from utils.text import (
    get_tokenizer,
    count_tokens,
    estimate_token_count,
    truncate_text,
)

__all__ = [
    # errors
    "AgentError",
    "ConfigError",
    # file_attachments
    "FileAttachment",
    "parse_attachments",
    "format_message_with_attachments",
    "get_attachment_summary",
    # git
    "GitContext",
    "get_git_context",
    "format_git_context",
    # paths
    "resolve_path",
    "display_path_rel_to_cwd",
    "ensure_parent_directory",
    "is_binary_file",
    # text
    "get_tokenizer",
    "count_tokens",
    "estimate_token_count",
    "truncate_text",
]
