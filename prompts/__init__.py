"""Prompts module - system prompts and prompt generation."""

from prompts.system import get_system_prompt, create_loop_breaker_prompt
from prompts.mcp_reference import get_mcp_setup_reference

__all__ = [
    "get_system_prompt",
    "create_loop_breaker_prompt",
    "get_mcp_setup_reference",
]
