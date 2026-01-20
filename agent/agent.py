from __future__ import annotations

from typing import AsyncGenerator, Awaitable, Callable

from agent.events import AgentEvent, AgentEventType
from agent.session import Session
from client.response import (
    StreamEventType,
    TokenUsage,
    ToolCall,
    ToolResultMessage,
    parse_tool_call_arguments,
)
from config.config import Config
from tools.base import ToolConfirmation


class Agent:
    def __init__(
        self,
        config: Config,
        confirmation_callback: (
            Callable[[ToolConfirmation], Awaitable[bool]] | None
        ) = None,
    ) -> None:
        self.config = config
        # self.client = LLMClient(config=self.config)
        # self.context_manager = ContextManager(config=self.config)
        # self.tool_registry = create_default_registry(config=self.config)
        self.session: Session | None = Session(config=self.config)

        self.session.approval_manager.confirmation_callback = confirmation_callback

    async def run(self, message: str) -> AsyncGenerator[AgentEvent, None]:
        yield AgentEvent.agent_start(message=message)
        self.session.context_manager.add_user_message(message)

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

        max_turns = self.config.max_turns

        for turn_no in range(max_turns):
            self.session.increment_turn_count()
            response_text = ""
            usage: TokenUsage | None = None
            # checking for the context overflow and trimming if necessary
            if self.session.context_manager.needs_compression():
                summary, usage = await self.session.chat_compressor.compress(
                    self.session.context_manager
                )
                if summary:
                    self.session.context_manager.replace_with_summary(summary)
                    self.session.context_manager.set_latest_usage(usage)
                    self.session.context_manager.add_usage(usage)
            tool_schema = self.session.tool_registry.get_schemas()
            tool_calls: list[ToolCall] = []
            has_error = False
            async for event in self.session.client.chat_completion(
                self.session.context_manager.get_messages(),
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

            # Convert tool_calls to the format expected by the API
            tool_calls_dict = (
                [
                    {
                        "id": tc.call_id,
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": tc.arguments,
                        },
                    }
                    for tc in tool_calls
                ]
                if tool_calls
                else None
            )

            self.session.context_manager.add_assistant_message(
                response_text or "", tool_calls=tool_calls_dict
            )
            if not tool_calls:
                if usage:
                    self.session.context_manager.set_latest_usage(usage)
                    self.session.context_manager.add_usage(usage)

                self.session.context_manager.prune_tool_outputs()

                return  # No tool calls, end the loop

            tool_call_results: list[ToolResultMessage] = []

            for tool_call in tool_calls:
                parsed_args = parse_tool_call_arguments(tool_call.arguments or "")

                yield AgentEvent.tool_call_start(
                    call_id=tool_call.call_id,
                    name=tool_call.name,
                    arguments=parsed_args,
                )

                result = await self.session.tool_registry.invoke(
                    tool_call.name or "",
                    parsed_args,
                    self.config.cwd,
                    self.session.approval_manager,
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
                self.session.context_manager.add_tool_result(
                    tool_result.tool_call_id,
                    tool_result.content,
                )
            if usage:
                self.session.context_manager.set_latest_usage(usage)
                self.session.context_manager.add_usage(usage)

            self.session.context_manager.prune_tool_outputs()

        yield AgentEvent.agent_error(
            f"Maximum number of turns {self.config.max_turns} reached."
        )

    async def __aenter__(self) -> Agent:
        await self.session.initialize()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self.session and self.session.client and self.session.mcp_manager:
            await self.session.client.close_client()
            await self.session.mcp_manager.shutdown_mcp()
            self.session.client = None
            self.session = None
