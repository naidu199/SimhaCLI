import uuid
from enum import Enum
from config.config import Config
from tools.base import Tool, ToolInvocation, ToolKind, ToolResult
from pydantic import BaseModel, Field


class TodoPriority(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class TodoStatus(str, Enum):
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"


class TodoItem:
    def __init__(self, content: str, priority: TodoPriority = TodoPriority.MEDIUM):
        self.id = str(uuid.uuid4())[:8]
        self.content = content
        self.priority = priority
        self.status = TodoStatus.NOT_STARTED

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "content": self.content,
            "priority": self.priority.value,
            "status": self.status.value,
        }


class TodosParams(BaseModel):
    action: str = Field(
        ...,
        description="Action: 'add', 'start', 'complete', 'list', 'clear', 'remove'",
    )
    id: str | None = Field(None, description="Todo ID (for start/complete/remove)")
    content: str | None = Field(None, description="Todo content (for add)")
    priority: str | None = Field(
        "medium",
        description="Priority: 'high', 'medium', 'low' (for add, default: medium)",
    )


class TodosTool(Tool):
    name = "todos"
    description = (
        "Manage a task list with priorities and status tracking. "
        "Use this to track multi-step tasks with clear progress visibility. "
        "Actions: add (create), start (mark in-progress), complete, list, remove, clear."
    )
    kind = ToolKind.MEMORY
    schema = TodosParams

    def __init__(self, config: Config) -> None:
        super().__init__(config)
        self._todos: dict[str, TodoItem] = {}

    async def execute(self, invocation: ToolInvocation) -> ToolResult:
        params = TodosParams(**invocation.params)
        action = params.action.lower()

        if action == "add":
            if not params.content:
                return ToolResult.error_result("`content` required for 'add' action")

            try:
                priority = TodoPriority(params.priority or "medium")
            except ValueError:
                return ToolResult.error_result(
                    f"Invalid priority: {params.priority}. Use 'high', 'medium', or 'low'."
                )

            todo = TodoItem(params.content, priority)
            self._todos[todo.id] = todo

            priority_icon = {"high": "🔴", "medium": "🟡", "low": "🟢"}[priority.value]

            return ToolResult.success_result(
                f"✅ Added todo [{todo.id}]: {params.content}",
                metadata={
                    "id": todo.id,
                    "priority": priority.value,
                    "status": "not_started",
                    "total_todos": len(self._todos),
                },
            )

        elif action == "start":
            if not params.id:
                return ToolResult.error_result("`id` required for 'start' action")
            if params.id not in self._todos:
                return ToolResult.error_result(f"Todo not found: {params.id}")

            todo = self._todos[params.id]
            if todo.status == TodoStatus.COMPLETED:
                return ToolResult.error_result(
                    f"Todo [{params.id}] is already completed"
                )

            todo.status = TodoStatus.IN_PROGRESS
            return ToolResult.success_result(
                f"▶️  Started todo [{params.id}]: {todo.content}",
                metadata={
                    "id": todo.id,
                    "status": "in_progress",
                    "in_progress_count": sum(
                        1
                        for t in self._todos.values()
                        if t.status == TodoStatus.IN_PROGRESS
                    ),
                },
            )

        elif action == "complete":
            if not params.id:
                return ToolResult.error_result("`id` required for 'complete' action")
            if params.id not in self._todos:
                return ToolResult.error_result(f"Todo not found: {params.id}")

            todo = self._todos[params.id]
            todo.status = TodoStatus.COMPLETED
            content = todo.content

            # Calculate progress
            completed = sum(
                1 for t in self._todos.values() if t.status == TodoStatus.COMPLETED
            )
            total = len(self._todos)

            return ToolResult.success_result(
                f"✅ Completed todo [{params.id}]: {content}\n📊 Progress: {completed}/{total} tasks completed",
                metadata={
                    "id": params.id,
                    "completed": completed,
                    "total": total,
                    "progress_percent": (
                        int((completed / total) * 100) if total > 0 else 0
                    ),
                },
            )

        elif action == "remove":
            if not params.id:
                return ToolResult.error_result("`id` required for 'remove' action")
            if params.id not in self._todos:
                return ToolResult.error_result(f"Todo not found: {params.id}")

            todo = self._todos.pop(params.id)
            return ToolResult.success_result(
                f"🗑️  Removed todo [{params.id}]: {todo.content}",
                metadata={"remaining_todos": len(self._todos)},
            )

        elif action == "list":
            if not self._todos:
                return ToolResult.success_result(
                    "📋 No todos",
                    metadata={"total": 0, "in_progress": 0, "completed": 0},
                )

            # Sort by priority and status
            priority_order = {"high": 0, "medium": 1, "low": 2}
            status_order = {"in_progress": 0, "not_started": 1, "completed": 2}

            sorted_todos = sorted(
                self._todos.values(),
                key=lambda t: (
                    status_order[t.status.value],
                    priority_order[t.priority.value],
                ),
            )

            lines = ["📋 Task List:\n"]

            # Group by status
            in_progress = [
                t for t in sorted_todos if t.status == TodoStatus.IN_PROGRESS
            ]
            not_started = [
                t for t in sorted_todos if t.status == TodoStatus.NOT_STARTED
            ]
            completed = [t for t in sorted_todos if t.status == TodoStatus.COMPLETED]

            priority_icons = {"high": "🔴", "medium": "🟡", "low": "🟢"}
            status_icons = {"in_progress": "▶️ ", "not_started": "⏸️ ", "completed": "✅"}

            if in_progress:
                lines.append("▶️  In Progress:")
                for todo in in_progress:
                    lines.append(
                        f"  {priority_icons[todo.priority.value]} [{todo.id}] {todo.content}"
                    )
                lines.append("")

            if not_started:
                lines.append("⏸️  Not Started:")
                for todo in not_started:
                    lines.append(
                        f"  {priority_icons[todo.priority.value]} [{todo.id}] {todo.content}"
                    )
                lines.append("")

            if completed:
                lines.append("✅ Completed:")
                for todo in completed:
                    lines.append(f"  ~~[{todo.id}] {todo.content}~~")
                lines.append("")

            # Summary
            total = len(self._todos)
            completed_count = len(completed)
            progress = int((completed_count / total) * 100) if total > 0 else 0

            lines.append(
                f"📊 Summary: {completed_count}/{total} completed ({progress}%)"
            )

            return ToolResult.success_result(
                "\n".join(lines),
                metadata={
                    "total": total,
                    "in_progress": len(in_progress),
                    "not_started": len(not_started),
                    "completed": completed_count,
                    "progress_percent": progress,
                },
            )

        elif action == "clear":
            count = len(self._todos)
            self._todos.clear()
            return ToolResult.success_result(
                f"🗑️  Cleared {count} todos",
                metadata={"cleared": count},
            )

        else:
            return ToolResult.error_result(
                f"Unknown action: {params.action}. Use: add, start, complete, list, remove, clear"
            )
