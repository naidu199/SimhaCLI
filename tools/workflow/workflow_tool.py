"""Workflow tool for executing development workflows."""
import asyncio
import logging
from typing import Any

from config.config import Config
from tools.base import Tool, ToolInvocation, ToolKind, ToolResult
from tools.workflow.engine import WorkflowEngine, WorkflowStatus
from tools.workflow.fullstack import (
    create_fullstack_workflow,
    CreateGitHubRepoStep,
    PushToGitHubStep,
    InstallDepsStep,
    EnvSetupStep,
    BuildStep,
    GenerateReadmeStep,
    SetupDatabaseStep,
    DeployToVercelStep,
    RunTestsStep,
)

logger = logging.getLogger(__name__)


class WorkflowTool(Tool):
    """Tool for executing end-to-end development workflows or individual steps."""

    name = "workflow"
    description = """Execute development workflows - full pipeline or individual steps.

Available actions:
- fullstack: Run complete pipeline (all steps below)
- github: Create a GitHub repository only
- push: Commit and push code changes to GitHub
- install_deps: Install project dependencies (npm, pip, yarn, etc.)
- env_setup: Create .env file from template or with custom vars
- build: Build the project (npm run build, cargo build, etc.)
- readme: Generate README.md for the project
- database: Set up database (PostgreSQL/Supabase) only
- deploy: Deploy to Vercel only
- tests: Run Playwright tests only

Supported package managers: npm, yarn, pnpm, pip, pipenv, composer, cargo, go
Supported database MCP servers: PostgreSQL, Supabase

Usage examples:
- Full workflow: {"action": "fullstack", "repo_name": "my-app", "db_name": "myapp_db", "project_path": "./my-app"}
- Create repo: {"action": "github", "repo_name": "my-app", "repo_description": "My app"}
- Push code: {"action": "push", "project_path": "./my-app", "commit_message": "Add feature"}
- Install deps: {"action": "install_deps", "project_path": "./my-app"}
- Setup env: {"action": "env_setup", "project_path": "./my-app", "env_vars": {"API_KEY": "xxx", "DB_URL": "yyy"}}
- Build: {"action": "build", "project_path": "./my-app"}
- Generate readme: {"action": "readme", "project_path": "./my-app", "repo_description": "My awesome app"}
- Database: {"action": "database", "db_name": "myapp_db", "db_schema": "CREATE TABLE users..."}
- Deploy: {"action": "deploy", "project_path": "./my-app"}
- Tests: {"action": "tests", "test_url": "https://my-app.vercel.app"}
"""

    kind = ToolKind.MCP

    def __init__(self, config: Config, registry=None):
        super().__init__(config)
        self._registry = registry

    @property
    def schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": "Action: fullstack, github, push, install_deps, env_setup, build, readme, database, deploy, tests",
                    "enum": ["fullstack", "github", "push", "install_deps", "env_setup", "build", "readme", "database", "deploy", "tests"],
                },
                "repo_name": {
                    "type": "string",
                    "description": "Name of the GitHub repository to create",
                },
                "repo_description": {
                    "type": "string",
                    "description": "Description for the GitHub repository",
                },
                "repo_private": {
                    "type": "boolean",
                    "description": "Whether the repository should be private",
                    "default": False,
                },
                "db_name": {
                    "type": "string",
                    "description": "Name of the PostgreSQL/Supabase database to create",
                },
                "db_schema": {
                    "type": "string",
                    "description": "SQL schema to apply after database creation",
                },
                "project_path": {
                    "type": "string",
                    "description": "Path to the project directory for deployment",
                },
                "project_name": {
                    "type": "string",
                    "description": "Name for the Vercel project",
                },
                "test_url": {
                    "type": "string",
                    "description": "URL to run tests against",
                },
                "test_scenarios": {
                    "type": "array",
                    "description": "Custom test scenarios to run",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "action": {"type": "string"},
                            "url": {"type": "string"},
                            "selector": {"type": "string"},
                        },
                    },
                },
                "commit_message": {
                    "type": "string",
                    "description": "Commit message for git push",
                },
                "files": {
                    "type": "array",
                    "description": "Specific files to commit (empty = all changes)",
                    "items": {"type": "string"},
                },
                "branch": {
                    "type": "string",
                    "description": "Git branch to push to (default: main)",
                    "default": "main",
                },
                "package_manager": {
                    "type": "string",
                    "description": "Package manager to use (npm, yarn, pnpm, pip, etc.)",
                    "enum": ["npm", "yarn", "pnpm", "pip", "pipenv", "composer", "cargo", "go"],
                },
                "env_vars": {
                    "type": "object",
                    "description": "Environment variables to set in .env file",
                    "additionalProperties": {"type": "string"},
                },
                "env_template": {
                    "type": "string",
                    "description": "Full .env file content to write",
                },
                "copy_from": {
                    "type": "string",
                    "description": "Copy .env from this file (default: .env.example)",
                    "default": ".env.example",
                },
                "build_command": {
                    "type": "string",
                    "description": "Custom build command (auto-detected if not provided)",
                },
                "build_output_dir": {
                    "type": "string",
                    "description": "Expected build output directory to verify",
                },
                "custom_readme": {
                    "type": "string",
                    "description": "Custom README.md content to write",
                },
                "overwrite_readme": {
                    "type": "boolean",
                    "description": "Overwrite existing README.md",
                    "default": False,
                },
            },
            "required": ["action"],
        }

    def is_mutating(self, params) -> bool:
        return True

    def _build_context(self, invocation: ToolInvocation) -> dict[str, Any]:
        """Build context dict from invocation params."""
        context = {}
        for key in [
            "repo_name", "repo_description", "repo_private", "repo_auto_init",
            "db_name", "db_schema",
            "project_path", "project_name",
            "test_url", "test_scenarios",
            "commit_message", "files", "branch", "remote",
            "package_manager", "env_vars", "env_template", "copy_from",
            "build_command", "build_output_dir",
            "custom_readme", "overwrite_readme",
        ]:
            if key in invocation.params:
                context[key] = invocation.params[key]
        return context

    def _format_step_result(self, step_name: str, result) -> str:
        """Format a single step result for output."""
        status_icon = {
            "completed": "✅",
            "failed": "❌",
            "skipped": "⏭️",
            "pending": "⏳",
            "running": "🔄",
        }.get(result.status.value, "❓")

        lines = [f"{status_icon} **{step_name}**: {result.status.value}"]
        if result.output:
            lines.append(f"   {result.output[:300]}")
        if result.error:
            lines.append(f"   Error: {result.error}")
        return "\n".join(lines)

    async def _execute_single_step(self, step, context: dict[str, Any], step_name: str) -> ToolResult:
        """Execute a single workflow step."""
        from tools.workflow.engine import WorkflowEngine

        engine = WorkflowEngine(
            tool_registry=self._registry,
            config=self.config,
        )

        # Add engine context
        context["_engine"] = engine
        context["_tool_registry"] = self._registry
        context["_config"] = self.config

        # Validate context
        validation_errors = step.validate_context(context)
        if validation_errors:
            return ToolResult.error_result(
                f"Missing required parameters: {'; '.join(validation_errors)}"
            )

        try:
            result = await step.execute(context)
            output = self._format_step_result(step_name, result)

            return ToolResult.success_result(
                output=output,
                metadata={
                    "step_name": step_name,
                    "status": result.status.value,
                    **result.metadata,
                },
            )
        except Exception as e:
            logger.exception(f"[WorkflowTool] Error executing {step_name}")
            return ToolResult.error_result(f"{step_name} failed: {e}")

    async def execute(self, invocation: ToolInvocation) -> ToolResult:
        action = invocation.params.get("action")

        if not action:
            return ToolResult.error_result(
                "Action is required. Use: fullstack, github, push, database, deploy, or tests"
            )

        context = self._build_context(invocation)

        # Route to appropriate handler
        if action == "fullstack":
            return await self._run_full_workflow(context)
        elif action == "github":
            return await self._execute_single_step(
                CreateGitHubRepoStep(), context, "create_github_repo"
            )
        elif action == "push":
            return await self._execute_single_step(
                PushToGitHubStep(), context, "push_to_github"
            )
        elif action == "install_deps":
            return await self._execute_single_step(
                InstallDepsStep(), context, "install_deps"
            )
        elif action == "env_setup":
            return await self._execute_single_step(
                EnvSetupStep(), context, "env_setup"
            )
        elif action == "build":
            return await self._execute_single_step(
                BuildStep(), context, "build"
            )
        elif action == "readme":
            return await self._execute_single_step(
                GenerateReadmeStep(), context, "generate_readme"
            )
        elif action == "database":
            return await self._execute_single_step(
                SetupDatabaseStep(), context, "setup_database"
            )
        elif action == "deploy":
            return await self._execute_single_step(
                DeployToVercelStep(), context, "deploy_vercel"
            )
        elif action == "tests":
            return await self._execute_single_step(
                RunTestsStep(), context, "run_tests"
            )
        else:
            return ToolResult.error_result(
                f"Unknown action: {action}. Use: fullstack, github, push, install_deps, env_setup, build, readme, database, deploy, or tests"
            )

    async def _run_full_workflow(self, context: dict[str, Any]) -> ToolResult:
        """Execute the complete fullstack workflow."""
        engine = WorkflowEngine(
            tool_registry=self._registry,
            config=self.config,
        )

        workflow = create_fullstack_workflow()
        engine.register_workflow(workflow)

        try:
            result = await engine.execute_workflow("fullstack", context)

            output_lines = [
                f"# Workflow: {result.workflow_name}",
                f"Status: {result.status.value}",
                "",
            ]

            for step in result.steps:
                output_lines.append(self._format_step_result(step.step_name, step))
                output_lines.append("")

            if result.error:
                output_lines.append(f"**Error**: {result.error}")

            return ToolResult.success_result(
                output="\n".join(output_lines),
                metadata={
                    "workflow_status": result.status.value,
                    "steps_completed": len(result.completed_steps),
                    "steps_failed": len(result.failed_steps),
                    "total_steps": len(result.steps),
                },
            )

        except Exception as e:
            logger.exception("[WorkflowTool] Error executing full workflow")
            return ToolResult.error_result(f"Workflow execution failed: {e}")


def get_workflow_tools(config: Config) -> list[Tool]:
    """Get all workflow-related tools."""
    return [WorkflowTool(config)]
