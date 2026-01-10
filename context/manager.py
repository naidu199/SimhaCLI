from itertools import count
import token
from typing import Any
from prompts.system import get_system_prompt
from dataclasses import dataclass

from utils.text import count_tokens


@dataclass
class MessageItem:
    role: str
    content: str
    token_count: int | None = None  # depends upon the model tokenizer

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {"role": self.role}
        if self.content:
            result["content"] = self.content
        return result


class ContextManager:
    def __init__(self) -> None:
        self._system_prompt = get_system_prompt()
        self._model_name = "mistralai/devstral-2512:free"
        self._messages: list[MessageItem] = []

    def add_user_message(
        self,
        content: str,
    ) -> None:
        message = MessageItem(
            role="user",
            content=content,
            token_count=count_tokens(content, self._model_name),
        )
        self._messages.append(message)

    def add_assistant_message(
        self,
        content: str,
    ) -> None:
        message = MessageItem(
            role="assistant",
            content=content or "",
            token_count=count_tokens(content, self._model_name),
        )
        self._messages.append(message)

    def get_messages(self) -> list[dict[str, str]]:
        messages = []

        if self._system_prompt:
            messages.append({"role": "system", "content": self._system_prompt})

        for msg in self._messages:
            messages.append(msg.to_dict())

        return messages
