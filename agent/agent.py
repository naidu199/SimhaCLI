from __future__ import annotations
from json import tool
from pathlib import Path
from tkinter import N
from typing import AsyncGenerator, final

from click import Context
from agent.events import AgentEvent, AgentEventType
from client.llm_client import LLMClinet
from client.response import (
    StreamEventType,
    ToolCall,
    ToolResultMessage,
    parse_tool_call_arguments,
)
from context.manager import ContextManager
from tools.registry import create_default_registry


class Agent:
    def __init__(self):
        self.client = LLMClinet()
        self.context_manager = ContextManager()
        self.tool_registry = create_default_registry()  # Placeholder for tool registry

    async def run(self, message: str) -> AsyncGenerator[AgentEvent, None]:
        yield AgentEvent.agent_start(message=message)
        self.context_manager.add_user_message(message)
        # add user message to the context
        final_message: str | None = None
        try:
            async for event in self._agentic_loop():
                yield event
                if event.type == AgentEventType.TEXT_COMPLETE:
                    final_message = event.data.get("content", "")
                    # yield AgentEvent.text_complete(content=final_message)

            yield AgentEvent.agent_end(response=final_message)
        except Exception as e:
            yield AgentEvent.agent_error(f"Agent encountered an error: {str(e)}")

    async def _agentic_loop(self) -> AsyncGenerator[AgentEvent, None]:

        response_text = ""

        tool_schema = self.tool_registry.get_schemas()
        tool_calls: list[ToolCall] = []
        has_error = False
        async for event in self.client.chat_completion(
            self.context_manager.get_messages(),
            tools=tool_schema if tool_schema else None,
        ):

            if event.type == StreamEventType.TEXT_DELTA:
                content = event.text_delta.content if event.text_delta else ""
                response_text += content
                yield AgentEvent.text_delta(content)
            elif event.type == StreamEventType.TOOL_CALL_COMPLETE:
                if event.tool_call:
                    tool_calls.append(event.tool_call)
            elif event.type == StreamEventType.ERROR:
                error_msg = event.error if event.error else "Unknown error"
                has_error = True
                yield AgentEvent.agent_error(error_msg)
                return  # Stop processing on error
            elif event.type == StreamEventType.MESSAGE_COMPLETE:
                usage = event.usage
                # Only yield text_complete once at the end with full response
                yield AgentEvent.text_complete(content=response_text)
        self.context_manager.add_assistant_message(response_text or "")

        tool_call_results: list[ToolResultMessage] = []

        for tool_call in tool_calls:
            parsed_args = parse_tool_call_arguments(tool_call.arguments or "")

            yield AgentEvent.tool_call_start(
                call_id=tool_call.call_id,
                name=tool_call.name,
                arguments=parsed_args,
            )

            result = await self.tool_registry.invoke(
                tool_call.name or "",
                parsed_args,
                Path.cwd(),
            )

            yield AgentEvent.tool_call_complete(
                tool_call.call_id,
                tool_call.name,
                result,
            )
            tool_call_results.append(
                ToolResultMessage(
                    tool_call_id=tool_call.call_id,
                    content=result.to_model_output(),
                    is_error=not result.success,
                )
            )

        for tool_result in tool_call_results:
            self.context_manager.add_tool_result(
                tool_result.tool_call_id,
                tool_result.content,
            )

    async def __aenter__(self) -> Agent:
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self.client:
            await self.client.close_client()
            self.client = None
