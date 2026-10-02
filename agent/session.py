from datetime import datetime
from pathlib import Path
import json
from typing import Any
import uuid
from agent.state import SessionSnapshot, make_session_title
from client.llm_client import LLMClient
from client.response import TokenUsage

from config.config import Config
from config.loader import get_data_dir
from context.compaction import ChatCompressor
from context.loop_detector import LoopDetector
from context.manager import ContextManager
from hooks.hook_system import HookSystem
from safety.approval import ApprovalManager
from tools.discovery import ToolDiscoveryManager
from tools.mcp.mcp_manager import MCPManager
from tools.registry import create_default_registry
from utils.git import get_git_context, format_git_context


class Session:
    def __init__(self, config: Config) -> None:
        self.config: Config = config
        self.client: LLMClient = LLMClient(config=self.config)
        self.tool_registry = create_default_registry(config=self.config)
        self.context_manager: ContextManager | None = None
        self.discovery_manager = ToolDiscoveryManager(
            config=self.config,
            registry=self.tool_registry,
        )
        self.approval_manager = ApprovalManager(
            approval_policy=self.config.approval,
            cwd=self.config.cwd,
        )
        self.hook_system = HookSystem(config=self.config)
        self.mcp_manager = MCPManager(config=self.config)
        self.loop_detector = LoopDetector()
        self.chat_compressor = ChatCompressor(client=self.client)
        self.session_id: str = str(uuid.uuid4())
        self.created_at = datetime.now()
        self.updated_at = datetime.now()

        self.turn_count: int = 0

    async def initialize(self) -> None:
        await self.mcp_manager.initialize()
        self.mcp_manager.register_tools(self.tool_registry)

        # Gather git context from the working directory
        git_ctx = get_git_context(self.config.cwd)
        git_context_str = format_git_context(git_ctx) if git_ctx else None

        # Discover custom tools before building the system prompt so they
        # are listed in it.
        self.discovery_manager.discover_all()

        self.context_manager = ContextManager(
            config=self.config,
            user_memory=self._load_memory(),
            tools=self.tool_registry.get_tools(),
            git_context_str=git_context_str,
        )
        return self

    def _load_memory(self) -> str | None:
        data_dir = get_data_dir()
        data_dir.mkdir(parents=True, exist_ok=True)
        path = data_dir / "user_memory.json"

        if not path.exists():
            return None

        try:
            content = path.read_text(encoding="utf-8")
            data = json.loads(content)
            entries = data.get("entries")
            if not entries:
                return None

            lines = ["User preferences and notes:"]
            for key, value in entries.items():
                lines.append(f"- {key}: {value}")

            return "\n".join(lines)
        except Exception:
            return None

    def has_conversation(self) -> bool:
        """True once the user has sent at least one message."""
        if not self.context_manager:
            return False
        return any(
            msg.get("role") == "user" for msg in self.context_manager.get_messages()
        )

    def to_snapshot(self, source: str = "cli") -> SessionSnapshot:
        messages = self.context_manager.get_messages() if self.context_manager else []
        return SessionSnapshot(
            session_id=self.session_id,
            created_at=self.created_at,
            updated_at=datetime.now(),
            turn_count=self.turn_count,
            messages=messages,
            total_usage=(
                self.context_manager.total_usage
                if self.context_manager
                else TokenUsage()
            ),
            title=make_session_title(messages),
            cwd=str(Path(self.config.cwd).resolve()),
            model=self.config.model.name,
            source=source,
        )

    def restore_snapshot(self, snapshot: SessionSnapshot) -> None:
        """Continue a saved conversation in this (already initialized) session.

        The current system prompt is kept so tools, git context and project
        instructions reflect the present environment.
        """
        self.session_id = snapshot.session_id
        self.created_at = snapshot.created_at
        self.updated_at = snapshot.updated_at
        self.turn_count = snapshot.turn_count
        self.context_manager.set_messages(
            [m for m in snapshot.messages if m.get("role") != "system"]
        )
        self.context_manager.total_usage = snapshot.total_usage
        self.loop_detector.clear()

    def start_new(self) -> None:
        """Start a fresh conversation under a new session id."""
        self.session_id = str(uuid.uuid4())
        self.created_at = datetime.now()
        self.updated_at = datetime.now()
        self.turn_count = 0
        if self.context_manager:
            self.context_manager.clear()
            self.context_manager.total_usage = TokenUsage()
        self.loop_detector.clear()

    def increment_turn_count(self) -> None:
        self.turn_count += 1
        self.updated_at = datetime.now()

        return self.turn_count

    def get_stats(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "turn_count": self.turn_count,
            "message_count": (
                self.context_manager.get_message_count if self.context_manager else 0
            ),
            "token_usage": (
                self.context_manager.get_total_usage if self.context_manager else None
            ),
            "tools_available": len(self.tool_registry.get_tools()),
            "mcp_servers": self.tool_registry.connected_mcp_servers,
        }
