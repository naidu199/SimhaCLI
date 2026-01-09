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
        assistant_msg = False
        response_content = ""
        async for event in self.agent.run(message):
            if event.type == AgentEventType.TEXT_DELTA:
                content = event.data.get("content", "")
                if not assistant_msg:
                    self.tui.begin_assistant()
                    assistant_msg = True
                self.tui.stream_assistant_delta(content)

            elif event.type == AgentEventType.TEXT_COMPLETE:
                if assistant_msg:
                    self.tui.end_assistant()
                    assistant_msg = False
                response_content = event.data.get("content", "")
            elif event.type == AgentEventType.AGENT_START:
                pass  # Agent started, nothing to display
            elif event.type == AgentEventType.AGENT_END:
                pass  # Agent ended successfully
            elif event.type == AgentEventType.AGENT_ERROR:
                error_msg = event.data.get("message", "Unknown error")
                self.tui.display_error(error_message=error_msg)
                return None

        # Ensure end_assistant is called if the stream was opened
        if assistant_msg:
            self.tui.end_assistant()

        return response_content if response_content else "completed"


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
