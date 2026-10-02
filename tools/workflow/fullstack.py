"""Full-stack development workflows."""

import asyncio
import logging
import re
import subprocess
from pathlib import Path
from typing import Any

from tools.workflow.engine import Workflow, WorkflowStep, WorkflowStepResult, StepStatus
from tools.workflow.steps import MCPToolStep, ShellCommandStep

logger = logging.getLogger(__name__)

# Default timeout (seconds) for git invocations
GIT_TIMEOUT = 60

# Safe PostgreSQL identifier (unquoted-style) for CREATE DATABASE
_DB_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _base_cwd(context: dict[str, Any]) -> Path:
    """Directory the workflow was invoked from (falls back to config cwd)."""
    base = context.get("_cwd")
    if base:
        return Path(base)
    config = context.get("_config")
    if config is not None and getattr(config, "cwd", None):
        return Path(config.cwd)
    return Path.cwd()


def _resolve_project_path(context: dict[str, Any], default: str = ".") -> str:
    """Resolve project_path against the invocation cwd, not the process cwd."""
    path = Path(str(context.get("project_path") or default)).expanduser()
    if not path.is_absolute():
        path = _base_cwd(context) / path
    return str(path)


async def _run(
    cmd: list[str] | str,
    cwd: str,
    timeout: float = GIT_TIMEOUT,
    shell: bool = False,
) -> subprocess.CompletedProcess:
    """Run a subprocess without blocking the event loop."""
    return await asyncio.to_thread(
        subprocess.run,
        cmd,
        shell=shell,
        capture_output=True,
        text=True,
        cwd=cwd,
        timeout=timeout,
    )


def _is_option_like(value: str) -> bool:
    """True if a value would be parsed by git as a command-line option."""
    return str(value).startswith("-")


def _parse_env_key(line: str) -> str | None:
    """Return the variable name of a KEY=VALUE .env line, or None."""
    stripped = line.strip()
    if not stripped or stripped.startswith("#") or "=" not in stripped:
        return None
    if stripped.startswith("export "):
        stripped = stripped[len("export ") :]
    key = stripped.partition("=")[0].strip()
    return key or None


def _format_env_line(key: str, value: Any) -> str:
    """Format a .env assignment, double-quoted with escaping."""
    text = "" if value is None else str(value)
    text = (
        text.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
    )
    return f'{key}="{text}"'


def _ensure_gitignored(project_path: str, entry: str) -> None:
    """Append `entry` to <project>/.gitignore unless it is already ignored."""
    gitignore = Path(project_path) / ".gitignore"
    content = ""
    if gitignore.exists():
        content = gitignore.read_text(encoding="utf-8")
        existing = {line.strip() for line in content.splitlines()}
        if {entry, f"/{entry}", f"{entry}*", f"/{entry}*"} & existing:
            return
    with open(gitignore, "a", encoding="utf-8") as f:
        if content and not content.endswith("\n"):
            f.write("\n")
        f.write(f"{entry}\n")


class CreateGitHubRepoStep(WorkflowStep):
    """Step to create a GitHub repository."""

    def __init__(self, name: str = "create_github_repo", required: bool = True):
        super().__init__(
            name=name,
            description="Create a new GitHub repository",
            required=required,
        )

    def validate_context(self, context: dict[str, Any]) -> list[str]:
        errors = []
        if "repo_name" not in context:
            errors.append("Missing 'repo_name' in context")
        return errors

    async def execute(self, context: dict[str, Any]) -> WorkflowStepResult:
        tool_registry = context.get("_tool_registry")
        if not tool_registry:
            return WorkflowStepResult(
                step_name=self.name,
                status=StepStatus.FAILED,
                error="Tool registry not available",
            )

        # Look for GitHub MCP tools
        github_tools = [
            name for name in tool_registry._mcp_tools.keys() if "github" in name.lower()
        ]

        if not github_tools:
            # Try with different naming patterns
            github_tools = [
                name
                for name in tool_registry._mcp_tools.keys()
                if "git" in name.lower()
            ]

        if not github_tools:
            return WorkflowStepResult(
                step_name=self.name,
                status=StepStatus.FAILED,
                error="""GitHub repository creation failed - no GitHub MCP connected.

Set up GitHub MCP (recommended):
1. Create a Personal Access Token at: https://github.com/settings/tokens
   - Select scopes: repo, workflow, gist
2. Add to .simhacli/config.toml (file is gitignored, keys are safe):

[mcp_servers.github]
command = "npx"
args = ["-y", "@modelcontextprotocol/server-github"]
env = { GITHUB_PERSONAL_ACCESS_TOKEN = "ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx" }

3. Restart SimhaCLI

Manual alternative (if MCP not available):
  git init && git remote add origin https://github.com/USERNAME/REPO.git
  git add -A && git commit -m "Initial commit"
  git push -u origin main""",
            )

        # Find the create repository tool
        create_repo_tool = None
        for tool_name in github_tools:
            if "create" in tool_name.lower() and "repo" in tool_name.lower():
                create_repo_tool = tool_name
                break

        if not create_repo_tool:
            # Try to find any tool that might create repos
            for tool_name in github_tools:
                tool = tool_registry.get(tool_name)
                if tool and "create" in tool.description.lower():
                    create_repo_tool = tool_name
                    break

        if not create_repo_tool:
            return WorkflowStepResult(
                step_name=self.name,
                status=StepStatus.FAILED,
                error="Could not find a GitHub repository creation tool",
            )

        try:
            from tools.base import ToolInvocation
            from pathlib import Path

            params = {
                "name": context["repo_name"],
                "description": context.get("repo_description", ""),
                "private": context.get("repo_private", False),
                "auto_init": context.get("repo_auto_init", True),
            }

            tool = tool_registry.get(create_repo_tool)
            invocation = ToolInvocation(
                params=params,
                cwd=(
                    context.get("_config", {}).cwd
                    if hasattr(context.get("_config", {}), "cwd")
                    else Path.cwd()
                ),
            )

            result = await tool.execute(invocation)

            if result.error:
                return WorkflowStepResult(
                    step_name=self.name,
                    status=StepStatus.FAILED,
                    error=result.error,
                    output=result.output or "",
                )

            # Store repo info in context metadata
            metadata = {
                "github_repo_name": context["repo_name"],
                "github_repo_created": True,
            }

            # Try to extract clone URL from output
            output = result.output or ""
            if "clone_url" in output.lower() or "https://" in output:
                # Try to extract the URL
                import re

                url_match = re.search(r'https://github\.com/[^\s"]+', output)
                if url_match:
                    metadata["github_clone_url"] = url_match.group(0)

            return WorkflowStepResult(
                step_name=self.name,
                status=StepStatus.COMPLETED,
                output=output,
                metadata=metadata,
            )

        except Exception as e:
            logger.exception(f"[CreateGitHubRepoStep] Error: {e}")
            return WorkflowStepResult(
                step_name=self.name,
                status=StepStatus.FAILED,
                error=str(e),
            )


