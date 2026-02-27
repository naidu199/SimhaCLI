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


def parse_tool_call_arguments(arguments_str: str) -> dict[str, Any]:
    if not arguments_str:
        return {}

    try:
        return json.loads(arguments_str)
    except json.JSONDecodeError:
        pass

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
        try:
            return json.loads(cleaned[start : end + 1])
        except json.JSONDecodeError:
            pass

    # Try fixing common issues: trailing commas, single quotes
    try:
        # Replace single quotes with double quotes (common small model mistake)
        fixed = cleaned.replace("'", '"')
        return json.loads(fixed)
    except json.JSONDecodeError:
        pass

    # Try removing trailing commas before } or ]
    import re

    try:
        fixed = re.sub(r",\s*([}\]])", r"\1", cleaned)
        return json.loads(fixed)
    except json.JSONDecodeError:
        pass

    return {"raw_arguments": arguments_str}
