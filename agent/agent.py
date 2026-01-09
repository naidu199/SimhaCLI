from __future__ import annotations
from typing import AsyncGenerator
from agent.events import AgentEvent, AgentEventType
from client.llm_client import LLMClinet
from client.response import StreamEventType


class Agent:
    def __init__(self):
        self.client = LLMClinet()

    async def run(self, message: str) -> AsyncGenerator[AgentEvent, None]:
        yield AgentEvent.agent_start(message=message)
        # add user message to the context
        try:
            async for event in self._agentic_loop(message):
                yield event
                if event.type == AgentEventType.TEXT_COMPLETE:
                    final_message = event.data.get("content", "")
                    # yield AgentEvent.text_complete(content=final_message)

            yield AgentEvent.agent_end(response=message)
        except Exception as e:
            yield AgentEvent.agent_error(f"Agent encountered an error: {str(e)}")

    async def _agentic_loop(self, message: str) -> AsyncGenerator[AgentEvent, None]:
        messages = [{"role": "user", "content": "Hello, how are you?"}]
        response_text = ""
        has_error = False
        async for event in self.client.chat_completion(messages, True):
            if event.type == StreamEventType.TEXT_DELTA:
                content = event.text_delta.content if event.text_delta else ""
                response_text += content
                yield AgentEvent.text_delta(content)
            elif event.type == StreamEventType.ERROR:
                error_msg = event.error if event.error else "Unknown error"
                has_error = True
                yield AgentEvent.agent_error(error_msg)
                return  # Stop processing on error
            elif event.type == StreamEventType.MESSAGE_COMPLETE:
                usage = event.usage
                # Only yield text_complete once at the end with full response
                yield AgentEvent.text_complete(content=response_text)

    async def __aenter__(self) -> Agent:
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self.client:
            await self.client.close_client()
            self.client = None
