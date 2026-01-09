import asyncio
from typing import Any, AsyncGenerator
from openai import APIConnectionError, APIError, APIError, AsyncOpenAI, RateLimitError
from .response import TextDelta, TokenUsage, StreamEvent, StreamEventType


class LLMClinet:
    def __init__(self) -> None:
        self._client: AsyncOpenAI | None = None
        self._max_rate_limit_retries = 3

    def get_client(self) -> AsyncOpenAI:
        if self._client is None:
            self._client = AsyncOpenAI(
                api_key="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",
                base_url="https://openrouter.ai/api/v1",
            )
        return self._client

    async def close_client(self) -> None:
        if self._client is not None:
            await self._client.close()
        self._client = None

    async def chat_completion(
        self, messages: list[dict[str, Any]], stream: bool = True
    ) -> AsyncGenerator:

        client = self.get_client()
        kwargs = {
            "model": "mistralai/devstral-2512:eee",
            "messages": messages,
            # "temperature": 0.7,
            # "top_p": 0.9,
            "stream": stream,
        }

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
                    print(f"[Retry {attempt + 1}/{self._max_rate_limit_retries}] Rate limit hit, retrying...")
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
                    print(f"[Retry {attempt + 1}/{self._max_rate_limit_retries}] Connection error, retrying...")
                    await asyncio.sleep(2**attempt)  # Exponential backoff
                    continue
                else:
                    yield StreamEvent(
                        type=StreamEventType.ERROR,
                        error=f"API connection error after {self._max_rate_limit_retries} retries: {str(e)}",
                    )
                    return
            except APIError as e:
                if attempt < self._max_rate_limit_retries:
                    print(f"[Retry {attempt + 1}/{self._max_rate_limit_retries}] API error, retrying...")
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

        yield StreamEvent(
            type=StreamEventType.MESSAGE_COMPLETE,
            text_delta=TextDelta(content="", is_final=True),
            usage=usage,
            final_reason=final_reason,
        )

    # Private method to process normal (non-streaming) responses (response already created)
    async def _process_normal_response(
        self, response
    ) -> StreamEvent:
        choice = response.choices[0]
        message = choice.message
        text_delta = "No text present"
        if message.content:
            text_delta = TextDelta(content=message.content)
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
