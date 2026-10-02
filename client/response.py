from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
import json
from typing import Any

from tools.base import Tool


@dataclass
class TextDelta:  # Represents a chunk of text received from the streaming response
    content: str
    is_final: bool = False

    def __str__(self) -> str:
        return self.content


@dataclass
class TokenUsage:  # Tracks token usage statistics
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cached_tokens: int = 0

    # To add two TokenUsage objects together
    def __add__(self, other: TokenUsage) -> TokenUsage:
        return TokenUsage(
            prompt_tokens=self.prompt_tokens + other.prompt_tokens,
            completion_tokens=self.completion_tokens + other.completion_tokens,
            total_tokens=self.total_tokens + other.total_tokens,
            cached_tokens=self.cached_tokens + other.cached_tokens,
        )


class StreamEventType(str, Enum):  # Types of events that can occur during streaming
    TEXT_DELTA = "text_delta"
    THINKING_DELTA = "thinking_delta"
    MESSAGE_COMPLETE = "message_complete"
    ERROR = "error"

    TOOL_CALL_START = "tool_call_start"
    TOOL_CALL_COMPLETE = "tool_call_complete"
    TOOL_CALL_END = "tool_call_end"
    TOOL_CALL_DELTA = "tool_call_delta"


@dataclass
class ToolCallDelta:
    call_id: str
    name: str | None = None
    arguments_delta: str = ""


@dataclass
class ToolCall:
    call_id: str
    arguments: str
    name: str | None = None


@dataclass
class StreamEvent:  # Represents an event during streaming
    type: StreamEventType
    text_delta: TextDelta | None = None
    thinking_delta: str | None = None
    error: str | None = None
    final_reason: str | None = None
    usage: TokenUsage | None = None
    tool_call_delta: ToolCallDelta | None = None
    tool_call: ToolCall | None = None


@dataclass
class ToolResultMessage:
    tool_call_id: str
    content: str
    is_error: bool = False

    def to_openai_message(self) -> dict[str, Any]:
        return {
            "role": "tool",
            "tool_call_id": self.tool_call_id,
            "content": self.content,
        }


# Key used by parse_tool_call_arguments() to signal unparseable arguments.
# Deliberately unusual so it can't collide with a real tool parameter name.
PARSE_ERROR_KEY = "__parse_error__"


def _loads_dict(text: str) -> dict[str, Any] | None:
    """json.loads that only accepts a JSON object; returns None otherwise."""
    try:
        value = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def parse_tool_call_arguments(arguments_str: str) -> dict[str, Any]:
    """Parse tool call arguments into a dict.

    On failure (malformed JSON, or valid JSON that isn't an object), returns
    ``{PARSE_ERROR_KEY: <raw arguments string>}``.
    """
    if not arguments_str or not arguments_str.strip():
        return {}

    parsed = _loads_dict(arguments_str)
    if parsed is not None:
        return parsed

    # Small models often produce malformed JSON - attempt recovery
    cleaned = arguments_str.strip()

    # Strip markdown code fences that small models sometimes wrap around JSON
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        cleaned = "\n".join(lines).strip()

    # Try to extract JSON object from surrounding text
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end != -1 and end > start:
        parsed = _loads_dict(cleaned[start : end + 1])
        if parsed is not None:
            return parsed

    # Try fixing common issues: single quotes (common small model mistake)
    parsed = _loads_dict(cleaned.replace("'", '"'))
    if parsed is not None:
        return parsed

    # Try removing trailing commas before } or ]
    import re

    parsed = _loads_dict(re.sub(r",\s*([}\]])", r"\1", cleaned))
    if parsed is not None:
        return parsed

    return {PARSE_ERROR_KEY: arguments_str}
