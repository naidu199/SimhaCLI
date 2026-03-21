import asyncio
from typing import Any
from config.config import Config
from tools.base import Tool, ToolInvocation, ToolResult
from dataclasses import dataclass
from pydantic import BaseModel, Field
from threading import Lock

# Use the shared console from TUI
from ui.tui import get_console


class SubagentStatusManager:
    """Manages parallel subagent status display."""

    _instance = None
    _lock = Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._statuses: dict[str, str] = {}  # {name: last_status}
        self._status_lock = Lock()

    def start(self, name: str):
        """Register a new subagent starting."""
        with self._status_lock:
            self._statuses[name] = "Starting..."
            get_console().print(f"  [cyan]⚡ {name}[/cyan] [dim]Starting...[/dim]")

    def update(self, name: str, status: str, style: str = "dim"):
        """Update a subagent's status."""
        with self._status_lock:
            # Only print if status changed
            if self._statuses.get(name) != status:
                self._statuses[name] = status
                get_console().print(f"  [cyan]⚡ {name}[/cyan] [{style}]{status}[/{style}]")

    def complete(self, name: str, success: bool = True):
        """Mark a subagent as complete."""
        with self._status_lock:
            if success:
                get_console().print(f"  [cyan]⚡ {name}[/cyan] [green]✓ Done[/green]")
            else:
                get_console().print(f"  [cyan]⚡ {name}[/cyan] [red]✗ Failed[/red]")
            if name in self._statuses:
                del self._statuses[name]


# Global status manager instance
status_manager = SubagentStatusManager()


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
        agent_name = self.definition.name

        # Register with shared status manager
        status_manager.start(agent_name)

        try:
            async with Agent(subagent_config) as agent:
                deadline = (
                    asyncio.get_event_loop().time() + self.definition.timeout_seconds
                )

                async for event in agent.run(prompt):
                    if asyncio.get_event_loop().time() > deadline:
                        terminate_response = "timeout"
                        final_response = "Sub-agent timed out"
                        status_manager.update(agent_name, "⏱ Timeout", "yellow")
                        break

                    if event.type == AgentEventType.THINKING_DELTA:
                        status_manager.update(agent_name, "Thinking...", "cyan")
                    elif event.type == AgentEventType.TOOL_CALL_START:
                        tool_name = event.data.get("name", "unknown")
                        tool_calls.append(tool_name)
                        status_manager.update(agent_name, f"→ {tool_name}", "yellow")
                    elif event.type == AgentEventType.TOOL_CALL_COMPLETE:
                        tool_name = event.data.get("name", "unknown")
                        success = event.data.get("success", False)
                        style = "green" if success else "red"
                        mark = "✓" if success else "✗"
                        status_manager.update(agent_name, f"{mark} {tool_name}", style)
                    elif event.type == AgentEventType.TEXT_DELTA:
                        status_manager.update(agent_name, "Writing...", "blue")
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

            status_manager.complete(agent_name, success=(error is None))

        except Exception as e:
            terminate_response = "error"
            error = str(e)
            final_response = f"Sub-agent failed: {e}"
            status_manager.complete(agent_name, success=False)

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

PERFORMANCE_ANALYZER = SubagentDefinition(
    name="performance_analyzer",
    description="Analyzes code performance, identifies bottlenecks, and suggests optimizations",
    goal_prompt="""You are a performance analysis specialist.
Your job is to identify performance bottlenecks in the code.
Look for inefficient algorithms, excessive computations, memory leaks,
poor database queries, and I/O bottlenecks.
Provide detailed analysis with performance metrics and optimization suggestions.
You can use shell commands to run profiling tools or performance benchmarks.
Use read_file, grep, and glob to examine the codebase.
Do NOT modify any files unless running performance tests.""",
    allowed_tools=["read_file", "grep", "glob", "list_dir", "shell"],
    max_turns=15,
    timeout_seconds=400,
)

CI_CD_INTEGRATOR = SubagentDefinition(
    name="ci_cd_integrator",
    description="Sets up and configures CI/CD pipelines (GitHub Actions, GitLab CI, Jenkins, etc.)",
    goal_prompt="""You are a CI/CD integration specialist.
Your job is to help with CI/CD pipeline setup, configuration, and troubleshooting.
Analyze existing pipelines, suggest improvements, and help configure new ones.
Support GitHub Actions, GitLab CI, Jenkins, CircleCI, and other CI/CD platforms.
Use read_file to examine configuration files and write_file or edit_file to create or update them.
Focus on best practices for continuous integration and deployment.""",
    allowed_tools=["read_file", "grep", "glob", "list_dir", "write_file", "edit_file"],
    max_turns=20,
    timeout_seconds=500,
)

DATABASE_EXPERT = SubagentDefinition(
    name="database_expert",
    description="Designs database schemas, optimizes queries, and creates migrations (SQL, NoSQL)",
    goal_prompt="""You are a database specialist.
Your job is to help with database schema design, query optimization, and migrations.
Work with SQL databases (PostgreSQL, MySQL, SQLite) and NoSQL (MongoDB, Redis).
Analyze database schemas, optimize queries, and suggest improvements.
Use read_file to examine database files and write_file or edit_file to create or update them.
Focus on performance, normalization, and data integrity.""",
    allowed_tools=["read_file", "grep", "glob", "list_dir", "write_file", "edit_file"],
    max_turns=18,
    timeout_seconds=450,
)

