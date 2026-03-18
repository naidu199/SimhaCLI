"""Full-stack development workflows."""
import logging
from typing import Any

from tools.workflow.engine import Workflow, WorkflowStep, WorkflowStepResult, StepStatus
from tools.workflow.steps import MCPToolStep, ShellCommandStep

logger = logging.getLogger(__name__)


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
            name for name in tool_registry._mcp_tools.keys()
            if "github" in name.lower()
        ]

        if not github_tools:
            # Try with different naming patterns
            github_tools = [
                name for name in tool_registry._mcp_tools.keys()
                if "git" in name.lower()
            ]

        if not github_tools:
            return WorkflowStepResult(
                step_name=self.name,
                status=StepStatus.FAILED,
                error="GitHub MCP server not connected. Please configure the GitHub MCP server.",
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
            name for name in tool_registry._mcp_tools.keys()
            if "supabase" in name.lower()
        ]

        # Look for PostgreSQL MCP tools
        pg_tools = [
            name for name in tool_registry._mcp_tools.keys()
            if "postgres" in name.lower() or "sql" in name.lower() or "database" in name.lower()
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
                error="No database MCP server connected. Please configure PostgreSQL or Supabase MCP server.",
            )

    async def _execute_supabase(self, context: dict[str, Any], supabase_tools: list[str]) -> WorkflowStepResult:
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
                    cwd=context.get("_config", {}).cwd if hasattr(context.get("_config", {}), "cwd") else Path.cwd(),
                )
                result = await tool.execute(invocation)
                metadata["db_schema_applied"] = True
            elif db_schema and query_tool:
                # Use query tool for schema
                tool = tool_registry.get(query_tool)
                invocation = ToolInvocation(
                    params={"query": db_schema, "project_ref": db_name},
                    cwd=context.get("_config", {}).cwd if hasattr(context.get("_config", {}), "cwd") else Path.cwd(),
                )
                result = await tool.execute(invocation)
                metadata["db_schema_applied"] = True
            elif project_tool:
                # Create project if tool available
                tool = tool_registry.get(project_tool)
                invocation = ToolInvocation(
                    params={"name": db_name},
                    cwd=context.get("_config", {}).cwd if hasattr(context.get("_config", {}), "cwd") else Path.cwd(),
                )
                result = await tool.execute(invocation)
            else:
                # Use first available tool with best effort
                tool_name = supabase_tools[0]
                tool = tool_registry.get(tool_name)
                params = {"query": db_schema} if db_schema else {}
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
                output=result.output or f"Supabase project '{db_name}' configured successfully",
                metadata=metadata,
            )

        except Exception as e:
            logger.exception(f"[SetupDatabaseStep/Supabase] Error: {e}")
            return WorkflowStepResult(
                step_name=self.name,
                status=StepStatus.FAILED,
                error=str(e),
            )

    async def _execute_postgres(self, context: dict[str, Any], pg_tools: list[str]) -> WorkflowStepResult:
        """Execute database setup using PostgreSQL MCP tools."""
        from tools.base import ToolInvocation
        from pathlib import Path

        db_name = context["db_name"]
        db_schema = context.get("db_schema", None)

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
                    cwd=context.get("_config", {}).cwd if hasattr(context.get("_config", {}), "cwd") else Path.cwd(),
                )
                result = await tool.execute(invocation)
            elif query_tool:
                tool = tool_registry.get(query_tool)
                create_sql = f'CREATE DATABASE "{db_name}";'
                invocation = ToolInvocation(
                    params={"query": create_sql},
                    cwd=context.get("_config", {}).cwd if hasattr(context.get("_config", {}), "cwd") else Path.cwd(),
                )
                result = await tool.execute(invocation)
            else:
                return WorkflowStepResult(
                    step_name=self.name,
                    status=StepStatus.FAILED,
                    error="No suitable PostgreSQL tool found for database creation",
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
                    cwd=context.get("_config", {}).cwd if hasattr(context.get("_config", {}), "cwd") else Path.cwd(),
                )
                schema_result = await tool.execute(invocation)
                if schema_result.error:
                    return WorkflowStepResult(
                        step_name=self.name,
                        status=StepStatus.COMPLETED,
                        output=f"Database '{db_name}' created. Schema creation failed: {schema_result.error}",
                        metadata=metadata,
                    )
                metadata["db_schema_applied"] = True

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
            name for name in tool_registry._mcp_tools.keys()
            if "vercel" in name.lower()
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

            project_path = context["project_path"]
            project_name = context.get("project_name", None)

            params = {
                "path": project_path,
            }
            if project_name:
                params["name"] = project_name

            tool = tool_registry.get(deploy_tool)
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

            metadata = {
                "vercel_deployed": True,
                "deploy_path": project_path,
            }

            # Try to extract deployment URL
            output = result.output or ""
            import re
            url_match = re.search(r'https://[a-z0-9-]+\.vercel\.app', output)
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
        import subprocess

        project_path = context["project_path"]

        try:
            # Check if vercel CLI is installed
            check = subprocess.run(
                "vercel --version",
                shell=True,
                capture_output=True,
                text=True,
            )

            if check.returncode != 0:
                return WorkflowStepResult(
                    step_name=self.name,
                    status=StepStatus.FAILED,
                    error="Vercel CLI not installed. Install with: npm i -g vercel",
                )

            # Deploy
            result = subprocess.run(
                "vercel --yes",
                shell=True,
                capture_output=True,
                text=True,
                cwd=project_path,
                timeout=300,
            )

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
            url_match = re.search(r'https://[a-z0-9-]+\.vercel\.app', result.stdout)
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
            name for name in tool_registry._mcp_tools.keys()
            if "playwright" in name.lower() or "browser" in name.lower()
        ]

        if not playwright_tools:
            return WorkflowStepResult(
                step_name=self.name,
                status=StepStatus.SKIPPED,
                output="Playwright MCP server not connected. Skipping tests.",
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
                    if action in name.lower() or "navigate" in name.lower() or "goto" in name.lower():
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
                    cwd=context.get("_config", {}).cwd if hasattr(context.get("_config", {}), "cwd") else Path.cwd(),
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
        import subprocess
        import re

        repo_path = context.get("project_path", ".")
        commit_message = context.get("commit_message", f"Update via SimhaCLI")
        files = context.get("files", [])  # Specific files to add, or all if empty
        branch = context.get("branch", "main")
        remote = context.get("remote", "origin")

        try:
            # Check if it's a git repo
            check_result = subprocess.run(
                "git rev-parse --is-inside-work-tree",
                shell=True,
                capture_output=True,
                text=True,
                cwd=repo_path,
            )

            if check_result.returncode != 0:
                # Try to initialize
                init_result = subprocess.run(
                    "git init",
                    shell=True,
                    capture_output=True,
                    text=True,
                    cwd=repo_path,
                )
                if init_result.returncode != 0:
                    return WorkflowStepResult(
                        step_name=self.name,
                        status=StepStatus.FAILED,
                        error=f"Failed to initialize git repo: {init_result.stderr}",
                    )

            # Add files
            if files:
                for file in files:
                    add_result = subprocess.run(
                        f'git add "{file}"',
                        shell=True,
                        capture_output=True,
                        text=True,
                        cwd=repo_path,
                    )
                    if add_result.returncode != 0:
                        return WorkflowStepResult(
                            step_name=self.name,
                            status=StepStatus.FAILED,
                            error=f"Failed to add file '{file}': {add_result.stderr}",
                        )
            else:
                # Add all changes
                add_result = subprocess.run(
                    "git add -A",
                    shell=True,
                    capture_output=True,
                    text=True,
                    cwd=repo_path,
                )
                if add_result.returncode != 0:
                    return WorkflowStepResult(
                        step_name=self.name,
                        status=StepStatus.FAILED,
                        error=f"Failed to stage files: {add_result.stderr}",
                    )

            # Check if there are changes to commit
            status_result = subprocess.run(
                "git status --porcelain",
                shell=True,
                capture_output=True,
                text=True,
                cwd=repo_path,
            )

            if not status_result.stdout.strip():
                return WorkflowStepResult(
                    step_name=self.name,
                    status=StepStatus.COMPLETED,
                    output="No changes to commit",
                    metadata={"committed": False, "pushed": False},
                )

            # Commit
            commit_result = subprocess.run(
                f'git commit -m "{commit_message}"',
                shell=True,
                capture_output=True,
                text=True,
                cwd=repo_path,
            )

            if commit_result.returncode != 0:
                return WorkflowStepResult(
                    step_name=self.name,
                    status=StepStatus.FAILED,
                    error=f"Commit failed: {commit_result.stderr}",
                )

            # Get commit hash
            hash_result = subprocess.run(
                "git rev-parse HEAD",
                shell=True,
                capture_output=True,
                text=True,
                cwd=repo_path,
            )
            commit_hash = hash_result.stdout.strip()[:7] if hash_result.returncode == 0 else "unknown"

            metadata = {
                "committed": True,
                "commit_hash": commit_hash,
                "commit_message": commit_message,
            }

            # Check if remote exists
            remote_result = subprocess.run(
                f"git remote get-url {remote}",
                shell=True,
                capture_output=True,
                text=True,
                cwd=repo_path,
            )

            if remote_result.returncode != 0:
                # Try to set up remote from repo_name
                repo_name = context.get("repo_name")
                if repo_name:
                    # Check for GitHub MCP clone URL
                    clone_url = context.get("github_clone_url")
                    if clone_url:
                        subprocess.run(
                            f"git remote add {remote} {clone_url}",
                            shell=True,
                            capture_output=True,
                            text=True,
                            cwd=repo_path,
                        )
                    else:
                        return WorkflowStepResult(
                            step_name=self.name,
                            status=StepStatus.COMPLETED,
                            output=f"Committed {commit_hash} locally. No remote configured - add a remote to push.",
                            metadata=metadata,
                        )

            # Push
            push_result = subprocess.run(
                f"git push {remote} {branch}",
                shell=True,
                capture_output=True,
                text=True,
                cwd=repo_path,
                timeout=60,
            )

            if push_result.returncode != 0:
                # Try push with -u for first push
                push_result = subprocess.run(
                    f"git push -u {remote} {branch}",
                    shell=True,
                    capture_output=True,
                    text=True,
                    cwd=repo_path,
                    timeout=60,
                )

                if push_result.returncode != 0:
                    return WorkflowStepResult(
                        step_name=self.name,
                        status=StepStatus.COMPLETED,
                        output=f"Committed {commit_hash} locally. Push failed: {push_result.stderr[:200]}",
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

        except subprocess.TimeoutExpired:
            return WorkflowStepResult(
                step_name=self.name,
                status=StepStatus.FAILED,
                error="Push timed out",
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
        import subprocess
        import os

        project_path = context["project_path"]
        package_manager = context.get("package_manager")  # npm, pip, yarn, pnpm, composer, etc.

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

            result = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                cwd=project_path,
                timeout=300,
            )

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

        project_path = context["project_path"]
        env_vars = context.get("env_vars", {})  # Dict of env var key-value pairs
        env_template = context.get("env_template", "")  # Full .env content
        copy_from = context.get("copy_from", ".env.example")  # File to copy from

        try:
            env_path = os.path.join(project_path, ".env")
            created = False
            updated_vars = []

            # If env_vars dict provided, write/update them
            if env_vars:
                existing = {}
                if os.path.exists(env_path):
                    with open(env_path, "r") as f:
                        for line in f:
                            line = line.strip()
                            if line and not line.startswith("#") and "=" in line:
                                key, _, value = line.partition("=")
                                existing[key.strip()] = value.strip()

                # Merge with new vars
                existing.update(env_vars)

                # Write .env file
                with open(env_path, "w") as f:
                    for key, value in existing.items():
                        f.write(f'{key}="{value}"\n')
                        updated_vars.append(key)

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
        import subprocess
        import os

        project_path = context["project_path"]
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

            result = subprocess.run(
                build_command,
                shell=True,
                capture_output=True,
                text=True,
                cwd=project_path,
                timeout=300,
            )

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

        project_path = context["project_path"]
        repo_name = context.get("repo_name", os.path.basename(os.path.abspath(project_path)))
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
                content = self._generate_readme(project_path, repo_name, repo_description, context)

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

    def _generate_readme(self, project_path: str, repo_name: str, repo_description: str, context: dict) -> str:
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
            run_cmd = "php artisan serve" if os.path.exists(os.path.join(project_path, "artisan")) else ""

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
