import asyncio
from typing import Any
from config.config import Config
from tools.base import Tool, ToolInvocation, ToolResult
from dataclasses import dataclass
from pydantic import BaseModel, Field


class SubagentParams(BaseModel):
    goal: str = Field(
        ..., description="The specific task or goal for the subagent to accomplish"
    )


@dataclass
class SubagentDefinition:
    name: str
    description: str
    goal_prompt: str
    allowed_tools: list[str] | None = None
    max_turns: int = 20
    timeout_seconds: float = 600


class SubagentTool(Tool):
    def __init__(self, config: Config, definition: SubagentDefinition):
        super().__init__(config)
        self.definition = definition

    @property
    def name(self) -> str:
        return f"subagent_{self.definition.name}"

    @property
    def description(self) -> str:
        return f"subagent_{self.definition.description}"

    schema = SubagentParams

    def is_mutating(self, params: dict[str, Any]) -> bool:
        return True

    async def execute(self, invocation: ToolInvocation) -> ToolResult:
        # To prevent circular imports
        from agent.agent import Agent
        from agent.events import AgentEventType

        params = SubagentParams(**invocation.params)
        if not params.goal:
            return ToolResult.error_result("No goal specified for sub-agent")

        config_dict = self.config.to_dict()
        config_dict["max_turns"] = self.definition.max_turns
        if self.definition.allowed_tools:
            config_dict["allowed_tools"] = self.definition.allowed_tools

        subagent_config = Config(**config_dict)

        prompt = f"""You are a specialized sub-agent with a specific task to complete.

        {self.definition.goal_prompt}

        YOUR TASK:
        {params.goal}

        IMPORTANT:
        - Focus only on completing the specified task
        - Do not engage in unrelated actions
        - Once you have completed the task or have the answer, provide your final response
        - Be concise and direct in your output
        """

        tool_calls = []
        final_response = None
        error = None
        terminate_response = "goal"

        try:
            async with Agent(subagent_config) as agent:
                deadline = (
                    asyncio.get_event_loop().time() + self.definition.timeout_seconds
                )

                async for event in agent.run(prompt):
                    if asyncio.get_event_loop().time() > deadline:
                        terminate_response = "timeout"
                        final_response = "Sub-agent timed out"
                        break

                    if event.type == AgentEventType.TOOL_CALL_START:
                        tool_calls.append(event.data.get("name"))
                    elif event.type == AgentEventType.TEXT_COMPLETE:
                        final_response = event.data.get("content")
                    elif event.type == AgentEventType.AGENT_END:
                        if final_response is None:
                            final_response = event.data.get("response")
                    elif event.type == AgentEventType.AGENT_ERROR:
                        terminate_response = "error"
                        error = event.data.get("error", "Unknown")
                        final_response = f"Sub-agent error: {error}"
                        break
        except Exception as e:
            terminate_response = "error"
            error = str(e)
            final_response = f"Sub-agent failed: {e}"

        result = f"""Sub-agent '{self.definition.name}' completed.
        Termination: {terminate_response}
        Tools called: {', '.join(tool_calls) if tool_calls else 'None'}

        Result:
        {final_response or 'No response'}
        """

        if error:
            return ToolResult.error_result(result)

        return ToolResult.success_result(result)


CODEBASE_INVESTIGATOR = SubagentDefinition(
    name="codebase_investigator",
    description="Investigates the codebase to answer questions about code structure, patterns, and implementations",
    goal_prompt="""You are a codebase investigation specialist.
Your job is to explore and understand code to answer questions.
Use read_file, grep, glob, and list_dir to investigate.
Do NOT modify any files.""",
    allowed_tools=["read_file", "grep", "glob", "list_dir"],
)

CODE_REVIEWER = SubagentDefinition(
    name="code_reviewer",
    description="Reviews code changes and provides feedback on quality, bugs, and improvements",
    goal_prompt="""You are a code review specialist.
Your job is to review code and provide constructive feedback.
Look for bugs, code smells, security issues, and improvement opportunities.
Use read_file, list_dir and grep to examine the code.
Do NOT modify any files.""",
    allowed_tools=["read_file", "grep", "list_dir"],
    max_turns=10,
    timeout_seconds=300,
)

