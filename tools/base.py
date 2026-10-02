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


class OriginalContent(str):
    """Pre-edit file content that also records how to restore it.

    Behaves exactly like ``str``. The extra attributes let ``/undo`` tell a
    newly created file apart from an existing file that was originally empty,
    and write the content back using the file's original encoding.
    """

    existed: bool
    encoding: str

    def __new__(
        cls, value: str = "", *, existed: bool = True, encoding: str = "utf-8"
    ) -> "OriginalContent":
        obj = super().__new__(cls, value)
        obj.existed = existed
        obj.encoding = encoding
        return obj


@dataclass
class FileDiff:
    path: Path
    old_content: str
    new_content: str

    is_new_file: bool = False
    is_deletion: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.old_content, OriginalContent):
            self.old_content = OriginalContent(
                self.old_content, existed=not self.is_new_file
            )

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
        properties: dict[str, Any],
        defs: dict[str, Any],
        _seen: frozenset[str] = frozenset(),
    ) -> dict[str, Any]:
        """Recursively resolve $ref pointers to inline definitions.

        This keeps tool schemas flat and understandable by small models that
        do not handle JSON-Schema $ref properly.
        """
        return {
            key: Tool._resolve_schema_refs(value, defs, _seen)
            for key, value in properties.items()
        }

    @staticmethod
    def _resolve_schema_refs(
        node: Any, defs: dict[str, Any], _seen: frozenset[str] = frozenset()
    ) -> Any:
        """Inline $ref pointers in a single schema node (and everything below it)."""
        import copy

        if isinstance(node, list):
            return [Tool._resolve_schema_refs(item, defs, _seen) for item in node]

        if not isinstance(node, dict):
            return node

        if "$ref" in node:
            ref_name = str(node["$ref"]).split("/")[-1]
            # Leave unknown or self-recursive references untouched.
            if ref_name not in defs or ref_name in _seen:
                return copy.deepcopy(node)
            resolved = copy.deepcopy(defs[ref_name])
            # Keep sibling keywords (e.g. description) next to the $ref.
            for key, value in node.items():
                if key != "$ref":
                    resolved.setdefault(key, copy.deepcopy(value))
            return Tool._resolve_schema_refs(resolved, defs, _seen | {ref_name})

        resolved = copy.deepcopy(node)

        if isinstance(resolved.get("properties"), dict):
            resolved["properties"] = Tool._resolve_refs(
                resolved["properties"], defs, _seen
            )

        for key in ("items", "additionalProperties", "not"):
            if isinstance(resolved.get(key), (dict, list)):
                resolved[key] = Tool._resolve_schema_refs(resolved[key], defs, _seen)

        for key in ("anyOf", "oneOf", "allOf", "prefixItems"):
            if isinstance(resolved.get(key), list):
                resolved[key] = Tool._resolve_schema_refs(resolved[key], defs, _seen)

        return resolved