class SetupDatabaseStep(WorkflowStep):
    """Step to set up a database using PostgreSQL MCP or Supabase MCP."""

    def __init__(self, name: str = "setup_database", required: bool = True):
        super().__init__(
            name=name,
            description="Set up PostgreSQL or Supabase database",
            required=required,
        )

    def validate_context(self, context: dict[str, Any]) -> list[str]:
        errors = []
        if "db_name" not in context:
            errors.append("Missing 'db_name' in context")
        return errors

    async def execute(self, context: dict[str, Any]) -> WorkflowStepResult:
        tool_registry = context.get("_tool_registry")
        if not tool_registry:
            return WorkflowStepResult(
                step_name=self.name,
                status=StepStatus.FAILED,
                error="Tool registry not available",
            )

        # Look for Supabase MCP tools (priority)
        supabase_tools = [
            name
            for name in tool_registry._mcp_tools.keys()
            if "supabase" in name.lower()
        ]

        # Look for PostgreSQL MCP tools
        pg_tools = [
            name
            for name in tool_registry._mcp_tools.keys()
            if "postgres" in name.lower()
            or "sql" in name.lower()
            or "database" in name.lower()
        ]

        # Prefer Supabase if available
        if supabase_tools:
            return await self._execute_supabase(context, supabase_tools)
        elif pg_tools:
            return await self._execute_postgres(context, pg_tools)
        else:
            return WorkflowStepResult(
                step_name=self.name,
                status=StepStatus.FAILED,
                error="""Database setup failed - no database MCP connected.

Set up PostgreSQL MCP (recommended):
1. Get your PostgreSQL connection string
2. Add to .simhacli/config.toml (file is gitignored, keys are safe):

[mcp_servers.postgresql]
command = "npx"
args = ["-y", "@modelcontextprotocol/server-postgres"]
env = { DATABASE_URL = "postgresql://postgres:password@db.abcdef.supabase.co:5432/postgres" }

Or set up Supabase MCP:
1. Get project ref and keys from: https://supabase.com/dashboard
2. Add to .simhacli/config.toml (file is gitignored, keys are safe):

[mcp_servers.supabase]
command = "npx"
args = [
  "-y",
  "@supabase/mcp-server-supabase",
  "--access-token", "sbp_xxxxxxxxxxxx",
  "--project-ref", "abcdefghijklmnop"
]

3. Restart SimhaCLI

Manual alternative (if MCP not available):
  psql "postgresql://user:pass@host:5432/dbname" -c "CREATE DATABASE mydb;\"""",
            )

    async def _execute_supabase(
        self, context: dict[str, Any], supabase_tools: list[str]
    ) -> WorkflowStepResult:
        """Execute database setup using Supabase MCP tools."""
        from tools.base import ToolInvocation
        from pathlib import Path

        db_name = context["db_name"]
        db_schema = context.get("db_schema", None)

        # Find appropriate Supabase tools
        query_tool = None
        project_tool = None
        migration_tool = None

        for tool_name in supabase_tools:
            tool = context.get("_tool_registry").get(tool_name)
            if not tool:
                continue
            desc = tool.description.lower()
            if "query" in desc or "execute" in desc or "run" in desc:
                query_tool = tool_name
            elif "project" in desc and ("create" in desc or "manage" in desc):
                project_tool = tool_name
            elif "migration" in desc:
                migration_tool = tool_name

        try:
            tool_registry = context.get("_tool_registry")
            metadata = {
                "db_name": db_name,
                "db_provider": "supabase",
                "db_created": True,
            }

            # If we have a migration tool and schema, use it
            if db_schema and migration_tool:
                tool = tool_registry.get(migration_tool)
                invocation = ToolInvocation(
                    params={"query": db_schema, "project_ref": db_name},
                    cwd=(
                        context.get("_config", {}).cwd
                        if hasattr(context.get("_config", {}), "cwd")
                        else Path.cwd()
                    ),
                )
                result = await tool.execute(invocation)
                metadata["db_schema_applied"] = True
            elif db_schema and query_tool:
                # Use query tool for schema
                tool = tool_registry.get(query_tool)
                invocation = ToolInvocation(
                    params={"query": db_schema, "project_ref": db_name},
                    cwd=(
                        context.get("_config", {}).cwd
                        if hasattr(context.get("_config", {}), "cwd")
                        else Path.cwd()
                    ),
                )
                result = await tool.execute(invocation)
                metadata["db_schema_applied"] = True
            elif project_tool:
                # Create project if tool available
                tool = tool_registry.get(project_tool)
                invocation = ToolInvocation(
                    params={"name": db_name},
                    cwd=(
                        context.get("_config", {}).cwd
                        if hasattr(context.get("_config", {}), "cwd")
                        else Path.cwd()
                    ),
                )
                result = await tool.execute(invocation)
            else:
                # Use first available tool with best effort
                tool_name = supabase_tools[0]
                tool = tool_registry.get(tool_name)
                params = {"query": db_schema} if db_schema else {}
                invocation = ToolInvocation(
                    params=params,
                    cwd=(
                        context.get("_config", {}).cwd
                        if hasattr(context.get("_config", {}), "cwd")
                        else Path.cwd()
                    ),
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
                output=result.output
                or f"Supabase project '{db_name}' configured successfully",
                metadata=metadata,
            )

        except Exception as e:
            logger.exception(f"[SetupDatabaseStep/Supabase] Error: {e}")
            return WorkflowStepResult(
                step_name=self.name,
                status=StepStatus.FAILED,
                error=str(e),
            )

    async def _execute_postgres(
        self, context: dict[str, Any], pg_tools: list[str]
    ) -> WorkflowStepResult:
        """Execute database setup using PostgreSQL MCP tools."""
        from tools.base import ToolInvocation
        from pathlib import Path

        db_name = context["db_name"]
        db_schema = context.get("db_schema", None)

        if not isinstance(db_name, str) or not _DB_NAME_RE.match(db_name):
            return WorkflowStepResult(
                step_name=self.name,
                status=StepStatus.FAILED,
                error=(
                    f"Invalid database name {db_name!r}: must match "
                    "^[A-Za-z_][A-Za-z0-9_]*$"
                ),
            )

        # Find a tool that can create databases or run queries
        create_db_tool = None
        query_tool = None

        for tool_name in pg_tools:
            tool = context.get("_tool_registry").get(tool_name)
            if not tool:
                continue
            desc = tool.description.lower()
            if "create" in desc and "database" in desc:
                create_db_tool = tool_name
            elif "query" in desc or "execute" in desc or "run" in desc:
                query_tool = tool_name

        try:
            tool_registry = context.get("_tool_registry")

            if create_db_tool:
                tool = tool_registry.get(create_db_tool)
                invocation = ToolInvocation(
                    params={"database": db_name},
                    cwd=(
                        context.get("_config", {}).cwd
                        if hasattr(context.get("_config", {}), "cwd")
                        else Path.cwd()
                    ),
                )
                result = await tool.execute(invocation)
            elif query_tool:
                tool = tool_registry.get(query_tool)
                create_sql = f'CREATE DATABASE "{db_name}";'
                invocation = ToolInvocation(
                    params={"query": create_sql},
                    cwd=(
                        context.get("_config", {}).cwd
                        if hasattr(context.get("_config", {}), "cwd")
                        else Path.cwd()
                    ),
                )
                result = await tool.execute(invocation)
            else:
                return WorkflowStepResult(
                    step_name=self.name,
                    status=StepStatus.FAILED,
                    error="No suitable PostgreSQL tool found for database creation",
                )

            # Check CREATE DATABASE result before applying any schema
            if result.error:
                return WorkflowStepResult(
                    step_name=self.name,
                    status=StepStatus.FAILED,
                    error=result.error,
                    output=result.output or "",
                )

            metadata = {
                "db_name": db_name,
                "db_provider": "postgresql",
                "db_created": True,
            }

            # If schema provided, create tables
            if db_schema and query_tool:
                tool = tool_registry.get(query_tool)
                invocation = ToolInvocation(
                    params={"query": db_schema},
                    cwd=(
                        context.get("_config", {}).cwd
                        if hasattr(context.get("_config", {}), "cwd")
                        else Path.cwd()
                    ),
                )
                schema_result = await tool.execute(invocation)
                if schema_result.error:
                    return WorkflowStepResult(
                        step_name=self.name,
                        status=StepStatus.FAILED,
                        error=f"Schema creation failed: {schema_result.error}",
                        output=f"Database '{db_name}' created, but schema was not applied",
                        metadata=metadata,
                    )
                metadata["db_schema_applied"] = True

            return WorkflowStepResult(
                step_name=self.name,
                status=StepStatus.COMPLETED,
                output=result.output or f"Database '{db_name}' created successfully",
                metadata=metadata,
            )

        except Exception as e:
            logger.exception(f"[SetupDatabaseStep/Postgres] Error: {e}")
            return WorkflowStepResult(
                step_name=self.name,
                status=StepStatus.FAILED,
                error=str(e),
            )


