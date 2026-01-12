import os
from pathlib import Path
import re
from tools.base import Tool, ToolInvocation, ToolKind, ToolResult
from pydantic import BaseModel, Field

from utils.paths import is_binary_file, resolve_path


class GlobParams(BaseModel):
    pattern: str = Field(..., description="Glob pattern to match")
    path: str = Field(
        ".", description="Directory to search in (default: current directory)"
    )


class GlobTool(Tool):
    name = "glob"
    description = (
        "Find files matching a glob pattern. Supports ** for recursive matching."
    )
    kind = ToolKind.READ
    schema = GlobParams

    EXCLUDED_DIRS = {
        "node_modules",
        "__pycache__",
        ".git",
        ".venv",
        "venv",
        ".env",
        "env",
        "dist",
        "build",
        ".next",
        ".nuxt",
        "target",
        "bin",
        "obj",
        ".gradle",
        ".idea",
        ".vscode",
        "coverage",
        ".pytest_cache",
        ".mypy_cache",
        ".tox",
        "site-packages",
        ".eggs",
        "*.egg-info",
    }

    async def execute(self, invocation: ToolInvocation) -> ToolResult:
        params = GlobParams(**invocation.params)

        search_path = resolve_path(invocation.cwd, params.path)

        if not search_path.exists() or not search_path.is_dir():
            return ToolResult.error_result(f"Directory does not exist: {search_path}")

        try:
            matches = self._glob_with_exclusions(search_path, params.pattern)
        except Exception as e:
            return ToolResult.error_result(f"Error searching: {e}")

        output_lines = []

        for file_path in matches[:1000]:
            try:
                rel_path = file_path.relative_to(invocation.cwd)
            except Exception:
                rel_path = file_path

            output_lines.append(str(rel_path))

        if len(matches) > 1000:
            output_lines.append(f"...(limited to 1000 results)")

        # Provide informative message when no matches found
        if not output_lines:
            output_lines.append(f"No files matching pattern '{params.pattern}' found")

        return ToolResult.success_result(
            "\n".join(output_lines),
            metadata={
                "path": str(search_path),
                "matches": len(matches),
            },
        )

    def _glob_with_exclusions(self, search_path: Path, pattern: str) -> list[Path]:
        """Recursively glob with directory exclusions."""
        results = []

        for root, dirs, files in os.walk(search_path):
            # Filter out excluded directories in-place
            dirs[:] = [d for d in dirs if d not in self.EXCLUDED_DIRS]

            root_path = Path(root)

            # Check if current directory matches pattern for files
            for file in files:
                file_path = root_path / file
                # Try to match the pattern relative to search_path
                try:
                    rel_path = file_path.relative_to(search_path)
                    if file_path.match(pattern) or rel_path.match(pattern):
                        results.append(file_path)
                except Exception:
                    # If pattern doesn't work with match, fall back to simple glob check
                    if file_path.name == pattern.replace("**/", "").replace("*/", ""):
                        results.append(file_path)

        return results

    def _find_files(self, search_path: Path) -> list[Path]:
        files = []

        for root, dirs, filenames in os.walk(search_path):
            dirs[:] = [d for d in dirs if d not in self.EXCLUDED_DIRS]

            for filename in filenames:
                if filename.startswith("."):
                    continue

                file_path = Path(root) / filename
                if not is_binary_file(file_path):
                    files.append(file_path)
                    if len(files) >= 500:
                        return files

        return files
