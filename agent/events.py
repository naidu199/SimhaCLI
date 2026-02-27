from __future__ import annotations
from enum import Enum
from dataclasses import dataclass, field
from typing import Any

from client.response import TokenUsage
from tools.base import ToolResult


class AgentEventType(str, Enum):
    # Agent lifecycle events
    AGENT_START = "agent_start"
    AGENT_END = "agent_end"
    AGENT_ERROR = "agent_error"

    # Task-related events
    TEXT_DELTA = "text_delta"
    TEXT_COMPLETE = "text_complete"

    # Thinking / reasoning events (shown as grey text)
    THINKING_DELTA = "thinking_delta"
    THINKING_COMPLETE = "thinking_complete"

    # Tool call events
    TOOL_CALL_START = "tool_call_start"
    TOOL_CALL_END = "tool_call_end"
    TOOL_CALL_ERROR = "tool_call_error"
    TOOL_CALL_COMPLETE = "tool_call_complete"

    LOOP_DETECTED = "loop_detected"


@dataclass
class AgentEvent:
    type: AgentEventType
    data: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def agent_start(cls, message: str) -> AgentEvent:
        return cls(
            type=AgentEventType.AGENT_START,
            data={"message": message},
        )

    @classmethod
    def agent_end(
        cls, response: str | None = None, usage: TokenUsage | None = None
    ) -> AgentEvent:
        return cls(
            type=AgentEventType.AGENT_END,
            data={"message": response, "usage": usage.__dict__ if usage else None},
        )

    @classmethod
    def agent_error(
        cls, error: str, details: dict[str, Any] | None = None
    ) -> AgentEvent:
        return cls(
            type=AgentEventType.AGENT_ERROR,
            data={
                "message": error,
                "details": details or {},
            },
        )

    @classmethod
    def text_delta(cls, content: str) -> AgentEvent:
        return cls(
            type=AgentEventType.TEXT_DELTA,
            data={"content": content},
        )

    @classmethod
    def text_complete(cls, content: str) -> AgentEvent:
        return cls(
            type=AgentEventType.TEXT_COMPLETE,
            data={"content": content},
        )

    @classmethod
    def thinking_delta(cls, content: str) -> AgentEvent:
        return cls(
            type=AgentEventType.THINKING_DELTA,
            data={"content": content},
        )

    @classmethod
    def thinking_complete(cls, content: str) -> AgentEvent:
        return cls(
            type=AgentEventType.THINKING_COMPLETE,
            data={"content": content},
        )

    @classmethod
    def tool_call_start(
        cls,
        call_id: str,
        name: str | None = None,
        arguments: dict[str, Any] | None = None,
    ) -> AgentEvent:
        return cls(
            type=AgentEventType.TOOL_CALL_START,
            data={
                "call_id": call_id,
                "name": name,
                "arguments": arguments,
            },
        )

    @classmethod
    def tool_call_complete(
        cls,
        call_id: str,
        name: str | None = None,
        result: ToolResult | None = None,
    ) -> AgentEvent:
        return cls(
            type=AgentEventType.TOOL_CALL_COMPLETE,
            data={
                "call_id": call_id,
                "name": name,
                "result": result,
                "success": result.success if result else False,
                "output": result.output if result else None,
                "error": result.error if result else None,
                "diff": result.diff.to_diff() if result.diff else None,
                "metadata": result.metadata if result else None,
                "truncated": result.truncated if result else False,
                "exit_code": result.exit_code,
            },
        )
