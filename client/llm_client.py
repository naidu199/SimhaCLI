import asyncio
from typing import Any, AsyncGenerator
from openai import APIConnectionError, APIError, AsyncOpenAI, RateLimitError

from config.config import Config
from .response import (
    TextDelta,
    TokenUsage,
    StreamEvent,
    StreamEventType,
    ToolCall,
    ToolCallDelta,
)


class LLMClient:
    def __init__(self, config: Config) -> None:
        self._client: AsyncOpenAI | None = None
        self._max_rate_limit_retries = 3
        self._config = config

    def get_client(self) -> AsyncOpenAI:
        if self._client is None:
            self._client = AsyncOpenAI(
                api_key=self._config.get_api_key(),
                base_url=self._config.get_api_base_url(),
            )
        return self._client

    async def close_client(self) -> None:
        if self._client is not None:
            await self._client.close()
        self._client = None

    def _build_tools(self, tools: list[dict[str, Any]]) -> list[dict[str, Any]]:

        return [
            {
                "type": "function",
                "function": {
                    "name": tool["name"],
                    "description": tool.get("description", ""),
                    "parameters": tool.get(
                        "parameters",
                        {
                            "type": "object",
                            "properties": {},
                        },
                    ),
                },
            }
            for tool in tools
        ]

    async def chat_completion(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        stream: bool = True,
    ) -> AsyncGenerator:

        client = self.get_client()
        kwargs = {
            "model": self._config.model.name,
            "messages": messages,
            "temperature": self._config.model.temperature,
            # "top_p": 0.9,
            "stream": stream,
        }

        if tools is not None:
            kwargs["tools"] = self._build_tools(tools)
            kwargs["tool_choice"] = "auto"

        # Handle rate limit with retries
        for attempt in range(self._max_rate_limit_retries + 1):
            try:
                # Make the API call first to catch exceptions before streaming
                response = await client.chat.completions.create(**kwargs)

                if stream:
                    async for event in self._process_stream_response(response):
                        yield event
                else:
                    event = await self._process_normal_response(response)
                    yield event
                return
            except RateLimitError as e:
                if attempt < self._max_rate_limit_retries:

                    await asyncio.sleep(2**attempt)  # Exponential backoff
                    continue
                else:
                    yield StreamEvent(
                        type=StreamEventType.ERROR,
                        error=f"Rate limit exceeded after {self._max_rate_limit_retries} retries: {str(e)}",
                    )
                    return
            except APIConnectionError as e:
                if attempt < self._max_rate_limit_retries:

                    await asyncio.sleep(2**attempt)  # Exponential backoff
                    continue
                else:
                    yield StreamEvent(
                        type=StreamEventType.ERROR,
                        error=f"API connection error after {self._max_rate_limit_retries} retries: {str(e)}",
                    )
                    return
            except APIError as e:
                # Check for specific error types and provide helpful messages
                error_str = str(e)

                # 404 data policy error (OpenRouter free models)
                if "404" in error_str and (
                    "data policy" in error_str.lower()
                    or "endpoints found" in error_str.lower()
                ):
                    yield StreamEvent(
                        type=StreamEventType.ERROR,
                        error=(
                            f"API error: {str(e)}\n\n"
                            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                            "🔓 To Fix This Error:\n"
                            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                            "1. Go to: https://openrouter.ai/settings/privacy\n"
                            "2. Enable: 'Enable free endpoints that may publish prompts'\n"
                            "3. Save your settings and try again\n\n"
                            "ℹ️  Note: Free models on OpenRouter require you to allow\n"
                            "   your prompts/completions to be published to public datasets.\n"
                            "If still facing issues after enabling this setting, terminate the agent and try again.\n"
                        ),
                    )
                    return

                # Upstream/model endpoint errors (temporary issues)
                if (
                    "upstream" in error_str.lower()
                    or "model endpoint" in error_str.lower()
                ):
                    if attempt < self._max_rate_limit_retries:
                        await asyncio.sleep(2**attempt)
                        continue
                    else:
                        yield StreamEvent(
                            type=StreamEventType.ERROR,
                            error=(
                                f"API error after {self._max_rate_limit_retries} retries: {str(e)}\n\n"
                                "💡 This model appears to be temporarily unavailable.\n"
                                "   Try one of these solutions:\n"
                                "   • Wait a moment and try again\n"
                                "   • Switch to a different model using: /model <model-name>\n"
                                "   • Recommended alternatives:\n"
                                "     - mistralai/mistral-7b-instruct:free\n"
                                "     - meta-llama/llama-3.2-3b-instruct:free\n"
                                "     - microsoft/phi-3-mini-128k-instruct:free"
                                "If still facing issues after enabling this setting, terminate the agent and try again.\n"
                            ),
                        )
                        return

                # Generic API errors with retry logic
                if attempt < self._max_rate_limit_retries:
                    await asyncio.sleep(2**attempt)  # Exponential backoff
                    continue
                else:
                    yield StreamEvent(
                        type=StreamEventType.ERROR,
                        error=f"API error after {self._max_rate_limit_retries} retries: {str(e)}",
                    )
                    return

    # Private method to process streaming responses (response already created)
    async def _process_stream_response(
        self, response
    ) -> AsyncGenerator[StreamEvent, None]:
        usage: TokenUsage | None = None
        final_reason: str | None = None
        tool_calls: dict[int, dict[str, Any]] = {}
        async for chunk in response:
            if hasattr(chunk, "usage") and chunk.usage:
                usage = TokenUsage(
                    prompt_tokens=chunk.usage.prompt_tokens,
                    completion_tokens=chunk.usage.completion_tokens,
                    total_tokens=chunk.usage.total_tokens,
                    cached_tokens=(
                        chunk.usage.prompt_tokens_details.cached_tokens
                        if chunk.usage.prompt_tokens_details
                        else 0
                    ),
                )
            if not chunk.choices:
                continue
            choice = chunk.choices[0]
            delta_content = (
                choice.delta.content
                if choice.delta and hasattr(choice.delta, "content")
                else ""
            )

            if choice.finish_reason is not None:
                final_reason = choice.finish_reason
            if delta_content:
                yield StreamEvent(
                    type=StreamEventType.TEXT_DELTA,
                    text_delta=TextDelta(content=delta_content),
                    usage=usage,
                    final_reason=final_reason,
                )
            if choice.delta.tool_calls is not None:

                for tool_call in choice.delta.tool_calls:
                    idx = tool_call.index
                    # [ChoiceDeltaToolCall(index=0, id='E1krIOK6f', function=ChoiceDeltaToolCallFunction(arguments='{"path": "main.py"}', name='read_file'), type='function')]
                    if idx not in tool_calls:
                        tool_calls[idx] = {
                            "id": tool_call.id or "",
                            "name": "",
                            "arguments": "",
                        }
                        if tool_call.function:
                            if tool_call.function.name:
                                tool_calls[idx]["name"] = tool_call.function.name or ""
                                yield StreamEvent(
                                    type=StreamEventType.TOOL_CALL_START,
                                    tool_call_delta=ToolCallDelta(
                                        call_id=tool_calls[idx]["id"],
                                        name=tool_calls[idx]["name"],
                                    ),
                                )
                            if tool_call.function.arguments:
                                tool_calls[idx][
                                    "arguments"
                                ] += tool_call.function.arguments

                                yield StreamEvent(
                                    type=StreamEventType.TOOL_CALL_DELTA,
                                    tool_call_delta=ToolCallDelta(
                                        call_id=tool_calls[idx]["id"],
                                        name=tool_calls[idx]["name"],
                                        arguments_delta=tool_calls[idx]["arguments"],
                                    ),
                                )

        for idx, tool_call in tool_calls.items():
            yield StreamEvent(
                type=StreamEventType.TOOL_CALL_COMPLETE,
                tool_call=ToolCall(
                    call_id=tool_call["id"],
                    name=tool_call["name"],
                    arguments=tool_call["arguments"],
                ),
            )
        yield StreamEvent(
            type=StreamEventType.MESSAGE_COMPLETE,
            text_delta=TextDelta(content="", is_final=True),
            usage=usage,
            final_reason=final_reason,
        )

    # Private method to process normal (non-streaming) responses (response already created)
    async def _process_normal_response(self, response) -> StreamEvent:
        choice = response.choices[0]
        message = choice.message
        text_delta = "No text present"
        if message.content:
            text_delta = TextDelta(content=message.content)
        tool_calls: list[ToolCall] = []
        if message.tool_calls:
            for tool_call in message.tool_calls:
                tool_calls.append(
                    ToolCall(
                        call_id=tool_call.id or "",
                        name=tool_call.function.name if tool_call.function else "",
                        arguments=(
                            tool_call.function.arguments if tool_call.function else ""
                        ),
                    )
                )
        if response.usage:
            usage = TokenUsage(
                prompt_tokens=response.usage.prompt_tokens,
                completion_tokens=response.usage.completion_tokens,
                total_tokens=response.usage.total_tokens,
                cached_tokens=(
                    response.usage.prompt_tokens_details.cached_tokens
                    if response.usage.prompt_tokens_details
                    else 0
                ),
            )

            return StreamEvent(
                type=StreamEventType.MESSAGE_COMPLETE,
                text_delta=text_delta,
                usage=usage,
                final_reason=choice.finish_reason,
            )