TEST_GENERATOR = SubagentDefinition(
    name="test_generator",
    description="Generates comprehensive test cases for code files or functions",
    goal_prompt="""You are a test generation specialist.
Your job is to analyze code and create thorough test cases.
Consider edge cases, error conditions, and various input scenarios.
Use read_file and grep to understand the code structure.
Then use write_file to create test files with appropriate test frameworks.""",
    allowed_tools=["read_file", "grep", "glob", "list_dir", "write_file"],
    max_turns=15,
    timeout_seconds=400,
)

DOCUMENTATION_WRITER = SubagentDefinition(
    name="documentation_writer",
    description="Creates or improves documentation for code, APIs, and projects",
    goal_prompt="""You are a documentation specialist.
Your job is to write clear, comprehensive documentation.
Analyze the code to understand its purpose, usage, and behavior.
Create or update documentation that is helpful for developers.
Use read_file, grep, and glob to understand the codebase.
Use write_file or edit_file to create or update documentation.""",
    allowed_tools=["read_file", "grep", "glob", "list_dir", "write_file", "edit_file"],
    max_turns=15,
    timeout_seconds=400,
)

BUG_FIXER = SubagentDefinition(
    name="bug_fixer",
    description="Diagnoses and fixes bugs in the codebase",
    goal_prompt="""You are a bug fixing specialist.
Your job is to identify the root cause of bugs and implement fixes.
First investigate the code to understand the issue.
Then make targeted changes to fix the problem.
Test your changes mentally and ensure they don't introduce new issues.
Use read_file and grep to investigate, then edit_file to fix.""",
    allowed_tools=["read_file", "grep", "glob", "list_dir", "edit_file", "shell"],
    max_turns=20,
    timeout_seconds=500,
)

REFACTORER = SubagentDefinition(
    name="refactorer",
    description="Refactors code to improve quality, readability, and maintainability",
    goal_prompt="""You are a code refactoring specialist.
Your job is to improve code quality without changing functionality.
Look for code smells, duplication, poor naming, and structural issues.
Apply refactoring patterns like Extract Method, Rename, Move, etc.
Ensure the refactored code is cleaner and more maintainable.
Use read_file and grep to analyze, then edit_file to refactor.""",
    allowed_tools=["read_file", "grep", "glob", "list_dir", "edit_file"],
    max_turns=20,
    timeout_seconds=500,
)

DEPENDENCY_ANALYZER = SubagentDefinition(
    name="dependency_analyzer",
    description="Analyzes project dependencies and suggests updates or improvements",
    goal_prompt="""You are a dependency analysis specialist.
Your job is to analyze project dependencies and their usage.
Check for outdated packages, security vulnerabilities, and unused dependencies.
Suggest appropriate updates and improvements.
Use read_file to examine dependency files and grep to find usage patterns.
Do NOT modify files unless specifically asked.""",
    allowed_tools=["read_file", "grep", "glob", "list_dir", "shell"],
    max_turns=12,
    timeout_seconds=350,
)

SECURITY_AUDITOR = SubagentDefinition(
    name="security_auditor",
    description="Performs security audits to identify vulnerabilities and security issues",
    goal_prompt="""You are a security audit specialist.
Your job is to identify security vulnerabilities in the code.
Look for common issues like SQL injection, XSS, insecure dependencies,
hardcoded credentials, insecure configurations, and authentication flaws.
Provide detailed findings with severity levels and remediation advice.
Use read_file, grep, and glob to examine the codebase.
Do NOT modify any files.""",
    allowed_tools=["read_file", "grep", "glob", "list_dir"],
    max_turns=15,
    timeout_seconds=400,
)


def get_default_subagent_definitions() -> list[SubagentDefinition]:
    return [
        CODEBASE_INVESTIGATOR,
        CODE_REVIEWER,
        TEST_GENERATOR,
        DOCUMENTATION_WRITER,
        BUG_FIXER,
        REFACTORER,
        DEPENDENCY_ANALYZER,
        SECURITY_AUDITOR,
    ]
