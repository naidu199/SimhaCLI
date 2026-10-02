"""Model, approval policy and credential changes, shared by the CLI commands
(``/model``, ``/approval``, ``/credentials``) and ``simhacli serve``."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from config.config import ApprovalPolicy
from config.loader import get_config_file_path, set_config_value


@dataclass
class SaveResult:
    """Where a setting was persisted, or why it couldn't be."""

    path: Path | None = None
    error: str | None = None


def project_config_path(config: Any) -> Path:
    return Path(config.cwd) / ".simhacli" / "config.toml"


def _save_to_project(config: Any, section: str, key: str, value: Any) -> SaveResult:
    """Persist to the project config if the project has a .simhacli directory."""
    path = project_config_path(config)
    if not path.parent.exists():
        return SaveResult()
    try:
        set_config_value(section, key, value, config_path=path)
    except Exception as e:
        return SaveResult(error=str(e))
    return SaveResult(path=path)


def set_model(agent: Any, config: Any, name: str) -> SaveResult:
    """Switch the model for this session and save it to the project config."""
    name = name.strip()
    if not name:
        raise ValueError("Model name must not be empty")
    config.model_name = name
    if agent and agent.session:
        tools = agent.session.tool_registry.get_tools()
        agent.session.context_manager.refresh_system_prompt(tools=tools)
    return _save_to_project(config, "model", "name", name)


def parse_approval_policy(value: str) -> ApprovalPolicy:
    try:
        return ApprovalPolicy(value.strip().lower())
    except ValueError:
        valid = ", ".join(p.value for p in ApprovalPolicy)
        raise ValueError(f"Unknown approval policy '{value}'. Valid options: {valid}")


def set_approval(agent: Any, config: Any, value: str) -> tuple[ApprovalPolicy, SaveResult]:
    """Change the approval policy now (live ApprovalManager too) and save it."""
    policy = parse_approval_policy(value)
    config.approval = policy
    session = getattr(agent, "session", None) if agent else None
    approval_manager = getattr(session, "approval_manager", None) if session else None
    if approval_manager is not None:
        approval_manager.approval_policy = policy
    return policy, _save_to_project(config, "", "approval", policy.value)


async def set_credentials(
    agent: Any,
    config: Any,
    api_key: str | None = None,
    base_url: str | None = None,
) -> Path:
    """Save the API key and/or base URL to the global config.

    Blank values are ignored. The LLM client is reset so the next request
    uses the new credentials. Returns the config file path.
    """
    if api_key is not None and api_key.strip():
        api_key = api_key.strip()
        set_config_value("", "api_key", api_key)
        config.api_key = api_key
    if base_url is not None and base_url.strip():
        base_url = base_url.strip()
        set_config_value("", "api_base_url", base_url)
        config.api_base_url = base_url

    if agent and agent.session:
        await agent.session.client.close_client()
    return get_config_file_path()
