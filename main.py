from re import A
import sys
import click
from httpx import get
from agent.agent import Agent
from agent.events import AgentEventType
from client.llm_client import LLMClinet
import asyncio

from ui.tui import TUI, get_console

console = get_console()  # Initialize console for TUI output


class SimhaCLI:
    def __init__(self):
        self.agent: Agent | None = None
        self.tui: TUI = TUI(console=console)

    async def run_single(self, message: str) -> str | None:
        async with Agent() as agent:
            self.agent = agent
            return await self.__process_message(message)

    async def __process_message(self, message: str) -> str | None:
        if self.agent is None:
            print("Agent is not initialized.")
            return None
        async for event in self.agent.run(message):
            if event.type == AgentEventType.TEXT_DELTA:
                content = event.data.get("content", "")
                self.tui.stream_assistant_delta(content)
            elif event.type == AgentEventType.AGENT_START:
                message = event.data.get("message", "")
                self.tui.stream_assistant_delta(f"Agent started: {message}\n")
            elif event.type == AgentEventType.TEXT_DELTA:
                content = event.data.get("content", "")
                self.tui.stream_assistant_delta(content)
            elif event.type == AgentEventType.AGENT_END:
                final_message = event.data.get("message", "")
                self.tui.stream_assistant_delta(f"\nAgent finished: {final_message}\n")
            elif event.type == AgentEventType.AGENT_ERROR:
                error_msg = event.data.get("message", "Unknown error")
                self.tui.stream_assistant_delta(f"\nAgent error: {error_msg}\n")


@click.command()
@click.argument("prompt", required=False)
def main(
    prompt: str | None = None,
):
    cli = SimhaCLI()
    if prompt:
        result = asyncio.run(cli.run_single(prompt))
        if result is None:
            sys.exit(1)


main()
