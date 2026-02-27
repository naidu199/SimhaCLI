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
        built = []
        for tool in tools:
            params = tool.get(
                "parameters",
                {"type": "object", "properties": {}},
            )

            # Remove $defs / definitions that Pydantic may inject — small models
            # get confused by JSON-Schema references.
            params.pop("$defs", None)
            params.pop("definitions", None)

            # Ensure "type" is declared (some models require it)
            params.setdefault("type", "object")
            params.setdefault("properties", {})

            # Clean up each property — many API providers reject Pydantic
            # artefacts like "anyOf", "default", "title" in tool schemas.
            cleaned_props = {}
            for pname, pval in params.get("properties", {}).items():
                cleaned_props[pname] = self._clean_property(pval)
            params["properties"] = cleaned_props

            built.append(
                {
                    "type": "function",
                    "function": {
                        "name": tool["name"],
                        "description": tool.get("description", ""),
                        "parameters": params,
                    },
                }
            )
        return built

    @staticmethod
    def _clean_property(prop: dict[str, Any]) -> dict[str, Any]:
        """Strip Pydantic JSON-Schema artefacts that many LLM APIs reject.

        Handles: anyOf (Optional types), default values, title fields,
        and recurses into nested object properties and array items.
        """
        import copy

        p = copy.deepcopy(prop)

        # Remove "title" — Pydantic adds this but APIs don't use it
        p.pop("title", None)

        # Remove "default" — many API providers reject this field
        p.pop("default", None)

        # Resolve "anyOf" — Pydantic generates this for Optional[X] types
        # e.g. {"anyOf": [{"type": "string"}, {"type": "null"}]} → {"type": "string"}
        if "anyOf" in p:
            any_of = p.pop("anyOf")
            # Pick the first non-null type
            for variant in any_of:
                if isinstance(variant, dict) and variant.get("type") != "null":
                    # Merge the chosen variant into the property
                    for k, v in variant.items():
                        if k not in p:
                            p[k] = v
                    break
            # If no type was set (all null?), default to string
            if "type" not in p:
                p["type"] = "string"

        # Recurse into nested object properties
        if p.get("type") == "object" and "properties" in p:
            cleaned = {}
            for k, v in p["properties"].items():
                if isinstance(v, dict):
                    cleaned[k] = LLMClient._clean_property(v)
                else:
                    cleaned[k] = v
            p["properties"] = cleaned

        # Recurse into array items
        if p.get("type") == "array" and "items" in p:
            if isinstance(p["items"], dict):
                p["items"] = LLMClient._clean_property(p["items"])

        return p

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
            "stream": stream,
        }

        if stream:
            # Request usage stats in streaming mode (supported by OpenAI, OpenRouter)
            kwargs["stream_options"] = {"include_usage": True}

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
                    async for event in self._process_normal_response(response):
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

            # Capture reasoning/thinking tokens from models that support it
            # (DeepSeek uses reasoning_content, some use reasoning)
            thinking_content = ""
            if choice.delta:
                thinking_content = (
                    getattr(choice.delta, "reasoning_content", None)
                    or getattr(choice.delta, "reasoning", None)
                    or ""
                )

            if choice.finish_reason is not None:
                final_reason = choice.finish_reason

            # Yield thinking tokens before text content
            if thinking_content:
                yield StreamEvent(
                    type=StreamEventType.THINKING_DELTA,
                    thinking_delta=thinking_content,
                )

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
                    if idx not in tool_calls:
                        tool_calls[idx] = {
                            "id": tool_call.id or "",
                            "name": "",
                            "arguments": "",
                        }

                    # Update id if provided in this chunk (some providers send it later)
                    if tool_call.id:
                        tool_calls[idx]["id"] = tool_call.id

                    if tool_call.function:
                        # Update name if provided (may arrive in first or later chunk)
                        if tool_call.function.name:
                            was_unnamed = not tool_calls[idx]["name"]
                            tool_calls[idx]["name"] = tool_call.function.name
                            if was_unnamed:
                                yield StreamEvent(
                                    type=StreamEventType.TOOL_CALL_START,
                                    tool_call_delta=ToolCallDelta(
                                        call_id=tool_calls[idx]["id"],
                                        name=tool_calls[idx]["name"],
                                    ),
                                )

                        # Accumulate arguments across all chunks
                        if tool_call.function.arguments:
                            tool_calls[idx]["arguments"] += tool_call.function.arguments

                            yield StreamEvent(
                                type=StreamEventType.TOOL_CALL_DELTA,
                                tool_call_delta=ToolCallDelta(
                                    call_id=tool_calls[idx]["id"],
                                    name=tool_calls[idx]["name"],
                                    arguments_delta=tool_call.function.arguments,
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
    async def _process_normal_response(
        self, response
    ) -> AsyncGenerator[StreamEvent, None]:
        choice = response.choices[0]
        message = choice.message

        # Yield text content if present
        if message.content:
            yield StreamEvent(
                type=StreamEventType.TEXT_DELTA,
                text_delta=TextDelta(content=message.content),
            )

        # Yield individual tool call events so the agent loop can collect them
        if message.tool_calls:
            for tool_call in message.tool_calls:
                tc = ToolCall(
                    call_id=tool_call.id or "",
                    name=tool_call.function.name if tool_call.function else "",
                    arguments=(
                        tool_call.function.arguments if tool_call.function else ""
                    ),
                )
                yield StreamEvent(
                    type=StreamEventType.TOOL_CALL_COMPLETE,
                    tool_call=tc,
                )

        usage = None
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

        yield StreamEvent(
            type=StreamEventType.MESSAGE_COMPLETE,
            text_delta=TextDelta(content=message.content or "", is_final=True),
            usage=usage,
            final_reason=choice.finish_reason,
        )