class DeployToVercelStep(WorkflowStep):
    """Step to deploy to Vercel."""

    def __init__(self, name: str = "deploy_vercel", required: bool = True):
        super().__init__(
            name=name,
            description="Deploy application to Vercel",
            required=required,
        )

    def validate_context(self, context: dict[str, Any]) -> list[str]:
        errors = []
        if "project_path" not in context:
            errors.append("Missing 'project_path' in context")
        return errors

    async def execute(self, context: dict[str, Any]) -> WorkflowStepResult:
        tool_registry = context.get("_tool_registry")
        if not tool_registry:
            return WorkflowStepResult(
                step_name=self.name,
                status=StepStatus.FAILED,
                error="Tool registry not available",
            )

        # Look for Vercel MCP tools
        vercel_tools = [
            name for name in tool_registry._mcp_tools.keys() if "vercel" in name.lower()
        ]

        if not vercel_tools:
            # Fallback to shell command
            return await self._deploy_with_shell(context)

        # Find deployment tool
        deploy_tool = None
        for tool_name in vercel_tools:
            tool = tool_registry.get(tool_name)
            if not tool:
                continue
            desc = tool.description.lower()
            if "deploy" in desc or "create" in desc:
                deploy_tool = tool_name
                break

        if not deploy_tool:
            return await self._deploy_with_shell(context)

        try:
            from tools.base import ToolInvocation
            from pathlib import Path

            project_path = _resolve_project_path(context)
            project_name = context.get("project_name", None)

            params = {
                "path": project_path,
            }
            if project_name:
                params["name"] = project_name

            tool = tool_registry.get(deploy_tool)
            invocation = ToolInvocation(
                params=params,
                cwd=(
                    context.get("_config", {}).cwd
                    if hasattr(context.get("_config", {}), "cwd")
                    else Path.cwd()
                ),
            )

            result = await tool.execute(invocation)

            if result.error:
                return WorkflowStepResult(
                    step_name=self.name,
                    status=StepStatus.FAILED,
                    error=result.error,
                    output=result.output or "",
                )

            metadata = {
                "vercel_deployed": True,
                "deploy_path": project_path,
            }

            # Try to extract deployment URL
            output = result.output or ""
            import re

            url_match = re.search(r"https://[a-z0-9-]+\.vercel\.app", output)
            if url_match:
                metadata["vercel_url"] = url_match.group(0)

            return WorkflowStepResult(
                step_name=self.name,
                status=StepStatus.COMPLETED,
                output=output,
                metadata=metadata,
            )

        except Exception as e:
            logger.exception(f"[DeployToVercelStep] Error: {e}")
            return WorkflowStepResult(
                step_name=self.name,
                status=StepStatus.FAILED,
                error=str(e),
            )

    async def _deploy_with_shell(self, context: dict[str, Any]) -> WorkflowStepResult:
        """Fallback deployment using vercel CLI."""
        project_path = _resolve_project_path(context)

        try:
            # Check if vercel CLI is installed (constant command; shell=True so
            # the vercel.cmd shim resolves on Windows)
            check = await _run(
                "vercel --version", cwd=project_path, timeout=60, shell=True
            )

            if check.returncode != 0:
                return WorkflowStepResult(
                    step_name=self.name,
                    status=StepStatus.FAILED,
                    error="""Vercel CLI not found. Install and login to deploy:

1. npm install -g vercel
2. vercel login (provide your token when prompted)
3. vercel --yes""",
                )

            # Deploy
            result = await _run("vercel --yes", cwd=project_path, timeout=300, shell=True)

            if result.returncode != 0:
                return WorkflowStepResult(
                    step_name=self.name,
                    status=StepStatus.FAILED,
                    error=f"Deployment failed: {result.stderr}",
                    output=result.stdout,
                )

            metadata = {
                "vercel_deployed": True,
                "deploy_path": project_path,
            }

            # Extract URL
            import re

            url_match = re.search(r"https://[a-z0-9-]+\.vercel\.app", result.stdout)
            if url_match:
                metadata["vercel_url"] = url_match.group(0)

            return WorkflowStepResult(
                step_name=self.name,
                status=StepStatus.COMPLETED,
                output=result.stdout,
                metadata=metadata,
            )

        except subprocess.TimeoutExpired:
            return WorkflowStepResult(
                step_name=self.name,
                status=StepStatus.FAILED,
                error="Deployment timed out",
            )
        except Exception as e:
            return WorkflowStepResult(
                step_name=self.name,
                status=StepStatus.FAILED,
                error=str(e),
            )


