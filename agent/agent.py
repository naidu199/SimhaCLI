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
from prompts.system import create_loop_breaker_prompt
from tools.base import ToolConfirmation, ToolResult


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
        await self.session.hook_system.trigger_before_agent(message)
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
            await self.session.hook_system.trigger_after_agent(
                user_message=message,
                agent_response=final_message or "",
            )
            yield AgentEvent.agent_end(response=final_message)
        except Exception as e:
            yield AgentEvent.agent_error(f"Agent encountered an error: {str(e)}")
            await self.session.hook_system.trigger_on_error(e)

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

            if response_text:
                yield AgentEvent.text_complete(response_text)
                self.session.loop_detector.record_action(
                    "response",
                    text=response_text,
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

                # If argument parsing returned raw_arguments, provide a clear
                # error back to the model so it can retry with valid JSON.
                if "raw_arguments" in parsed_args:
                    raw = parsed_args["raw_arguments"]
                    error_result = ToolResult.error_result(
                        f"Invalid JSON in tool call arguments. Could not parse: {raw[:200]}. "
                        "Please provide valid JSON arguments."
                    )
                    yield AgentEvent.tool_call_start(
                        call_id=tool_call.call_id,
                        name=tool_call.name,
                        arguments=parsed_args,
                    )
                    yield AgentEvent.tool_call_complete(
                        tool_call.call_id,
                        tool_call.name,
                        error_result,
                    )
                    tool_call_results.append(
                        ToolResultMessage(
                            tool_call_id=tool_call.call_id,
                            content=error_result.to_model_output(),
                            is_error=True,
                        )
                    )
                    continue

                yield AgentEvent.tool_call_start(
                    call_id=tool_call.call_id,
                    name=tool_call.name,
                    arguments=parsed_args,
                )

                self.session.loop_detector.record_action(
                    "tool_call",
                    tool_name=tool_call.name,
                    args=parsed_args,
                )

                result = await self.session.tool_registry.invoke(
                    tool_call.name or "",
                    parsed_args,
                    self.config.cwd,
                    self.session.approval_manager,
                    self.session.hook_system,
                )

                # Record tool failure for loop detection
                if not result.success:
                    self.session.loop_detector.record_tool_failure(
                        tool_call.name or "", parsed_args
                    )

                    # Check for consecutive failures immediately
                    loop_detector_value = self.session.loop_detector.check_for_loop()
                    if loop_detector_value:
                        yield AgentEvent.tool_call_complete(
                            tool_call.call_id,
                            tool_call.name,
                            result,
                        )
                        yield AgentEvent.agent_error(
                            f"Stopping execution: {loop_detector_value}"
                        )
                        return

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
            loop_detector_value = self.session.loop_detector.check_for_loop()
            if loop_detector_value:
                loop_prompt = create_loop_breaker_prompt(
                    loop_description=loop_detector_value,
                )
                self.session.context_manager.add_user_message(loop_prompt)
                continue  # Skip executing the tool and continue the loop
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
