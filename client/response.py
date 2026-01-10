from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
import json
from typing import Any

from regex import T

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
    error: str | None = None
    final_reason: str | None = None
    usage: TokenUsage | None = None
    tool_call_delta: ToolCallDelta | None = None
    tool_call: ToolCall | None = None


def parse_tool_call_arguments(arguments_str: str) -> dict[str, Any]:
    if not arguments_str:
        return {}

    try:
        return json.loads(arguments_str)
    except json.JSONDecodeError:
        return {"raw_arguments": arguments_str}
