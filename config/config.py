from __future__ import annotations
from enum import Enum
import os
from pathlib import Path
from typing import Any
from pydantic import BaseModel, Field, PrivateAttr, model_validator


class ModelConfig(BaseModel):
    name: str = "openrouter/free"
    temperature: float = Field(default=1.0, ge=0.0, le=2.0)
    context_window: int = 256_000


class TelegramConfig(BaseModel):
    """Telegram bot configuration."""
    bot_token: str | None = None
    allowed_user_ids: list[int] = Field(default_factory=list)


class ShellEnvironmentPolicy(BaseModel):
    ignore_default_excludes: bool = False
    exclude_patterns: list[str] = Field(
        default_factory=lambda: ["*KEY*", "*TOKEN*", "*SECRET*"]
    )
    set_vars: dict[str, str] = Field(default_factory=dict)


class MCPServerConfig(BaseModel):
    enabled: bool = True
    startup_timeout_sec: float = 10

    # stdio transport
    command: str | None = None
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    cwd: Path | None = None

    # http/sse transport
    url: str | None = None

    @model_validator(mode="after")
    def validate_transport(self) -> MCPServerConfig:
        has_command = self.command is not None
        has_url = self.url is not None

        if not has_command and not has_url:
            raise ValueError(
                "MCP Server must have either 'command' (stdio) or 'url' (http/sse)"
            )

        if has_command and has_url:
            raise ValueError(
                "MCP Server cannot have both 'command' (stdio) and 'url' (http/sse)"
            )

        return self


class ApprovalPolicy(str, Enum):
    ON_REQUEST = "on_request"
    ALWAYS = "always"
    ON_FAILURE = "on_failure"
    AUTO_APPROVE = "auto_approve"
    AUTO_EDIT = "auto_edit"
    NEVER = "never"
    YOLO = "yolo"


class HookTrigger(str, Enum):
    BEFORE_TOOL = "before_tool"
    AFTER_TOOL = "after_tool"
    BEFORE_AGENT = "before_agent"
    AFTER_AGENT = "after_agent"
    ON_ERROR = "on_error"


class HookConfig(BaseModel):
    name: str
    trigger: HookTrigger
    command: str | None = None
    script: str | None = None
    time_out_sec: float = 30.0
    enabled: bool = True

    @model_validator(mode="after")
    def validate_hook(self) -> HookConfig:
        if self.command is None and self.script is None:
            raise ValueError("Hook must have either 'command' or 'script' defined.")

        return self


class Config(BaseModel):
    model_config = {"populate_by_name": True}

    model: ModelConfig = Field(default_factory=ModelConfig)
    cwd: Path = Field(default_factory=Path.cwd)
    telegram: TelegramConfig = Field(default_factory=TelegramConfig)
    shell_environment: ShellEnvironmentPolicy = Field(
        default_factory=ShellEnvironmentPolicy
    )
    max_turns: int = 72
    max_tool_output_tokens: int = 50_000
    mcp_servers: dict[str, MCPServerConfig] = Field(default_factory=dict)
    developer_instructions: str | None = None
    user_instructions: str | None = None
    approval: ApprovalPolicy = ApprovalPolicy.ON_REQUEST
    hooks_enabled: bool = True
    hooks: list[HookConfig] = Field(default_factory=list)
    allowed_tools: list[str] | None = Field(
        None,
        description="If set, only these tools will be available to the agent",
    )
    denied_tools: list[str] = Field(
        default_factory=list,
        description="Tools explicitly denied from use by the agent",
    )

    debug: bool = False

    # API credentials - stored in config.toml or environment variables
    api_key: str | None = Field(default=None)
    api_base_url: str | None = Field(default=None)

    def get_api_key(self) -> str | None:
        """Get API key from config or environment variable."""
        return self.api_key or os.environ.get("API_KEY")

    def get_api_base_url(self) -> str | None:
        """Get API base URL from config or environment variable."""
        return self.api_base_url or os.environ.get("API_BASE_URL")

    @property
    def model_name(self) -> str:
        return self.model.name

    @model_name.setter
    def model_name(self, value: str) -> None:
        self.model.name = value

    @property
    def temperature(self) -> float:
        return self.model.temperature

    @temperature.setter
    def temperature(self, value: float) -> None:
        self.model.temperature = value

    def validate(self) -> None:
        errors: list[str] = []
        if self.get_api_key() is None:
            errors.append(
                "API_KEY is not configured. Set it in config.toml or as an environment variable."
            )
        if not self.cwd.exists() or not self.cwd.is_dir():
            errors.append(f"CWD path does not exist or is not a directory: {self.cwd}")

        return errors

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")
