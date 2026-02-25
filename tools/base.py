from __future__ import annotations
import abc

from enum import Enum

from pathlib import Path
from typing import Any
from pydantic import BaseModel, ValidationError
from dataclasses import dataclass, field
from pydantic.json_schema import model_json_schema

from config.config import Config


class ToolKind(str, Enum):
    READ = "read"
    WRITE = "write"
    SHELL = "shell"
    NETWORK = "network"
    MEMORY = "memory"
    MCP = "mcp"


@dataclass
class FileDiff:
    path: Path
    old_content: str
    new_content: str

    is_new_file: bool = False
    is_deletion: bool = False

    def to_diff(self) -> str:
        import difflib

        old_lines = self.old_content.splitlines(keepends=True)
        new_lines = self.new_content.splitlines(keepends=True)

        if old_lines and not old_lines[-1].endswith("\n"):
            old_lines[-1] += "\n"
        if new_lines and not new_lines[-1].endswith("\n"):
            new_lines[-1] += "\n"

        old_name = "/dev/null" if self.is_new_file else str(self.path)
        new_name = "/dev/null" if self.is_deletion else str(self.path)

        diff = difflib.unified_diff(
            old_lines,
            new_lines,
            fromfile=old_name,
            tofile=new_name,
        )

        return "".join(diff)


@dataclass
class ToolInvocation:
    cwd: Path
    params: dict[str, Any]


@dataclass
class ToolResult:
    success: bool
    output: str
    error: str | None = None
    metadata: dict[str, Any] | None = field(default_factory=dict)
    truncated: bool = False
    diff: FileDiff | None = None
    exit_code: int | None = None

    @classmethod
    def error_result(cls, error: str, output: str = "", **kwargs: Any):
        return cls(
            success=False,
            output=output,
            error=error,
            **kwargs,
        )

    @classmethod
    def success_result(cls, output: str, **kwargs: Any):
        return cls(
            success=True,
            output=output,
            error=None,
            **kwargs,
        )

    def to_model_output(self) -> str:
        if self.success:
            return self.output

        return f"Error: {self.error}\n\nOutput:\n{self.output}"


@dataclass
class ToolConfirmation:
    tool_name: str
    params: dict[str, Any]
    description: str

    diff: FileDiff | None = None
    affected_paths: list[Path] = field(default_factory=list)
    command: str | None = None
    is_dangerous: bool = False


class Tool(abc.ABC):
    name: str = "base_tool"
    description: str = "Base tool description"
    kind: ToolKind = ToolKind.READ

    def __init__(self, config: Config) -> None:
        self.config = config

    @property
    def schema(self) -> dict[str, Any] | type["BaseModel"]:
        raise NotImplementedError(
            "Tool must define a schema property or class attribute."
        )

    @abc.abstractmethod
    async def execute(self, invocation: ToolInvocation) -> ToolResult:
        pass

    def validate_params(self, params: dict[str, Any]) -> list[str]:
        schema = self.schema
        if isinstance(schema, type) and issubclass(schema, BaseModel):
            try:
                schema(**params)
                return []
            except ValidationError as e:
                errors = []
                for err in e.errors():
                    field = ".".join(str(loc) for loc in err.get("loc", []))
                    message = err.get("msg", "Validation error")
                    errors.append(f"Parameter {field}: {message}")
                return errors
            except Exception as e:
                return [str(e)]

        return []

    def is_mutating(self, params: dict[str, Any]) -> bool:
        return self.kind in {
            ToolKind.WRITE,
            ToolKind.SHELL,
            ToolKind.NETWORK,
            ToolKind.MCP,
        }

    async def get_confirmation(
        self, invocation: ToolInvocation
    ) -> ToolConfirmation | None:
        if not self.is_mutating(invocation.params):
            return None

        return ToolConfirmation(
            tool_name=self.name,
            params=invocation.params,
            description=f"Execute {self.name}",
        )

    def to_openai_schema(self) -> dict[str, Any]:
        schema = self.schema

        if isinstance(schema, type) and issubclass(schema, BaseModel):

            json_schema = model_json_schema(schema, mode="serialization")

            # Build a clean parameters dict – strip Pydantic artefacts that
            # confuse smaller models ($defs, definitions, additionalProperties).
            properties = json_schema.get("properties", {})
            # Inline any $ref references and remove $defs to keep the schema flat
            defs = json_schema.get("$defs", json_schema.get("definitions", {}))
            if defs:
                properties = self._resolve_refs(properties, defs)

            return {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": json_schema.get("required", []),
                },
            }

        if isinstance(schema, dict):
            result = {
                "name": self.name,
                "description": self.description,
            }

            if "parameters" in schema:
                result["parameters"] = schema["parameters"]
            else:
                result["parameters"] = schema

            return result

        raise ValueError(f"Invalid schema type for tool {self.name}: {type(schema)}")

    @staticmethod
    def _resolve_refs(
        properties: dict[str, Any], defs: dict[str, Any]
    ) -> dict[str, Any]:
        """Recursively resolve $ref pointers to inline definitions.

        This keeps tool schemas flat and understandable by small models that
        do not handle JSON-Schema $ref properly.
        """
        import copy

        resolved: dict[str, Any] = {}
        for key, value in properties.items():
            if isinstance(value, dict):
                if "$ref" in value:
                    ref_name = value["$ref"].split("/")[-1]
                    if ref_name in defs:
                        resolved[key] = copy.deepcopy(defs[ref_name])
                    else:
                        resolved[key] = value
                else:
                    resolved[key] = copy.deepcopy(value)
                    # Recurse into nested properties
                    if "properties" in resolved[key]:
                        resolved[key]["properties"] = Tool._resolve_refs(
                            resolved[key]["properties"], defs
                        )
            else:
                resolved[key] = value
        return resolved