DEVOPS_ASSISTANT = SubagentDefinition(
    name="devops_assistant",
    description="Helps with infrastructure-as-code, cloud deployments, and DevOps practices",
    goal_prompt="""You are a DevOps specialist.
Your job is to assist with infrastructure-as-code, cloud deployments, and DevOps practices.
Help with configuration management, containerization, orchestration, and monitoring.
Use read_file to examine infrastructure files and write_file to create or update them.
Focus on automation, scalability, and reliability.""",
    allowed_tools=[
        "read_file",
        "grep",
        "glob",
        "list_dir",
        "write_file",
        "edit_file",
        "shell",
    ],
    max_turns=20,
    timeout_seconds=500,
)

AI_ML_SPECIALIST = SubagentDefinition(
    name="ai_ml_specialist",
    description="Develops AI/ML models with TensorFlow, PyTorch, scikit-learn; handles data preprocessing and deployment",
    goal_prompt="""You are an AI/ML specialist.
Your job is to assist with AI/ML model development, training, and deployment.
Work with frameworks like TensorFlow, PyTorch, scikit-learn, and Hugging Face.
Help with data preprocessing, model selection, training, evaluation, and deployment.
Use read_file to examine code and data files, write_file or edit_file to create ML code.
You can use shell to install packages or run training scripts.
Focus on best practices for machine learning and AI development.""",
    allowed_tools=[
        "read_file",
        "grep",
        "glob",
        "list_dir",
        "write_file",
        "edit_file",
        "shell",
    ],
    max_turns=20,
    timeout_seconds=500,
)

FRONTEND_OPTIMIZER = SubagentDefinition(
    name="frontend_optimizer",
    description="Optimizes frontend code for React, Vue, Angular; improves UI/UX and ensures WCAG accessibility",
    goal_prompt="""You are a frontend optimization specialist.
Your job is to optimize frontend code, improve UI/UX, and ensure accessibility compliance.
Work with React, Vue, Angular, and vanilla JavaScript/TypeScript.
Analyze frontend code for performance (bundle size, render optimization), usability, and WCAG accessibility.
Suggest improvements for better user experience and performance.
Use read_file to examine frontend files and edit_file or write_file to create or update them.""",
    allowed_tools=["read_file", "grep", "glob", "list_dir", "write_file", "edit_file"],
    max_turns=18,
    timeout_seconds=450,
)

API_DESIGNER = SubagentDefinition(
    name="api_designer",
    description="Assists in designing RESTful, GraphQL, or gRPC APIs with best practices",
    goal_prompt="""You are an API design specialist.
Your job is to assist in designing RESTful, GraphQL, or gRPC APIs with best practices.
Help with API structure, endpoints, request/response formats, and documentation.
Use read_file to examine existing APIs and write_file to create or update API specifications.
Focus on consistency, usability, and scalability.""",
    allowed_tools=["read_file", "grep", "glob", "list_dir", "write_file", "edit_file"],
    max_turns=18,
    timeout_seconds=450,
)

LOCALIZATION_EXPERT = SubagentDefinition(
    name="localization_expert",
    description="Manages localization and internationalization (i18n) for applications",
    goal_prompt="""You are a localization specialist.
Your job is to manage localization and internationalization (i18n) for applications.
Help with string extraction, translation management, and locale-specific formatting.
Use read_file to examine code and write_file to create or update localization files.
Focus on supporting multiple languages and regions effectively.""",
    allowed_tools=["read_file", "grep", "glob", "list_dir", "write_file", "edit_file"],
    max_turns=18,
    timeout_seconds=450,
)

LEGACY_CODE_MODERNIZER = SubagentDefinition(
    name="legacy_code_modernizer",
    description="Helps modernize legacy codebases and migrate to newer technologies",
    goal_prompt="""You are a legacy code modernization specialist.
Your job is to help modernize legacy codebases and migrate to newer technologies.
Analyze legacy code, suggest modernization strategies, and implement migrations.
Use read_file to examine legacy code and edit_file to modernize it.
Focus on maintaining functionality while improving maintainability and performance.""",
    allowed_tools=["read_file", "grep", "glob", "list_dir", "edit_file", "write_file"],
    max_turns=20,
    timeout_seconds=500,
)

MOBILE_DEVELOPMENT_ASSISTANT = SubagentDefinition(
    name="mobile_development_assistant",
    description="Develops mobile apps for iOS (Swift/SwiftUI) and Android (Kotlin/Jetpack Compose), React Native, Flutter",
    goal_prompt="""You are a mobile development specialist.
Your job is to assist with mobile app development for iOS and Android.
Work with native platforms (Swift/SwiftUI, Kotlin/Jetpack Compose) and cross-platform (React Native, Flutter).
Help with platform-specific code, UI/UX design, and performance optimization.
Use read_file to examine mobile app code and edit_file or write_file to create or update it.
Focus on platform-specific best practices and user experience.""",
    allowed_tools=["read_file", "grep", "glob", "list_dir", "write_file", "edit_file"],
    max_turns=20,
    timeout_seconds=500,
)


def get_default_subagent_definitions() -> list[SubagentDefinition]:
    """Return a focused set of subagent definitions.

    Keeping the list small (5 subagents) improves compatibility with smaller
    models that struggle when too many tools are registered. Additional
    specialized subagents (SECURITY_AUDITOR, PERFORMANCE_ANALYZER, CI_CD_INTEGRATOR,
    DATABASE_EXPERT, DEVOPS_ASSISTANT, AI_ML_SPECIALIST, FRONTEND_OPTIMIZER,
    API_DESIGNER, LOCALIZATION_EXPERT, LEGACY_CODE_MODERNIZER,
    MOBILE_DEVELOPMENT_ASSISTANT, DEPENDENCY_ANALYZER) are still defined above
    and can be registered manually via ToolRegistry.register() when needed.
    """
    return [
        CODEBASE_INVESTIGATOR,
        CODE_REVIEWER,
        TEST_GENERATOR,
        BUG_FIXER,
        REFACTORER,
    ]