class RunTestsStep(WorkflowStep):
    """Step to run tests using Playwright MCP."""

    def __init__(self, name: str = "run_tests", required: bool = False):
        super().__init__(
            name=name,
            description="Run end-to-end tests with Playwright",
            required=required,
        )

    def validate_context(self, context: dict[str, Any]) -> list[str]:
        errors = []
        if "test_url" not in context and "vercel_url" not in context:
            errors.append("Missing 'test_url' or 'vercel_url' in context")
        return errors

    async def execute(self, context: dict[str, Any]) -> WorkflowStepResult:
        tool_registry = context.get("_tool_registry")
        if not tool_registry:
            return WorkflowStepResult(
                step_name=self.name,
                status=StepStatus.FAILED,
                error="Tool registry not available",
            )

        # Look for Playwright MCP tools
        playwright_tools = [
            name
            for name in tool_registry._mcp_tools.keys()
            if "playwright" in name.lower() or "browser" in name.lower()
        ]

        if not playwright_tools:
            return WorkflowStepResult(
                step_name=self.name,
                status=StepStatus.SKIPPED,
                output="""Playwright MCP server not connected. Tests skipped.

To enable E2E testing, set up Playwright MCP in .simhacli/config.toml:

[mcp_servers.playwright]
command = "npx"
args = ["-y", "@playwright/mcp"]

Restart SimhaCLI after configuring.

Manual alternative:
  npm i -g @playwright/mcp && npx @playwright/mcp""",
            )

        test_url = context.get("test_url") or context.get("vercel_url")
        test_scenarios = context.get("test_scenarios", [])

        if not test_scenarios:
            # Default basic tests
            test_scenarios = [
                {"name": "page_loads", "action": "goto", "url": test_url},
                {"name": "title_check", "action": "get_title"},
            ]

        results = []
        all_passed = True

        try:
            from tools.base import ToolInvocation
            from pathlib import Path

            for scenario in test_scenarios:
                scenario_name = scenario.get("name", "unnamed")
                action = scenario.get("action", "goto")

                # Find appropriate tool
                tool_name = None
                for name in playwright_tools:
                    if (
                        action in name.lower()
                        or "navigate" in name.lower()
                        or "goto" in name.lower()
                    ):
                        tool_name = name
                        break

                if not tool_name:
                    tool_name = playwright_tools[0]  # Use first available

                tool = tool_registry.get(tool_name)
                if not tool:
                    continue

                params = {}
                if action == "goto":
                    params["url"] = scenario.get("url", test_url)
                elif action == "get_title":
                    params = {}
                elif action == "screenshot":
                    params["path"] = scenario.get("path", "test_screenshot.png")
                elif action == "click":
                    params["selector"] = scenario.get("selector", "")

                invocation = ToolInvocation(
                    params=params,
                    cwd=(
                        context.get("_config", {}).cwd
                        if hasattr(context.get("_config", {}), "cwd")
                        else Path.cwd()
                    ),
                )

                result = await tool.execute(invocation)

                if result.error:
                    all_passed = False
                    results.append(f"❌ {scenario_name}: {result.error}")
                else:
                    results.append(f"✅ {scenario_name}: {result.output or 'Passed'}")

            metadata = {
                "tests_run": len(test_scenarios),
                "tests_passed": all_passed,
                "test_url": test_url,
            }

            output = "\n".join(results)

            return WorkflowStepResult(
                step_name=self.name,
                status=StepStatus.COMPLETED if all_passed else StepStatus.FAILED,
                output=output,
                metadata=metadata,
                error=None if all_passed else "Some tests failed",
            )

        except Exception as e:
            logger.exception(f"[RunTestsStep] Error: {e}")
            return WorkflowStepResult(
                step_name=self.name,
                status=StepStatus.FAILED,
                error=str(e),
            )


