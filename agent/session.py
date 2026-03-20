from datetime import datetime
import json
from typing import Any
import uuid
from client.llm_client import LLMClient

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

        self.context_manager = ContextManager(
            config=self.config,
            user_memory=self._load_memory(),
            tools=self.tool_registry.get_tools(),
            git_context_str=git_context_str,
        )
        self.discovery_manager.discover_all()
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
                self.context_manager.get_message_count() if self.context_manager else 0
            ),
            "token_usage": (
                self.context_manager.get_total_usage if self.context_manager else None
            ),
            "tools_available": len(self.tool_registry.get_tools()),
            "mcp_servers": self.tool_registry.connected_mcp_servers,
        }
