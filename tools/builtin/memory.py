import json
import os
import tempfile
import time
import uuid
from config.config import Config
from config.loader import get_data_dir
from tools.base import Tool, ToolInvocation, ToolKind, ToolResult
from pydantic import BaseModel, Field


class MemoryLoadError(Exception):
    """Raised when the memory file exists but cannot be parsed."""


class MemoryParams(BaseModel):
    action: str = Field(
        ..., description="Action: 'set', 'get', 'delete', 'list', 'clear'"
    )
    key: str | None = Field(
        None, description="Memory key (required for `set`, `get`, `delete`)"
    )
    value: str | None = Field(None, description="Value to store (required for `set`)")


class MemoryTool(Tool):
    name = "memory"
    description = "Store and retrieve persistent memory. Use this to remember user preferences, important context or notes."
    kind = ToolKind.MEMORY
    schema = MemoryParams

    def _memory_path(self):
        data_dir = get_data_dir()
        data_dir.mkdir(parents=True, exist_ok=True)
        return data_dir / "user_memory.json"

    def _load_memory(self) -> dict:
        path = self._memory_path()

        if not path.exists():
            return {"entries": {}}

        try:
            content = path.read_text(encoding="utf-8")
            memory = json.loads(content)
            if not isinstance(memory, dict):
                raise ValueError("top-level JSON value is not an object")
            if not isinstance(memory.setdefault("entries", {}), dict):
                raise ValueError("'entries' is not an object")
            return memory
        except Exception as e:
            # Never silently fall back to empty memory: the next save would
            # overwrite every stored entry. Move the corrupt file aside instead.
            backup = path.with_name(f"{path.name}.corrupt-{int(time.time())}")
            try:
                os.replace(path, backup)
                moved = f" It was moved to {backup}."
            except OSError:
                moved = ""
            raise MemoryLoadError(
                f"Memory file {path} is corrupt and could not be loaded ({e}).{moved}"
            ) from e

    def _save_memory(self, memory: dict) -> None:
        path = self._memory_path()

        # Atomic write: temp file in the same directory, then os.replace
        fd, tmp_name = tempfile.mkstemp(
            dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(json.dumps(memory, indent=2, ensure_ascii=False))
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_name, path)
        except BaseException:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise

    async def execute(self, invocation: ToolInvocation) -> ToolResult:
        params = MemoryParams(**invocation.params)
        action = params.action.strip().lower()

        try:
            return self._run_action(action, params)
        except MemoryLoadError as e:
            return ToolResult.error_result(str(e))
        except OSError as e:
            return ToolResult.error_result(f"Failed to access memory file: {e}")

    def _run_action(self, action: str, params: MemoryParams) -> ToolResult:
        if action == "set":
            if not params.key or not params.value:
                return ToolResult.error_result(
                    "`key` and `value` are required for 'set' action"
                )
            memory = self._load_memory()
            memory.setdefault("entries", {})[params.key] = params.value
            self._save_memory(memory)

            return ToolResult.success_result(f"Set memory: {params.key}")
        elif action == "get":
            if not params.key:
                return ToolResult.error_result("`key` required for 'get' action")

            memory = self._load_memory()
            if params.key not in memory.get("entries", {}):
                return ToolResult.success_result(
                    f"Memory not found: {params.key}",
                    metadata={
                        "found": False,
                    },
                )
            return ToolResult.success_result(
                f"Memory found: {params.key}: {memory['entries'][params.key]}",
                metadata={
                    "found": True,
                },
            )
        elif action == "delete":
            if not params.key:
                return ToolResult.error_result("`key` required for 'delete' action")
            memory = self._load_memory()
            if params.key not in memory.get("entries", {}):
                return ToolResult.success_result(f"Memory not found: {params.key}")

            del memory["entries"][params.key]
            self._save_memory(memory)

            return ToolResult.success_result(f"Deleted memory: {params.key}")
        elif action == "list":
            memory = self._load_memory()
            entries = memory.get("entries", {})
            if not entries:
                return ToolResult.success_result(
                    f"No memories stored",
                    metadata={
                        "found": False,
                    },
                )
            lines = [f"Stored memories:"]
            for key, value in sorted(entries.items()):
                lines.append(f"  {key}: {value}")

            return ToolResult.success_result(
                "\n".join(lines),
                metadata={
                    "found": True,
                },
            )
        elif action == "clear":
            memory = self._load_memory()
            count = len(memory.get("entries", {}))
            memory["entries"] = {}
            self._save_memory(memory)
            return ToolResult.success_result(f"Cleared {count} memory entries")
        else:
            return ToolResult.error_result(f"Unknown action: {params.action}")
