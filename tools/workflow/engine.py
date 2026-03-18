"""Workflow engine for orchestrating end-to-end development tasks."""
import asyncio
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

logger = logging.getLogger(__name__)


class WorkflowStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class StepStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class WorkflowStepResult:
    """Result of a single workflow step."""
    step_name: str
    status: StepStatus
    output: str = ""
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class WorkflowResult:
    """Result of a complete workflow execution."""
    workflow_name: str
    status: WorkflowStatus
    steps: list[WorkflowStepResult] = field(default_factory=list)
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def success(self) -> bool:
        return self.status == WorkflowStatus.COMPLETED

    @property
    def failed_steps(self) -> list[WorkflowStepResult]:
        return [s for s in self.steps if s.status == StepStatus.FAILED]

    @property
    def completed_steps(self) -> list[WorkflowStepResult]:
        return [s for s in self.steps if s.status == StepStatus.COMPLETED]


class WorkflowStep(ABC):
    """Base class for a workflow step."""

    def __init__(self, name: str, description: str = "", required: bool = True):
        self.name = name
        self.description = description
        self.required = required

    @abstractmethod
    async def execute(self, context: dict[str, Any]) -> WorkflowStepResult:
        """Execute the step with the given context."""
        pass

    def validate_context(self, context: dict[str, Any]) -> list[str]:
        """Validate that required context keys are present. Returns list of errors."""
        return []


class Workflow:
    """A workflow that orchestrates multiple steps."""

    def __init__(
        self,
        name: str,
        description: str = "",
        steps: list[WorkflowStep] | None = None,
    ):
        self.name = name
        self.description = description
        self.steps: list[WorkflowStep] = steps or []
        self._context: dict[str, Any] = {}

    def add_step(self, step: WorkflowStep) -> "Workflow":
        """Add a step to the workflow."""
        self.steps.append(step)
        return self

    def set_context(self, **kwargs) -> "Workflow":
        """Set context values for the workflow."""
        self._context.update(kwargs)
        return self

    async def execute(self, context: dict[str, Any] | None = None) -> WorkflowResult:
        """Execute all steps in the workflow."""
        ctx = {**self._context}
        if context:
            ctx.update(context)

        result = WorkflowResult(
            workflow_name=self.name,
            status=WorkflowStatus.RUNNING,
        )

        logger.info(f"[Workflow] Starting workflow: {self.name}")

        for step in self.steps:
            # Validate context for this step
            validation_errors = step.validate_context(ctx)
            if validation_errors:
                if step.required:
                    result.steps.append(WorkflowStepResult(
                        step_name=step.name,
                        status=StepStatus.FAILED,
                        error=f"Context validation failed: {'; '.join(validation_errors)}",
                    ))
                    result.status = WorkflowStatus.FAILED
                    result.error = f"Required step '{step.name}' failed validation"
                    logger.error(f"[Workflow] Step '{step.name}' validation failed: {validation_errors}")
                    return result
                else:
                    result.steps.append(WorkflowStepResult(
                        step_name=step.name,
                        status=StepStatus.SKIPPED,
                        output=f"Skipped: {'; '.join(validation_errors)}",
                    ))
                    logger.info(f"[Workflow] Optional step '{step.name}' skipped due to validation")
                    continue

            # Execute the step
            logger.info(f"[Workflow] Executing step: {step.name}")
            try:
                step_result = await step.execute(ctx)
                result.steps.append(step_result)

                # Update context with step output
                if step_result.metadata:
                    ctx.update(step_result.metadata)

                if step_result.status == StepStatus.FAILED:
                    if step.required:
                        result.status = WorkflowStatus.FAILED
                        result.error = f"Required step '{step.name}' failed: {step_result.error}"
                        logger.error(f"[Workflow] Step '{step.name}' failed: {step_result.error}")
                        return result
                    else:
                        logger.warning(f"[Workflow] Optional step '{step.name}' failed: {step_result.error}")

                elif step_result.status == StepStatus.COMPLETED:
                    logger.info(f"[Workflow] Step '{step.name}' completed successfully")

            except Exception as e:
                error_result = WorkflowStepResult(
                    step_name=step.name,
                    status=StepStatus.FAILED,
                    error=str(e),
                )
                result.steps.append(error_result)

                if step.required:
                    result.status = WorkflowStatus.FAILED
                    result.error = f"Required step '{step.name}' raised exception: {e}"
                    logger.exception(f"[Workflow] Step '{step.name}' raised exception")
                    return result
                else:
                    logger.warning(f"[Workflow] Optional step '{step.name}' raised exception: {e}")

        result.status = WorkflowStatus.COMPLETED
        logger.info(f"[Workflow] Workflow '{self.name}' completed successfully")
        return result


class WorkflowEngine:
    """Engine for managing and executing workflows."""

    def __init__(self, tool_registry=None, config=None):
        self._workflows: dict[str, Workflow] = {}
        self._tool_registry = tool_registry
        self._config = config

    def register_workflow(self, workflow: Workflow) -> None:
        """Register a workflow."""
        self._workflows[workflow.name] = workflow
        logger.info(f"[WorkflowEngine] Registered workflow: {workflow.name}")

    def get_workflow(self, name: str) -> Workflow | None:
        """Get a workflow by name."""
        return self._workflows.get(name)

    def list_workflows(self) -> list[dict[str, str]]:
        """List all registered workflows."""
        return [
            {"name": w.name, "description": w.description}
            for w in self._workflows.values()
        ]

    async def execute_workflow(
        self,
        name: str,
        context: dict[str, Any] | None = None,
    ) -> WorkflowResult:
        """Execute a workflow by name."""
        workflow = self.get_workflow(name)
        if not workflow:
            return WorkflowResult(
                workflow_name=name,
                status=WorkflowStatus.FAILED,
                error=f"Workflow '{name}' not found",
            )

        # Add engine context
        ctx = context or {}
        ctx["_engine"] = self
        ctx["_tool_registry"] = self._tool_registry
        ctx["_config"] = self._config

        return await workflow.execute(ctx)
