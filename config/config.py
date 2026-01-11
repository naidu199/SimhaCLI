from doctest import debug
from logging import config
from multiprocessing import context
import os
from pathlib import Path
from click import File
from pydantic import BaseModel, Field


class ModelConfig(BaseModel):
    name: str = "mistralai/devstral-2512:free"
    temperature: float = Field(default=1.0, ge=0.0, le=2.0)
    context_window: int = 256_000


class Config(BaseModel):
    model: ModelConfig = Field(default_factory=ModelConfig)
    cwd: Path = Field(default_factory=Path.cwd())

    max_turns: int = 72
    max_tool_output_tokens: int = 50_000

    developer_instructions: str | None = None
    user_instructions: str | None = None

    debug: bool = False

    @property
    def api_key(self) -> str | None:
        return os.environ.get("API_KEY")

    @property
    def api_base_url(self) -> str | None:
        return os.environ.get("API_BASE_URL")

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
        if self.api_key is None:
            errors.append("API_KEY environment variable is not set.")
        if not self.cwd.exists() or not self.cwd.is_dir():
            errors.append(f"CWD path does not exist or is not a directory: {self.cwd}")

        return errors
