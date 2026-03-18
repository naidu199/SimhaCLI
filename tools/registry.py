from pathlib import Path
from typing import Any

from config.config import Config
from hooks.hook_system import HookSystem
from safety.approval import ApprovalContext, ApprovalDecision, ApprovalManager
from tools.base import Tool, ToolInvocation, ToolResult
import logging
from tools.builtin import ReadFileTool, get_all_builtin_tools
from tools.subagent import SubagentTool, get_default_subagent_definitions

logger = logging.getLogger(__name__)


class ToolRegistry:
    def __init__(self, config: Config) -> None:
        self.config = config
        self._tools: dict[str, Tool] = {}
        self._mcp_tools: dict[str, Tool] = {}

    @property
    def connected_mcp_servers(self) -> list[Tool]:
        return self._mcp_tools.values()

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            logger.warning(f"Overwriting existing tool: {tool.name}")

        self._tools[tool.name] = tool
        logger.debug(f"Registered tool: {tool.name}")

    def register_mcp_tool(self, tool: Tool) -> None:
        self._mcp_tools[tool.name] = tool
        logger.debug(f"Registered MCP tool: {tool.name}")

    def unregister(self, name: str) -> bool:
        if name in self._tools:
            del self._tools[name]
            return True

        return False

    def get(self, name: str) -> Tool | None:
        if name in self._tools:
            return self._tools[name]
        elif name in self._mcp_tools:
            return self._mcp_tools[name]

        return None

    def get_all_registered_tools(self) -> list[Tool]:
        """Return every registered tool regardless of allow/deny filters."""
        tools: list[Tool] = list(self._tools.values()) + list(self._mcp_tools.values())
        return tools

    def get_tools(self) -> list[Tool]:
        tools: list[Tool] = []

        for tool in self._tools.values():
            tools.append(tool)

        for mcp_tool in self._mcp_tools.values():
            tools.append(mcp_tool)

        if self.config.allowed_tools:
            allowed_set = set(self.config.allowed_tools)
            tools = [t for t in tools if t.name in allowed_set]

        if self.config.denied_tools:
            denied_set = set(self.config.denied_tools)
            tools = [t for t in tools if t.name not in denied_set]

        return tools

    def get_schemas(self) -> list[dict[str, Any]]:
        return [tool.to_openai_schema() for tool in self.get_tools()]

    async def invoke(
        self,
        name: str,
        params: dict[str, Any],
        cwd: Path,
        approval_manager: ApprovalManager | None = None,
        hook_system: HookSystem | None = None,
    ) -> ToolResult:
        tool = self.get(name)
        if tool is None:
            result = ToolResult.error_result(
                f"Unknown tool: {name}",
                metadata={"tool_name": name},
            )
            if hook_system:
                await hook_system.trigger_after_tool(name, params, result)
            return result

        validation_errors = tool.validate_params(params)
        if validation_errors:
            result = ToolResult.error_result(
                f"Invalid parameters: {'; '.join(validation_errors)}",
                metadata={
                    "tool_name": name,
                    "validation_errors": validation_errors,
                },
            )

            if hook_system:
                await hook_system.trigger_after_tool(name, params, result)

            return result

        if hook_system:
            await hook_system.trigger_before_tool(name, params)
        invocation = ToolInvocation(
            params=params,
            cwd=cwd,
        )
        if approval_manager:
            confirmation = await tool.get_confirmation(invocation)
            if confirmation:
                context = ApprovalContext(
                    tool_name=name,
                    params=params,
                    is_mutating=tool.is_mutating(params),
                    affected_paths=confirmation.affected_paths,
                    command=confirmation.command,
                    is_dangerous=confirmation.is_dangerous,
                )

                decision = await approval_manager.check_approval(context)
                if decision == ApprovalDecision.REJECTED:
                    result = ToolResult.error_result(
                        "Operation rejected by safety policy"
                    )
                    if hook_system:
                        await hook_system.trigger_after_tool(name, params, result)
                    return result
                elif decision == ApprovalDecision.NEEDS_CONFIRMATION:
                    approved = await approval_manager.request_confirmation(confirmation)

                    if not approved:
                        result = ToolResult.error_result("User rejected the operation")
                        if hook_system:
                            await hook_system.trigger_after_tool(name, params, result)
                        return result

        try:
            result = await tool.execute(invocation)
        except Exception as e:
            logger.exception(f"Tool {name} raised unexpected error")
            result = ToolResult.error_result(
                f"Internal error: {str(e)}",
                metadata={
                    "tool_name": name,
                },
            )

        if hook_system:
            await hook_system.trigger_after_tool(name, params, result)
        return result


def create_default_registry(config: Config) -> ToolRegistry:
    registry = ToolRegistry(config=config)

    for tool_class in get_all_builtin_tools():
        # Special handling for WorkflowTool which needs registry reference
        if tool_class.__name__ == "WorkflowTool":
            registry.register(tool_class(config, registry=registry))
        else:
            registry.register(tool_class(config))

    for subagent_def in get_default_subagent_definitions():
        registry.register(SubagentTool(config, subagent_def))

    return registry
