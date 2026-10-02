from __future__ import annotations

import asyncio
from threading import Lock
from typing import AsyncGenerator, Awaitable, Callable

from agent.events import AgentEvent, AgentEventType
from agent.session import Session
from client.response import (
    PARSE_ERROR_KEY,
    StreamEventType,
    TokenUsage,
    ToolCall,
    ToolResultMessage,
    parse_tool_call_arguments,
)
from config.config import Config
from prompts.system import create_loop_breaker_prompt
from tools.base import ToolConfirmation, ToolResult

# Approximate characters per token for truncation calculation
_CHARS_PER_TOKEN = 4


class Agent:
    def __init__(
        self,
        config: Config,
        confirmation_callback: (
            Callable[[ToolConfirmation], Awaitable[bool]] | None
        ) = None,
    ) -> None:
        self.config = config
        self._confirmation_callback = confirmation_callback
        self.session: Session | None = None  # Created in __aenter__
        # Track file diffs for /undo support (with thread-safe access)
        self._undo_stack: list[tuple[str, str, str]] = []  # (path, old_content, new_content)
        self._undo_lock = Lock()

    # ------------------------------------------------------------------
    # Undo stack management (thread-safe)
    # ------------------------------------------------------------------
    def clear_undo_stack(self) -> None:
        """Clear the undo stack before processing a new message."""
        with self._undo_lock:
            self._undo_stack.clear()

    def get_undo_stack(self) -> list[tuple[str, str, str]]:
        """Get the current undo stack. Note: Returns direct reference for manipulation."""
        return self._undo_stack

    def has_undo_changes(self) -> bool:
        """Check if there are changes that can be undone."""
        with self._undo_lock:
            return len(self._undo_stack) > 0

    def get_undo_count(self) -> int:
        """Get the number of files that can be undone."""
        with self._undo_lock:
            return len(self._undo_stack)

    def _append_undo(self, path: str, old_content: str, new_content: str) -> None:
        """Thread-safe append to undo stack."""
        with self._undo_lock:
            self._undo_stack.append((path, old_content, new_content))

    async def run(self, message: str | list) -> AsyncGenerator[AgentEvent, None]:
        if self.session is None:
            yield AgentEvent.agent_error("Agent not initialized. Use 'async with Agent(...) as agent:'")
            return
        # Extract user-readable text for event data and hooks — for multimodal
        # messages, pull the text parts only
        msg_text = message
        if isinstance(message, list):
            text_parts = [
                part.get("text", "")
                for part in message
                if part.get("type") == "text"
            ]
            msg_text = " ".join(p for p in text_parts if p) or "[Image attachment]"
        await self.session.hook_system.trigger_before_agent(msg_text)
        yield AgentEvent.agent_start(message=msg_text)
        self.session.context_manager.add_user_message(message)

        final_message: str | None = None
        try:
            async for event in self._agentic_loop():
                yield event
                if event.type == AgentEventType.TEXT_COMPLETE:
                    final_message = event.data.get("content", "")
            await self.session.hook_system.trigger_after_agent(
                user_message=msg_text,
                agent_response=final_message or "",
            )
            # Pass cumulative usage so the TUI can display token counts
            total_usage = self.session.context_manager.get_total_usage
            yield AgentEvent.agent_end(response=final_message, usage=total_usage)
        except Exception as e:
            yield AgentEvent.agent_error(f"Agent encountered an error: {str(e)}")
            await self.session.hook_system.trigger_on_error(e)

    # ------------------------------------------------------------------
    # Single tool call execution (used for both sequential & parallel)
    # ------------------------------------------------------------------
    async def _execute_tool_call(
        self, tool_call: ToolCall
    ) -> tuple[list[AgentEvent], ToolResultMessage | None, bool]:
        """Execute one tool call and return (events, result_message, should_stop).

        Returns collected events instead of yielding so this can be used
        inside asyncio.gather for parallel execution.
        """
        events: list[AgentEvent] = []
        parsed_args = parse_tool_call_arguments(tool_call.arguments or "")

        # --- Bad JSON ---
        if PARSE_ERROR_KEY in parsed_args:
            raw = str(parsed_args[PARSE_ERROR_KEY])
            error_result = ToolResult.error_result(
                f"Invalid JSON in tool call arguments. Could not parse: {raw[:200]}. "
                "Please provide valid JSON arguments."
            )
            events.append(
                AgentEvent.tool_call_complete(
                    tool_call.call_id, tool_call.name or "(unknown)", error_result
                )
            )
            return (
                events,
                ToolResultMessage(
                    tool_call_id=tool_call.call_id,
                    content=error_result.to_model_output(),
                    is_error=True,
                ),
                False,
            )

        # --- Missing tool name ---
        if not tool_call.name:
            error_result = ToolResult.error_result(
                "Tool call is missing a tool name. "
                "Please specify the tool name in the function call."
            )
            events.append(
                AgentEvent.tool_call_complete(
                    tool_call.call_id, "(missing)", error_result
                )
            )
            return (
                events,
                ToolResultMessage(
                    tool_call_id=tool_call.call_id,
                    content=error_result.to_model_output(),
                    is_error=True,
                ),
                False,
            )

        events.append(
            AgentEvent.tool_call_start(
                call_id=tool_call.call_id,
                name=tool_call.name,
                arguments=parsed_args,
            )
        )

        self.session.loop_detector.record_action(
            "tool_call",
            tool_name=tool_call.name,
            args=parsed_args,
        )

        try:
            result = await self.session.tool_registry.invoke(
                tool_call.name,
                parsed_args,
                self.config.cwd,
                self.session.approval_manager,
                self.session.hook_system,
            )
        except Exception as e:
            error_result = ToolResult.error_result(
                f"Tool execution failed with error: {e}"
            )
            events.append(
                AgentEvent.tool_call_complete(
                    tool_call.call_id, tool_call.name, error_result
                )
            )
            return (
                events,
                ToolResultMessage(
                    tool_call_id=tool_call.call_id,
                    content=error_result.to_model_output(),
                    is_error=True,
                ),
                False,
            )

        # --- Track file diffs for /undo ---
        if result.success and result.diff:
            self._append_undo(
                str(result.diff.path),
                result.diff.old_content,
                result.diff.new_content,
            )

        # --- Truncate oversized tool output ---
        output = result.to_model_output()
        max_chars = self.config.max_tool_output_tokens * _CHARS_PER_TOKEN
        if len(output) > max_chars:
            output = (
                output[:max_chars]
                + "\n\n[Output truncated — exceeded max_tool_output_tokens]"
            )
            result.truncated = True

        result_msg = ToolResultMessage(
            tool_call_id=tool_call.call_id,
            content=output,
            is_error=not result.success,
        )

        if result.success:
            self.session.loop_detector.record_tool_success()
        else:
            self.session.loop_detector.record_tool_failure(tool_call.name, parsed_args)
            loop_val = self.session.loop_detector.check_for_loop()
            if loop_val:
                events.append(
                    AgentEvent.tool_call_complete(
                        tool_call.call_id, tool_call.name, result
                    )
                )
                events.append(AgentEvent.agent_error(f"Stopping execution: {loop_val}"))
                # Still return the result so the tool_call gets a matching
                # tool message in the context (otherwise later API calls 400).
                return (events, result_msg, True)

        events.append(
            AgentEvent.tool_call_complete(tool_call.call_id, tool_call.name, result)
        )
        return (events, result_msg, False)

    @staticmethod
    def _tool_exception_outcome(
        tool_call: ToolCall, exc: BaseException
    ) -> tuple[list[AgentEvent], ToolResultMessage, bool]:
        """Build an error outcome for a tool call whose execution raised."""
        error_result = ToolResult.error_result(f"Tool execution failed with error: {exc}")
        return (
            [AgentEvent.agent_error(f"Tool execution error: {exc}")],
            ToolResultMessage(
                tool_call_id=tool_call.call_id,
                content=error_result.to_model_output(),
                is_error=True,
            ),
            False,
        )

    # ------------------------------------------------------------------
    # Main agentic loop
    # ------------------------------------------------------------------
    async def _agentic_loop(self) -> AsyncGenerator[AgentEvent, None]:

        max_turns = self.config.max_turns
        empty_retries = 0  # Track consecutive empty responses

        for turn_no in range(max_turns):
            self.session.increment_turn_count()
            response_text = ""
            usage: TokenUsage | None = None

            # Prune old tool outputs at 75% to avoid hitting compression
            if self.session.context_manager.needs_pruning():
                pruned = self.session.context_manager.prune_tool_outputs()
                if pruned > 0:
                    yield AgentEvent.text_delta(
                        f"\nPruned {pruned} old tool outputs to save context.\n"
                    )

            # Check for context overflow and compress if necessary
            if self.session.context_manager.needs_compression():
                yield AgentEvent.text_delta(
                    "\nContext limit approaching, compressing conversation...\n"
                )
                summary, compress_usage = await self.session.chat_compressor.compress(
                    self.session.context_manager
                )
                if summary:
                    self.session.context_manager.replace_with_summary(summary)
                    # Count the compression call toward totals, but don't treat
                    # its usage as the size of the (new, compressed) context.
                    if compress_usage:
                        self.session.context_manager.add_usage(compress_usage)
                    yield AgentEvent.text_delta(
                        "Conversation compressed. Continuing...\n"
                    )

            tool_schema = self.session.tool_registry.get_schemas()
            tool_calls: list[ToolCall] = []
            finish_reason: str | None = None

            thinking_text = ""
            async for event in self.session.client.chat_completion(
                self.session.context_manager.get_messages(),
                tools=tool_schema if tool_schema else None,
            ):
                if event.type == StreamEventType.THINKING_DELTA:
                    delta = event.thinking_delta or ""
                    thinking_text += delta
                    yield AgentEvent.thinking_delta(delta)
                elif event.type == StreamEventType.TEXT_DELTA:
                    # Transition: if we were thinking, close it before text
                    if thinking_text:
                        yield AgentEvent.thinking_complete(thinking_text)
                        thinking_text = ""
                    content = event.text_delta.content if event.text_delta else ""
                    response_text += content
                    yield AgentEvent.text_delta(content)
                elif event.type == StreamEventType.TOOL_CALL_COMPLETE:
                    if event.tool_call:
                        tool_calls.append(event.tool_call)
                elif event.type == StreamEventType.ERROR:
                    error_msg = event.error if event.error else "Unknown error"
                    yield AgentEvent.agent_error(error_msg)
                    return
                elif event.type == StreamEventType.MESSAGE_COMPLETE:
                    usage = event.usage
                    finish_reason = event.final_reason

            # Record usage exactly once per LLM call, before any branching
            if usage:
                self.session.context_manager.set_latest_usage(usage)
                self.session.context_manager.add_usage(usage)

            # Close thinking display if still open (e.g. thinking → tool_calls)
            if thinking_text:
                yield AgentEvent.thinking_complete(thinking_text)
                thinking_text = ""

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

            # --- Handle output truncation (finish_reason: "length") ---
            # The model hit its max output token limit. This can truncate
            # either plain text or tool call arguments mid-generation.
            # IMPORTANT: We must handle this BEFORE saving the assistant
            # message — otherwise broken tool_calls poison the context
            # and every subsequent API call fails with 400.
            if finish_reason == "length":
                if tool_calls:
                    # Tool call arguments are likely incomplete JSON — save
                    # only the text portion (discard the broken tool calls)
                    # so the context stays valid.
                    self.session.context_manager.add_assistant_message(
                        response_text or "", tool_calls=None
                    )
                    self.session.context_manager.add_user_message(
                        "Your response was cut off due to output length limits, and "
                        "your tool call arguments were truncated (incomplete JSON). "
                        "Please retry — if the content is large, break it into "
                        "smaller parts using multiple tool calls.",
                        synthetic=True,
                    )
                else:
                    # Text-only output was cut off. Save what we got, then
                    # ask the model to continue from where it stopped.
                    self.session.context_manager.add_assistant_message(
                        response_text or "", tool_calls=None
                    )
                    if response_text:
                        yield AgentEvent.text_complete(response_text)
                    self.session.context_manager.add_user_message(
                        "Your response was cut off due to output length limits. "
                        "Please continue exactly where you left off. Do NOT repeat "
                        "any content you already produced — just continue from the "
                        "exact point of interruption.",
                        synthetic=True,
                    )
                continue

            # Normal (non-truncated) response — save with tool calls intact
            self.session.context_manager.add_assistant_message(
                response_text or "", tool_calls=tool_calls_dict
            )

            if response_text:
                yield AgentEvent.text_complete(response_text)
                self.session.loop_detector.record_action("response", text=response_text)
                empty_retries = 0  # Reset on any content

            if not tool_calls:
                # --- Auto-retry on completely empty response (no text, no tools) ---
                if not response_text and empty_retries < 1:
                    empty_retries += 1
                    self.session.context_manager.add_user_message(
                        "Your last response was empty. Please continue with the task.",
                        synthetic=True,
                    )
                    continue

                return

            # Reset empty retries since tool calls were made
            empty_retries = 0

            # --- Execute tool calls (parallel when >1, sequential for single) ---
            outcomes: list[tuple[list[AgentEvent], ToolResultMessage | None, bool]] = []

            if len(tool_calls) == 1:
                # Single tool call — run directly
                try:
                    outcomes.append(await self._execute_tool_call(tool_calls[0]))
                except Exception as e:
                    outcomes.append(self._tool_exception_outcome(tool_calls[0], e))
            else:
                # Multiple tool calls — run in parallel via asyncio.gather
                tasks = [self._execute_tool_call(tc) for tc in tool_calls]
                results = await asyncio.gather(*tasks, return_exceptions=True)
                for tc, r in zip(tool_calls, results):
                    if isinstance(r, BaseException):
                        # Still answer this tool_call id so the context stays valid
                        outcomes.append(self._tool_exception_outcome(tc, r))
                    else:
                        outcomes.append(r)

            # Add tool results to context BEFORE yielding events, so a consumer
            # abandoning the generator mid-yield can't leave orphaned tool calls.
            stop_requested = False
            for _, result_msg, should_stop in outcomes:
                if result_msg:
                    self.session.context_manager.add_tool_result(
                        result_msg.tool_call_id,
                        result_msg.content,
                    )
                if should_stop:
                    stop_requested = True

            for events, _, _ in outcomes:
                for ev in events:
                    yield ev

            if stop_requested:
                return

            loop_detector_value = self.session.loop_detector.check_for_loop()
            if loop_detector_value:
                loop_prompt = create_loop_breaker_prompt(
                    loop_description=loop_detector_value,
                )
                self.session.context_manager.add_user_message(loop_prompt, synthetic=True)
                # Reset loop detector after intervention to allow fresh actions
                self.session.loop_detector.clear()
                continue

        yield AgentEvent.agent_error(
            f"Maximum number of turns {self.config.max_turns} reached."
        )

    async def __aenter__(self) -> Agent:
        # Create session when entering context
        self.session = Session(config=self.config)
        self.session.approval_manager.confirmation_callback = self._confirmation_callback
        try:
            await self.session.initialize()
        except BaseException:
            # Don't leak the HTTP client / already-started MCP servers
            await self.__aexit__(None, None, None)
            raise
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self.session:
            try:
                if self.session.client:
                    await self.session.client.close_client()
            except Exception:
                pass
            try:
                if self.session.mcp_manager:
                    await self.session.mcp_manager.shutdown_mcp()
            except Exception:
                pass
            self.session = None
