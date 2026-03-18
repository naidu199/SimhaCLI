"""Workflow steps for MCP-based operations."""
import logging
from typing import Any, Callable

from tools.workflow.engine import WorkflowStep, WorkflowStepResult, StepStatus

logger = logging.getLogger(__name__)


class MCPToolStep(WorkflowStep):
    """Generic step that calls an MCP tool."""

    def __init__(
        self,
        name: str,
        tool_name: str,
        description: str = "",
        required: bool = True,
        param_mapping: dict[str, str] | None = None,
        static_params: dict[str, Any] | None = None,
    ):
        super().__init__(name, description, required)
        self.tool_name = tool_name
        self.param_mapping = param_mapping or {}
        self.static_params = static_params or {}

    def validate_context(self, context: dict[str, Any]) -> list[str]:
        """Validate that required context keys for param mapping are present."""
        errors = []
        for ctx_key in self.param_mapping.values():
            if ctx_key not in context:
                errors.append(f"Missing context key: {ctx_key}")
        return errors

    def _build_params(self, context: dict[str, Any]) -> dict[str, Any]:
        """Build tool parameters from context using param mapping."""
        params = dict(self.static_params)
        for param_name, ctx_key in self.param_mapping.items():
            if ctx_key in context:
                params[param_name] = context[ctx_key]
        return params

    async def execute(self, context: dict[str, Any]) -> WorkflowStepResult:
        """Execute the MCP tool call."""
        tool_registry = context.get("_tool_registry")
        if not tool_registry:
            return WorkflowStepResult(
                step_name=self.name,
                status=StepStatus.FAILED,
                error="Tool registry not available in context",
            )

        tool = tool_registry.get(self.tool_name)
        if not tool:
            return WorkflowStepResult(
                step_name=self.name,
                status=StepStatus.FAILED,
                error=f"Tool '{self.tool_name}' not found in registry",
            )

        params = self._build_params(context)

        try:
            from tools.base import ToolInvocation
            from pathlib import Path

            invocation = ToolInvocation(
                params=params,
                cwd=context.get("_config", {}).cwd if hasattr(context.get("_config", {}), "cwd") else Path.cwd(),
            )

            result = await tool.execute(invocation)

            if result.error:
                return WorkflowStepResult(
                    step_name=self.name,
                    status=StepStatus.FAILED,
                    error=result.error,
                    output=result.output or "",
                )

            return WorkflowStepResult(
                step_name=self.name,
                status=StepStatus.COMPLETED,
                output=result.output or "",
                metadata=result.metadata or {},
            )

        except Exception as e:
            logger.exception(f"[MCPToolStep] Error executing {self.tool_name}")
            return WorkflowStepResult(
                step_name=self.name,
                status=StepStatus.FAILED,
                error=str(e),
            )


class ShellCommandStep(WorkflowStep):
    """Step that runs a shell command."""

    def __init__(
        self,
        name: str,
        command: str | None = None,
        command_template: str | None = None,
        description: str = "",
        required: bool = True,
    ):
        super().__init__(name, description, required)
        self.command = command
        self.command_template = command_template

    def _build_command(self, context: dict[str, Any]) -> str:
        """Build command string, optionally using template with context."""
        if self.command:
            return self.command
        elif self.command_template:
            return self.command_template.format(**context)
        else:
            raise ValueError("No command or command_template provided")

    async def execute(self, context: dict[str, Any]) -> WorkflowStepResult:
        """Execute the shell command."""
        import subprocess

        try:
            cmd = self._build_command(context)
            logger.info(f"[ShellCommandStep] Running: {cmd}")

            result = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=120,
                cwd=str(context.get("project_path", ".")),
            )

            if result.returncode != 0:
                return WorkflowStepResult(
                    step_name=self.name,
                    status=StepStatus.FAILED,
                    error=f"Command failed with exit code {result.returncode}",
                    output=result.stderr or result.stdout,
                )

            return WorkflowStepResult(
                step_name=self.name,
                status=StepStatus.COMPLETED,
                output=result.stdout,
            )

        except subprocess.TimeoutExpired:
            return WorkflowStepResult(
                step_name=self.name,
                status=StepStatus.FAILED,
                error="Command timed out",
            )
        except Exception as e:
            return WorkflowStepResult(
                step_name=self.name,
                status=StepStatus.FAILED,
                error=str(e),
            )


class ConditionalStep(WorkflowStep):
    """Step that conditionally runs based on context or previous step results."""

    def __init__(
        self,
        name: str,
        condition: Callable[[dict[str, Any]], bool],
        true_step: WorkflowStep,
        false_step: WorkflowStep | None = None,
        description: str = "",
        required: bool = False,
    ):
        super().__init__(name, description, required)
        self.condition = condition
        self.true_step = true_step
        self.false_step = false_step

    async def execute(self, context: dict[str, Any]) -> WorkflowStepResult:
        """Execute the conditional step."""
        try:
            if self.condition(context):
                logger.info(f"[ConditionalStep] Condition true, executing: {self.true_step.name}")
                return await self.true_step.execute(context)
            elif self.false_step:
                logger.info(f"[ConditionalStep] Condition false, executing: {self.false_step.name}")
                return await self.false_step.execute(context)
            else:
                return WorkflowStepResult(
                    step_name=self.name,
                    status=StepStatus.SKIPPED,
                    output="Condition not met, no alternative step",
                )
        except Exception as e:
            return WorkflowStepResult(
                step_name=self.name,
                status=StepStatus.FAILED,
                error=str(e),
            )