class PushToGitHubStep(WorkflowStep):
    """Step to commit and push code changes to GitHub."""

    def __init__(self, name: str = "push_to_github", required: bool = True):
        super().__init__(
            name=name,
            description="Commit and push code changes to GitHub repository",
            required=required,
        )

    def validate_context(self, context: dict[str, Any]) -> list[str]:
        errors = []
        if "commit_message" not in context and "repo_name" not in context:
            errors.append("Missing 'commit_message' or 'repo_name' in context")
        return errors

    async def execute(self, context: dict[str, Any]) -> WorkflowStepResult:
        repo_path = _resolve_project_path(context)
        commit_message = str(context.get("commit_message") or "Update via SimhaCLI")
        files = context.get("files") or []  # Specific files to add, or all if empty
        if isinstance(files, str):
            files = [files]
        branch = context.get("branch")  # Default: current branch (resolved below)
        remote = str(context.get("remote") or "origin")

        # Values are passed as argv (no shell), but still must not be parsed
        # as git options.
        for label, value in (("remote", remote), ("branch", branch)):
            if value and _is_option_like(value):
                return WorkflowStepResult(
                    step_name=self.name,
                    status=StepStatus.FAILED,
                    error=f"Invalid {label}: {value!r}",
                )

        try:
            # Check if it's a git repo
            check_result = await _run(
                ["git", "rev-parse", "--is-inside-work-tree"], cwd=repo_path
            )

            if check_result.returncode != 0:
                # Try to initialize
                init_result = await _run(["git", "init"], cwd=repo_path)
                if init_result.returncode != 0:
                    return WorkflowStepResult(
                        step_name=self.name,
                        status=StepStatus.FAILED,
                        error=f"Failed to initialize git repo: {init_result.stderr}",
                    )

            # Add files
            if files:
                for file in files:
                    add_result = await _run(
                        ["git", "add", "--", str(file)], cwd=repo_path
                    )
                    if add_result.returncode != 0:
                        return WorkflowStepResult(
                            step_name=self.name,
                            status=StepStatus.FAILED,
                            error=f"Failed to add file '{file}': {add_result.stderr}",
                        )
            else:
                # Add all changes under the project directory only (avoid
                # staging unrelated files when nested inside a parent repo)
                add_result = await _run(["git", "add", "-A", "--", "."], cwd=repo_path)
                if add_result.returncode != 0:
                    return WorkflowStepResult(
                        step_name=self.name,
                        status=StepStatus.FAILED,
                        error=f"Failed to stage files: {add_result.stderr}",
                    )

            # Check if there are staged changes to commit
            status_result = await _run(
                ["git", "diff", "--cached", "--name-only"], cwd=repo_path
            )

            if not status_result.stdout.strip():
                return WorkflowStepResult(
                    step_name=self.name,
                    status=StepStatus.COMPLETED,
                    output="No changes to commit",
                    metadata={"committed": False, "pushed": False},
                )

            # Commit
            commit_result = await _run(
                ["git", "commit", "-m", commit_message], cwd=repo_path
            )

            if commit_result.returncode != 0:
                return WorkflowStepResult(
                    step_name=self.name,
                    status=StepStatus.FAILED,
                    error=f"Commit failed: {commit_result.stderr or commit_result.stdout}",
                )

            # Get commit hash
            hash_result = await _run(["git", "rev-parse", "HEAD"], cwd=repo_path)
            commit_hash = (
                hash_result.stdout.strip()[:7]
                if hash_result.returncode == 0
                else "unknown"
            )

            # Default to the current branch instead of assuming "main"
            if not branch:
                branch_result = await _run(
                    ["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=repo_path
                )
                current = branch_result.stdout.strip()
                branch = (
                    current
                    if branch_result.returncode == 0 and current and current != "HEAD"
                    else "main"
                )
            branch = str(branch)

            metadata = {
                "committed": True,
                "commit_hash": commit_hash,
                "commit_message": commit_message,
            }

            # Check if remote exists
            remote_result = await _run(
                ["git", "remote", "get-url", remote], cwd=repo_path
            )

            if remote_result.returncode != 0:
                # Try to set up remote from repo_name
                repo_name = context.get("repo_name")
                clone_url = context.get("github_clone_url")
                if repo_name and clone_url and not _is_option_like(clone_url):
                    add_remote = await _run(
                        ["git", "remote", "add", remote, str(clone_url)],
                        cwd=repo_path,
                    )
                    if add_remote.returncode != 0:
                        return WorkflowStepResult(
                            step_name=self.name,
                            status=StepStatus.FAILED,
                            error=(
                                f"Committed {commit_hash} locally, but failed to add "
                                f"remote '{remote}': {add_remote.stderr.strip()}"
                            ),
                            metadata=metadata,
                        )
                else:
                    return WorkflowStepResult(
                        step_name=self.name,
                        status=StepStatus.COMPLETED,
                        output=f"Committed {commit_hash} locally. No remote configured - add a remote to push.",
                        metadata=metadata,
                    )

            # Push
            push_result = await _run(["git", "push", remote, branch], cwd=repo_path)

            if push_result.returncode != 0:
                # Try push with -u for first push
                push_result = await _run(
                    ["git", "push", "-u", remote, branch], cwd=repo_path
                )

                if push_result.returncode != 0:
                    metadata["pushed"] = False
                    return WorkflowStepResult(
                        step_name=self.name,
                        status=StepStatus.FAILED,
                        output=f"Committed {commit_hash} locally.",
                        error=f"Push to {remote}/{branch} failed: {push_result.stderr[:500]}",
                        metadata=metadata,
                    )

            metadata["pushed"] = True
            metadata["branch"] = branch
            metadata["remote"] = remote

            # Get changed files count
            files_changed = len(status_result.stdout.strip().split("\n"))

            return WorkflowStepResult(
                step_name=self.name,
                status=StepStatus.COMPLETED,
                output=f"Committed {commit_hash} ({files_changed} files) and pushed to {remote}/{branch}",
                metadata=metadata,
            )

        except subprocess.TimeoutExpired as e:
            return WorkflowStepResult(
                step_name=self.name,
                status=StepStatus.FAILED,
                error=f"Git command timed out: {' '.join(map(str, e.cmd)) if isinstance(e.cmd, list) else e.cmd}",
            )
        except Exception as e:
            logger.exception(f"[PushToGitHubStep] Error: {e}")
            return WorkflowStepResult(
                step_name=self.name,
                status=StepStatus.FAILED,
                error=str(e),
            )


class InstallDepsStep(WorkflowStep):
    """Step to install project dependencies."""

    def __init__(self, name: str = "install_deps", required: bool = False):
        super().__init__(
            name=name,
            description="Install project dependencies (npm, pip, etc.)",
            required=required,
        )

    def validate_context(self, context: dict[str, Any]) -> list[str]:
        errors = []
        if "project_path" not in context:
            errors.append("Missing 'project_path' in context")
        return errors

    async def execute(self, context: dict[str, Any]) -> WorkflowStepResult:
        import os

        project_path = _resolve_project_path(context)
        package_manager = context.get(
            "package_manager"
        )  # npm, pip, yarn, pnpm, composer, etc.

        try:
            # Auto-detect package manager if not specified
            if not package_manager:
                if os.path.exists(os.path.join(project_path, "package.json")):
                    if os.path.exists(os.path.join(project_path, "yarn.lock")):
                        package_manager = "yarn"
                    elif os.path.exists(os.path.join(project_path, "pnpm-lock.yaml")):
                        package_manager = "pnpm"
                    else:
                        package_manager = "npm"
                elif os.path.exists(os.path.join(project_path, "requirements.txt")):
                    package_manager = "pip"
                elif os.path.exists(os.path.join(project_path, "Pipfile")):
                    package_manager = "pipenv"
                elif os.path.exists(os.path.join(project_path, "pyproject.toml")):
                    package_manager = "pip"
                elif os.path.exists(os.path.join(project_path, "composer.json")):
                    package_manager = "composer"
                elif os.path.exists(os.path.join(project_path, "Cargo.toml")):
                    package_manager = "cargo"
                elif os.path.exists(os.path.join(project_path, "go.mod")):
                    package_manager = "go"
                else:
                    return WorkflowStepResult(
                        step_name=self.name,
                        status=StepStatus.SKIPPED,
                        output="No supported package manager detected",
                    )

            # Run install command
            install_commands = {
                "npm": "npm install",
                "yarn": "yarn install",
                "pnpm": "pnpm install",
                "pip": "pip install -r requirements.txt",
                "pipenv": "pipenv install",
                "composer": "composer install",
                "cargo": "cargo build",
                "go": "go mod download",
            }

            cmd = install_commands.get(package_manager)
            if not cmd:
                return WorkflowStepResult(
                    step_name=self.name,
                    status=StepStatus.SKIPPED,
                    output=f"Unsupported package manager: {package_manager}",
                )

            # pyproject.toml/setup.py-only projects have no requirements.txt
            if package_manager == "pip" and not os.path.exists(
                os.path.join(project_path, "requirements.txt")
            ):
                if os.path.exists(
                    os.path.join(project_path, "pyproject.toml")
                ) or os.path.exists(os.path.join(project_path, "setup.py")):
                    cmd = "pip install -e ."
                else:
                    return WorkflowStepResult(
                        step_name=self.name,
                        status=StepStatus.SKIPPED,
                        output="pip selected but no requirements.txt, pyproject.toml or setup.py found",
                    )

            # Fixed install commands (no interpolated values); shell=True so
            # .cmd shims (npm, yarn, ...) resolve on Windows
            result = await _run(cmd, cwd=project_path, timeout=300, shell=True)

            if result.returncode != 0:
                return WorkflowStepResult(
                    step_name=self.name,
                    status=StepStatus.FAILED,
                    error=f"{package_manager} install failed: {result.stderr[:500]}",
                    output=result.stdout[:500],
                )

            return WorkflowStepResult(
                step_name=self.name,
                status=StepStatus.COMPLETED,
                output=f"Dependencies installed via {package_manager}",
                metadata={
                    "package_manager": package_manager,
                    "deps_installed": True,
                },
            )

        except subprocess.TimeoutExpired:
            return WorkflowStepResult(
                step_name=self.name,
                status=StepStatus.FAILED,
                error="Dependency installation timed out",
            )
        except Exception as e:
            logger.exception(f"[InstallDepsStep] Error: {e}")
            return WorkflowStepResult(
                step_name=self.name,
                status=StepStatus.FAILED,
                error=str(e),
            )


class EnvSetupStep(WorkflowStep):
    """Step to set up environment variables."""

    def __init__(self, name: str = "env_setup", required: bool = False):
        super().__init__(
            name=name,
            description="Set up environment variables and .env file",
            required=required,
        )

    def validate_context(self, context: dict[str, Any]) -> list[str]:
        errors = []
        if "project_path" not in context:
            errors.append("Missing 'project_path' in context")
        return errors

    async def execute(self, context: dict[str, Any]) -> WorkflowStepResult:
        import os

        project_path = _resolve_project_path(context)
        env_vars = context.get("env_vars", {})  # Dict of env var key-value pairs
        env_template = context.get("env_template", "")  # Full .env content
        copy_from = context.get("copy_from", ".env.example")  # File to copy from

        try:
            env_path = os.path.join(project_path, ".env")
            created = False
            updated_vars = []

            # If env_vars dict provided, write/update them
            if env_vars:
                pending = {str(k): v for k, v in env_vars.items()}
                new_lines: list[str] = []

                # Update matching keys in place; keep comments and unrelated
                # lines exactly as they were
                if os.path.exists(env_path):
                    with open(env_path, "r", encoding="utf-8") as f:
                        for raw in f.read().splitlines():
                            key = _parse_env_key(raw)
                            if key is not None and key in pending:
                                prefix = (
                                    "export " if raw.lstrip().startswith("export ") else ""
                                )
                                new_lines.append(
                                    prefix + _format_env_line(key, pending.pop(key))
                                )
                                updated_vars.append(key)
                            else:
                                new_lines.append(raw)

                # Append keys that were not already present
                for key, value in pending.items():
                    new_lines.append(_format_env_line(key, value))
                    updated_vars.append(key)

                with open(env_path, "w", encoding="utf-8") as f:
                    f.write("\n".join(new_lines) + "\n")

                created = True

            # If template content provided, write it
            elif env_template:
                with open(env_path, "w") as f:
                    f.write(env_template)
                created = True

            # If copy_from specified and .env doesn't exist
            elif copy_from and not os.path.exists(env_path):
                template_path = os.path.join(project_path, copy_from)
                if os.path.exists(template_path):
                    import shutil

                    shutil.copy2(template_path, env_path)
                    created = True
                    updated_vars = [f"Copied from {copy_from}"]

            if not created:
                if os.path.exists(env_path):
                    return WorkflowStepResult(
                        step_name=self.name,
                        status=StepStatus.COMPLETED,
                        output=".env file already exists, no changes made",
                        metadata={"env_exists": True},
                    )
                else:
                    return WorkflowStepResult(
                        step_name=self.name,
                        status=StepStatus.SKIPPED,
                        output="No env_vars, env_template, or .env.example found",
                    )

            # Make sure secrets in .env are never committed
            _ensure_gitignored(project_path, ".env")

            vars_str = f" with vars: {', '.join(updated_vars)}" if updated_vars else ""
            return WorkflowStepResult(
                step_name=self.name,
                status=StepStatus.COMPLETED,
                output=f".env file created/updated{vars_str}",
                metadata={
                    "env_created": True,
                    "vars_updated": updated_vars,
                },
            )

        except Exception as e:
            logger.exception(f"[EnvSetupStep] Error: {e}")
            return WorkflowStepResult(
                step_name=self.name,
                status=StepStatus.FAILED,
                error=str(e),
            )


class BuildStep(WorkflowStep):
    """Step to build the project."""

    def __init__(self, name: str = "build", required: bool = False):
        super().__init__(
            name=name,
            description="Build the project (npm run build, make, etc.)",
            required=required,
        )

    def validate_context(self, context: dict[str, Any]) -> list[str]:
        errors = []
        if "project_path" not in context:
            errors.append("Missing 'project_path' in context")
        return errors

    async def execute(self, context: dict[str, Any]) -> WorkflowStepResult:
        import os

        project_path = _resolve_project_path(context)
        build_command = context.get("build_command")  # Custom build command
        build_output_dir = context.get("build_output_dir")  # Expected output dir

        try:
            # Auto-detect build command if not specified
            if not build_command:
                if os.path.exists(os.path.join(project_path, "package.json")):
                    # Check if build script exists in package.json
                    import json

                    with open(os.path.join(project_path, "package.json")) as f:
                        pkg = json.load(f)
                        if "build" in pkg.get("scripts", {}):
                            build_command = "npm run build"
                        elif "compile" in pkg.get("scripts", {}):
                            build_command = "npm run compile"
                elif os.path.exists(os.path.join(project_path, "Makefile")):
                    build_command = "make build"
                elif os.path.exists(os.path.join(project_path, "Cargo.toml")):
                    build_command = "cargo build --release"
                elif os.path.exists(os.path.join(project_path, "go.mod")):
                    build_command = "go build"
                elif os.path.exists(os.path.join(project_path, "pyproject.toml")):
                    # Python projects often don't need a build step
                    return WorkflowStepResult(
                        step_name=self.name,
                        status=StepStatus.SKIPPED,
                        output="Python project - no build step needed",
                    )
                elif os.path.exists(os.path.join(project_path, "setup.py")):
                    return WorkflowStepResult(
                        step_name=self.name,
                        status=StepStatus.SKIPPED,
                        output="Python project - no build step needed",
                    )
                else:
                    return WorkflowStepResult(
                        step_name=self.name,
                        status=StepStatus.SKIPPED,
                        output="No build command detected or needed",
                    )

            if not build_command:
                # e.g. package.json without a "build"/"compile" script
                return WorkflowStepResult(
                    step_name=self.name,
                    status=StepStatus.SKIPPED,
                    output="No build command detected or needed",
                )

            # build_command is a user-supplied shell command (approved via the
            # workflow tool's confirmation); detected commands are constants.
            result = await _run(build_command, cwd=project_path, timeout=300, shell=True)

            if result.returncode != 0:
                return WorkflowStepResult(
                    step_name=self.name,
                    status=StepStatus.FAILED,
                    error=f"Build failed: {result.stderr[:500]}",
                    output=result.stdout[:500],
                )

            metadata = {
                "build_command": build_command,
                "build_success": True,
            }

            # Verify output directory if specified
            if build_output_dir:
                output_path = os.path.join(project_path, build_output_dir)
                if os.path.exists(output_path):
                    metadata["output_dir_exists"] = True
                else:
                    return WorkflowStepResult(
                        step_name=self.name,
                        status=StepStatus.COMPLETED,
                        output=f"Build succeeded but output directory '{build_output_dir}' not found",
                        metadata=metadata,
                    )

            return WorkflowStepResult(
                step_name=self.name,
                status=StepStatus.COMPLETED,
                output=f"Build successful: {build_command}",
                metadata=metadata,
            )

        except subprocess.TimeoutExpired:
            return WorkflowStepResult(
                step_name=self.name,
                status=StepStatus.FAILED,
                error="Build timed out",
            )
        except Exception as e:
            logger.exception(f"[BuildStep] Error: {e}")
            return WorkflowStepResult(
                step_name=self.name,
                status=StepStatus.FAILED,
                error=str(e),
            )


class GenerateReadmeStep(WorkflowStep):
    """Step to generate a README.md file."""

    def __init__(self, name: str = "generate_readme", required: bool = False):
        super().__init__(
            name=name,
            description="Generate README.md for the project",
            required=required,
        )

    def validate_context(self, context: dict[str, Any]) -> list[str]:
        errors = []
        if "project_path" not in context:
            errors.append("Missing 'project_path' in context")
        return errors

    async def execute(self, context: dict[str, Any]) -> WorkflowStepResult:
        import os

        project_path = _resolve_project_path(context)
        repo_name = context.get(
            "repo_name", os.path.basename(os.path.abspath(project_path))
        )
        repo_description = context.get("repo_description", "")
        custom_readme = context.get("custom_readme", "")
        overwrite = context.get("overwrite_readme", False)

        readme_path = os.path.join(project_path, "README.md")

        try:
            # Skip if exists and not overwriting
            if os.path.exists(readme_path) and not overwrite:
                return WorkflowStepResult(
                    step_name=self.name,
                    status=StepStatus.SKIPPED,
                    output="README.md already exists (use overwrite_readme: true to replace)",
                    metadata={"readme_exists": True},
                )

            # Use custom README if provided
            if custom_readme:
                content = custom_readme
            else:
                # Auto-generate from project context
                content = self._generate_readme(
                    project_path, repo_name, repo_description, context
                )

            with open(readme_path, "w") as f:
                f.write(content)

            return WorkflowStepResult(
                step_name=self.name,
                status=StepStatus.COMPLETED,
                output=f"README.md generated for {repo_name}",
                metadata={
                    "readme_generated": True,
                    "readme_path": readme_path,
                },
            )

        except Exception as e:
            logger.exception(f"[GenerateReadmeStep] Error: {e}")
            return WorkflowStepResult(
                step_name=self.name,
                status=StepStatus.FAILED,
                error=str(e),
            )

    def _generate_readme(
        self, project_path: str, repo_name: str, repo_description: str, context: dict
    ) -> str:
        """Generate a README.md content."""
        import os
        import json

        lines = [f"# {repo_name}\n"]

        if repo_description:
            lines.append(f"{repo_description}\n")

        # Detect project type
        project_type = "unknown"
        install_cmd = ""
        run_cmd = ""
        test_cmd = ""
        build_cmd = ""

        if os.path.exists(os.path.join(project_path, "package.json")):
            project_type = "Node.js"
            with open(os.path.join(project_path, "package.json")) as f:
                pkg = json.load(f)
                scripts = pkg.get("scripts", {})
                if "start" in scripts:
                    run_cmd = "npm start"
                elif "dev" in scripts:
                    run_cmd = "npm run dev"
                if "test" in scripts:
                    test_cmd = "npm test"
                if "build" in scripts:
                    build_cmd = "npm run build"
                install_cmd = "npm install"
        elif os.path.exists(os.path.join(project_path, "requirements.txt")):
            project_type = "Python"
            install_cmd = "pip install -r requirements.txt"
            if os.path.exists(os.path.join(project_path, "main.py")):
                run_cmd = "python main.py"
            elif os.path.exists(os.path.join(project_path, "app.py")):
                run_cmd = "python app.py"
            test_cmd = "pytest"
        elif os.path.exists(os.path.join(project_path, "pyproject.toml")):
            project_type = "Python"
            install_cmd = "pip install ."
            test_cmd = "pytest"
        elif os.path.exists(os.path.join(project_path, "Cargo.toml")):
            project_type = "Rust"
            install_cmd = "cargo build"
            run_cmd = "cargo run"
            test_cmd = "cargo test"
        elif os.path.exists(os.path.join(project_path, "go.mod")):
            project_type = "Go"
            run_cmd = "go run ."
            test_cmd = "go test ./..."
        elif os.path.exists(os.path.join(project_path, "composer.json")):
            project_type = "PHP"
            install_cmd = "composer install"
            run_cmd = (
                "php artisan serve"
                if os.path.exists(os.path.join(project_path, "artisan"))
                else ""
            )

        lines.append(f"\n## Tech Stack\n")
        lines.append(f"- {project_type}\n")

        lines.append(f"\n## Installation\n")
        lines.append(f"```bash\n")
        if install_cmd:
            lines.append(f"{install_cmd}\n")
        else:
            lines.append(f"# Install dependencies\n")
        lines.append(f"```\n")

        if run_cmd or build_cmd:
            lines.append(f"\n## Usage\n")
            lines.append(f"```bash\n")
            if build_cmd:
                lines.append(f"{build_cmd}\n")
            if run_cmd:
                lines.append(f"{run_cmd}\n")
            lines.append(f"```\n")

        if test_cmd:
            lines.append(f"\n## Testing\n")
            lines.append(f"```bash\n")
            lines.append(f"{test_cmd}\n")
            lines.append(f"```\n")

        lines.append(f"\n## License\n")
        lines.append(f"MIT\n")

        return "\n".join(lines)


def create_fullstack_workflow() -> Workflow:
    """Create the complete full-stack development workflow."""
    workflow = Workflow(
        name="fullstack",
        description="End-to-end: GitHub -> Push -> Install -> Env -> Build -> DB -> Deploy -> Tests",
    )

    workflow.add_step(CreateGitHubRepoStep())
    workflow.add_step(PushToGitHubStep())
    workflow.add_step(InstallDepsStep())
    workflow.add_step(EnvSetupStep())
    workflow.add_step(BuildStep())
    workflow.add_step(GenerateReadmeStep())
    workflow.add_step(SetupDatabaseStep())
    workflow.add_step(DeployToVercelStep())
    workflow.add_step(RunTestsStep())

    return workflow
