import click
from client.llm_client import LLMClinet
import asyncio



class CLI:
    def __init__(self):
        pass
    def run_single(self):
	    pass


@click.command()
@click.argument("prompt", required=False)
def main(
	prompt: str | None = None,
):
	print("Starting LLM Client...")
	print(prompt)
	client = LLMClinet()
	messages = [
		{"role": "user", "content": "Hello, how are you?"}
	]
	asyncio.run(run(messages, stream=True))

	print("Done")


async def run(messages: list[dict[str, str]], stream: bool):
	client = LLMClinet()
	async for event in client.chat_completion(messages, stream):
		if event.type == "message_complete":
			print("Received complete message:")
			print(event.final_reason)
			print("Token usage:")
			print(event.usage)
		elif event.type == "text_delta":
			print("Received text delta:")
			print(event.text_delta)
		elif event.type == "error":
			print("Error occurred:")
			print(event.error)


main()
