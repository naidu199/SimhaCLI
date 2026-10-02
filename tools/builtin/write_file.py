from pathlib import Path

from pydantic import BaseModel, Field
from tools.base import (
    FileDiff,
    OriginalContent,
    Tool,
    ToolConfirmation,
    ToolInvocation,
    ToolKind,
    ToolResult,
)
from utils.paths import ensure_parent_directory, resolve_path


def read_original_content(path: Path) -> OriginalContent:
    """Read the current file content (utf-8, falling back to latin-1 like read_file).

    Line endings are preserved so /undo can restore the file byte-for-byte.
    """
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            return OriginalContent(f.read(), existed=True, encoding="utf-8")
    except UnicodeDecodeError:
        with path.open("r", encoding="latin-1", newline="") as f:
            return OriginalContent(f.read(), existed=True, encoding="latin-1")


class WriteFileParams(BaseModel):
    path: str = Field(
        ...,
        description="Path to the file to write (relative to working directory or absolute)",
    )
    content: str = Field(..., description="Content to write to the file")
    create_directories: bool = Field(
        True, description="Create parent directories if they don't exist"
    )


class WriteFileTool(Tool):
    name = "write_file"
    description = (
        "Write content to a file. Creates the file if it doesn't exist, "
        "or overwrites if it does. Parent directories are created automatically. "
        "Use this for creating new files or completely replacing file contents. "
        "For partial modifications, use the edit tool instead."
    )
    kind = ToolKind.WRITE
    schema = WriteFileParams

    async def get_confirmation(
        self, invocation: ToolInvocation
    ) -> ToolConfirmation | None:
        params = WriteFileParams(**invocation.params)
        path = resolve_path(invocation.cwd, params.path)
        is_new_file = not path.exists()

        old_content = ""
        if not is_new_file:
            try:
                old_content = read_original_content(path)
            except OSError:
                pass

        diff = FileDiff(
            path=path,
            old_content=old_content,
            new_content=params.content,
            is_new_file=is_new_file,
        )

        action = "Created" if is_new_file else "Updated"

        return ToolConfirmation(
            tool_name=self.name,
            params=invocation.params,
            description=f"{action} file: {path}",
            diff=diff,
            affected_paths=[path],
            is_dangerous=not is_new_file,
        )

    async def execute(self, invocation: ToolInvocation) -> ToolResult:
        params = WriteFileParams(**invocation.params)
        path = resolve_path(invocation.cwd, params.path)
        is_new_file = not path.exists()
        old_content = ""

        if not is_new_file:
            # The original content must be captured, otherwise /undo cannot
            # restore it - refuse to overwrite a file we cannot read.
            try:
                old_content = read_original_content(path)
            except OSError as e:
                return ToolResult.error_result(
                    f"Failed to read existing file {path} before overwriting: {e}"
                )
        try:
            if params.create_directories:
                ensure_parent_directory(path)
            elif not path.parent.exists():
                return ToolResult.error_result(
                    f"Parent directory does not exist: {path.parent}"
                )
            path.write_text(params.content, encoding="utf-8")
            action = "Created" if is_new_file else "Updated"
            line_count = len(params.content.splitlines())

            return ToolResult.success_result(
                f"{action} {path} {line_count} lines",
                diff=FileDiff(
                    path=path,
                    old_content=old_content,
                    new_content=params.content,
                    is_new_file=is_new_file,
                ),
                metadata={
                    "path": str(path),
                    "is_new_file": is_new_file,
                    "lines": line_count,
                    "bytes": len(params.content.encode("utf-8")),
                },
            )
        except OSError as e:
            return ToolResult.error_result(
                error=f"Failed to write to file {path}: {str(e)}",
            )
