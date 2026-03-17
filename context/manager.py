from datetime import datetime
from typing import Any

from client.response import TokenUsage
from config.config import Config
from prompts.system import get_system_prompt
from dataclasses import dataclass, field

from tools.base import Tool
from utils.text import count_tokens


@dataclass
class MessageItem:
    role: str
    content: str
    tool_call_id: str | None = None
    tool_calls: list[dict[str, Any]] | None = field(default_factory=list)
    token_count: int | None = None  # depends upon the model tokenizer
    pruned_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {"role": self.role}
        if self.tool_call_id:
            result["tool_call_id"] = self.tool_call_id
        if self.tool_calls:
            result["tool_calls"] = self.tool_calls
        # Always include content for tool messages, even if empty
        if self.content or self.role == "tool":
            result["content"] = self.content
        return result


class ContextManager:
    PRUNE_PROTECT_TOKENS = 40000  # Minimum tokens to protect from pruning
    PRUNE_MINIMUM_TOKENS = 20000  # Minimum tokens to prune

    def __init__(
        self,
        config: Config,
        tools: list[Tool] | None,
        user_memory: str | None = None,
        git_context_str: str | None = None,
    ) -> None:
        self._git_context_str = git_context_str
        self._system_prompt = get_system_prompt(
            config=config,
            user_memory=user_memory,
            tools=tools,
            git_context_str=git_context_str,
        )
        self._config = config
        self._model_name = config.model.name
        self._messages: list[MessageItem] = []
        self._latest_usage: TokenUsage = TokenUsage()
        self._total_usage: TokenUsage = TokenUsage()

    @property
    def get_message_count(self) -> int:
        return len(self._messages)

    @property
    def total_usage(self) -> TokenUsage:
        return self._total_usage

    @total_usage.setter
    def total_usage(self, value: TokenUsage) -> None:
        self._total_usage = value

    @property
    def get_total_usage(self) -> TokenUsage:
        return self._total_usage

    def add_user_message(
        self,
        content: str,
    ) -> None:
        message = MessageItem(
            role="user",
            content=content,
            token_count=count_tokens(content or "", self._model_name),
        )
        self._messages.append(message)

    def add_assistant_message(
        self,
        content: str,
        tool_calls: list[dict[str, Any]] | None = None,
    ) -> None:
        message = MessageItem(
            role="assistant",
            content=content or "",
            tool_calls=tool_calls or [],
            token_count=count_tokens(content or "", self._model_name),
        )
        self._messages.append(message)

    def add_tool_result(self, tool_call_id: str, content: str) -> None:
        item = MessageItem(
            role="tool",
            content=content,
            tool_call_id=tool_call_id,
            token_count=count_tokens(content, self._model_name),
        )

        self._messages.append(item)

    def get_messages(self) -> list[dict[str, str]]:
        messages = []

        if self._system_prompt:
            messages.append({"role": "system", "content": self._system_prompt})

        for msg in self._messages:
            messages.append(msg.to_dict())

        return messages

    def needs_compression(self) -> bool:
        context_limit = self._config.model.context_window
        current_tokens = self._latest_usage.total_tokens

        return current_tokens > (context_limit * 0.8)

    def set_latest_usage(self, usage: TokenUsage):
        self._latest_usage = usage

    def add_usage(self, usage: TokenUsage):
        self._total_usage += usage

    def replace_with_summary(self, summary: str) -> None:
        self._messages = []

        continuation_content = f"""# Context Restoration (Previous Session Compacted)

        The previous conversation was compacted due to context length limits. Below is a detailed summary of the work done so far.

        **CRITICAL: Actions listed under "COMPLETED ACTIONS" are already done. DO NOT repeat them.**

        ---

        {summary}

        ---

        Resume work from where we left off. Focus ONLY on the remaining tasks."""

        summary_item = MessageItem(
            role="user",
            content=continuation_content,
            token_count=count_tokens(continuation_content, self._model_name),
        )
        self._messages.append(summary_item)

        ack_content = """I've reviewed the context from the previous session. I understand:
- The original goal and what was requested
- Which actions are ALREADY COMPLETED (I will NOT repeat these)
- The current state of the project
- What still needs to be done

I'll continue with the REMAINING tasks only, starting from where we left off."""
        ack_item = MessageItem(
            role="assistant",
            content=ack_content,
            token_count=count_tokens(ack_content, self._model_name),
        )
        self._messages.append(ack_item)

    def refresh_system_prompt(
        self, tools: list[Tool] | None = None, user_memory: str | None = None
    ) -> None:
        """Refresh the system prompt with updated config (e.g., after model change)."""
        self._system_prompt = get_system_prompt(
            config=self._config,
            user_memory=user_memory,
            tools=tools,
            git_context_str=self._git_context_str,
        )
        # Update model name tracking
        self._model_name = self._config.model.name

        continue_content = (
            "Continue with the REMAINING work only. Do NOT repeat any completed actions. "
            "Proceed with the next step as described in the context above."
        )

        continue_item = MessageItem(
            role="user",
            content=continue_content,
            token_count=count_tokens(continue_content, self._model_name),
        )
        self._messages.append(continue_item)

    def prune_tool_outputs(self) -> int:
        user_message_count = sum(1 for msg in self._messages if msg.role == "user")

        if user_message_count < 2:
            return 0

        total_tokens = 0
        pruned_tokens = 0
        to_prune: list[MessageItem] = []

        for msg in reversed(self._messages):
            if msg.role == "tool" and msg.tool_call_id:
                if msg.pruned_at:
                    break

                tokens = msg.token_count or count_tokens(msg.content, self._model_name)
                total_tokens += tokens

                if total_tokens > self.PRUNE_PROTECT_TOKENS:
                    pruned_tokens += tokens
                    to_prune.append(msg)

        if pruned_tokens < self.PRUNE_MINIMUM_TOKENS:
            return 0

        pruned_count = 0

        for msg in to_prune:
            msg.content = "[Old tool result content cleared]"
            msg.token_count = count_tokens(msg.content, self._model_name)
            msg.pruned_at = datetime.now()
            pruned_count += 1

        return pruned_count

    def clear(self) -> None:
        self._messages = []
