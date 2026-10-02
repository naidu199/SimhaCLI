from typing import Any
from client.llm_client import LLMClient
from client.response import StreamEventType, TokenUsage
from context.manager import ContextManager
from prompts.system import get_compression_prompt


class ChatCompressor:
    def __init__(self, client: LLMClient):
        self.client = client

    @staticmethod
    def _content_to_text(content: Any) -> str:
        """Flatten message content to plain text.

        Multimodal (list) content keeps only text parts; image parts become
        "[image]" so base64 data never ends up in the compression prompt.
        """
        if content is None:
            return ""
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = []
            for part in content:
                if not isinstance(part, dict):
                    continue
                if part.get("type") == "text":
                    parts.append(part.get("text", "") or "")
                elif part.get("type") in ("image_url", "image", "input_image"):
                    parts.append("[image]")
            return "\n".join(p for p in parts if p)
        return str(content)

    def _format_history_for_compaction(self, messages: list[dict[str, Any]]) -> str:
        output = ["Here is the conversation that needs to be continue: \n"]

        for msg in messages:
            role = msg.get("role", "")
            content = self._content_to_text(msg.get("content"))

            if role == "system":
                continue

            if role == "tool":
                tool_id = msg.get("tool_call_id", "unknown")

                truncated = content[:2000] if len(content) > 2000 else content
                if len(content) > 2000:
                    truncated += "\n... [tool output truncated]"

                output.append(f"[Tool Result ({tool_id})]:\n{truncated}")
            elif role == "assistant":
                tool_details = []
                if content:
                    truncated = content[:3000] if len(content) > 3000 else content
                    if len(content) > 3000:
                        truncated += "\n... [response truncated]"
                    output.append(f"Assistant:\n{truncated}")

                if msg.get("tool_calls"):
                    for tc in msg["tool_calls"]:
                        func = tc.get("function", {})
                        name = func.get("name", "unknown")
                        args = func.get("arguments") or "{}"

                        if len(args) > 500:
                            args = args[:500]
                        tool_details.append(f"  - {name}({args})")

                    output.append("Assistant called tools:\n" + "\n".join(tool_details))
            else:
                truncated = content[:1500] if len(content) > 1500 else content
                if len(content) > 1500:
                    truncated += "\n... [message truncated]"
                output.append(f"User:\n{truncated}")

        return "\n\n---\n\n".join(output)

    async def compress(
        self, context_manager: ContextManager
    ) -> tuple[str | None, TokenUsage | None]:
        messages = context_manager.get_messages()

        if len(messages) < 3:
            return None, None

        compression_messages = [
            {
                "role": "system",
                "content": get_compression_prompt(),
            },
            {
                "role": "user",
                "content": self._format_history_for_compaction(messages),
            },
        ]

        try:
            summary = ""
            usage = None
            async for event in self.client.chat_completion(
                compression_messages,
                stream=False,
            ):
                if event.type == StreamEventType.MESSAGE_COMPLETE:
                    usage = event.usage
                    summary += event.text_delta.content

            if not summary or not usage:
                return None, None

            return summary, usage
        except Exception:
            return None, None
