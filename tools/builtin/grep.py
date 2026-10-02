import os
from pathlib import Path
import re
from tools.base import Tool, ToolInvocation, ToolKind, ToolResult
from tools.builtin.glob import is_excluded_dir, make_path_matcher
from pydantic import BaseModel, Field

from utils.paths import is_binary_file, resolve_path


class GrepParams(BaseModel):
    pattern: str = Field(..., description="Regular expression pattern to search for")
    path: str = Field(
        ".", description="File or directory to search in (default: current directory)"
    )
    case_insensitive: bool = Field(
        True,
        description="Case-insensitive search (default: true)",
    )
    context_lines: int = Field(
        0,
        description="Number of context lines to show before and after each match (default: 0)",
        ge=0,
        le=5,
    )
    max_matches_per_file: int = Field(
        50,
        description="Maximum matches to show per file (default: 50)",
        ge=1,
        le=200,
    )
    file_pattern: str | None = Field(
        None,
        description="Optional glob pattern to filter files (e.g., '*.py', '*.js')",
    )


MAX_FILES_SEARCHED = 500


class GrepTool(Tool):
    name = "grep"
    description = (
        "Search for a regex pattern in file contents. Returns matching lines with file paths and line numbers. "
        "Supports context lines and file filtering. Case-insensitive by default."
    )
    kind = ToolKind.READ
    schema = GrepParams

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
        params = GrepParams(**invocation.params)

        search_path = resolve_path(invocation.cwd, params.path)

        if not search_path.exists():
            return ToolResult.error_result(f"Path does not exist: {search_path}")

        try:
            flags = re.IGNORECASE if params.case_insensitive else 0
            pattern = re.compile(params.pattern, flags)
        except re.error as e:
            return ToolResult.error_result(f"Invalid regex pattern: {e}")

        file_limit_hit = False
        if search_path.is_dir():
            files = self._find_files(search_path, params.file_pattern)
            file_limit_hit = len(files) >= MAX_FILES_SEARCHED
        else:
            files = [search_path]
        limit_note = (
            f"(search stopped after {MAX_FILES_SEARCHED} files; "
            "narrow the path or file_pattern to search the rest)"
        )

        output_lines = []
        total_matches = 0
        files_with_matches = 0
        truncated_files = []

        for file_path in files:
            try:
                content = file_path.read_text(encoding="utf-8")
            except Exception:
                continue

            lines = content.splitlines()
            file_matches = []

            # Find all matches in the file
            for i, line in enumerate(lines, start=1):
                if pattern.search(line):
                    file_matches.append((i, line))

            if file_matches:
                files_with_matches += 1
                try:
                    rel_path = file_path.relative_to(invocation.cwd)
                except ValueError:
                    rel_path = file_path

                # Limit matches per file
                displayed_matches = file_matches[: params.max_matches_per_file]
                total_matches += len(file_matches)

                output_lines.append(f"\n📄 {rel_path} ({len(file_matches)} matches)")

                # Process each match with context
                for line_num, line in displayed_matches:
                    # Add context lines before
                    if params.context_lines > 0:
                        start_ctx = max(1, line_num - params.context_lines)
                        for ctx_num in range(start_ctx, line_num):
                            ctx_line = (
                                lines[ctx_num - 1] if ctx_num - 1 < len(lines) else ""
                            )
                            output_lines.append(f"  {ctx_num}: {ctx_line}")

                    # Plain text only: this output goes to the model, so no ANSI codes
                    output_lines.append(f"→ {line_num}: {line}")

                    # Add context lines after
                    if params.context_lines > 0:
                        end_ctx = min(len(lines), line_num + params.context_lines)
                        for ctx_num in range(line_num + 1, end_ctx + 1):
                            ctx_line = (
                                lines[ctx_num - 1] if ctx_num - 1 < len(lines) else ""
                            )
                            output_lines.append(f"  {ctx_num}: {ctx_line}")

                        # Add separator between matches with context
                        if (
                            params.context_lines > 0
                            and displayed_matches.index((line_num, line))
                            < len(displayed_matches) - 1
                        ):
                            output_lines.append("  ...")

                # Note if file had more matches than displayed
                if len(file_matches) > params.max_matches_per_file:
                    truncated_files.append(rel_path)
                    remaining = len(file_matches) - params.max_matches_per_file
                    output_lines.append(f"  ... ({remaining} more matches not shown)")

                output_lines.append("")

        if not output_lines:
            search_info = f"pattern '{params.pattern}'"
            if params.file_pattern:
                search_info += f" in files matching '{params.file_pattern}'"

            no_match_msg = f"No matches found for {search_info}"
            if file_limit_hit:
                no_match_msg += f"\n{limit_note}"

            return ToolResult.success_result(
                no_match_msg,
                metadata={
                    "path": str(search_path),
                    "matches": 0,
                    "files_searched": len(files),
                    "files_with_matches": 0,
                    "file_limit_hit": file_limit_hit,
                },
            )

        # Add summary at the top
        summary = f"Found {total_matches} matches in {files_with_matches} files (searched {len(files)} files)"
        if truncated_files:
            summary += f"\n⚠️  {len(truncated_files)} files had matches truncated to {params.max_matches_per_file} per file"
        if file_limit_hit:
            summary += f"\n{limit_note}"

        result_output = summary + "\n" + "\n".join(output_lines)

        return ToolResult.success_result(
            result_output,
            metadata={
                "path": str(search_path),
                "matches": total_matches,
                "files_searched": len(files),
                "files_with_matches": files_with_matches,
                "truncated": len(truncated_files) > 0,
                "file_limit_hit": file_limit_hit,
            },
        )

    def _find_files(
        self, search_path: Path, file_pattern: str | None = None
    ) -> list[Path]:
        files = []
        matches = make_path_matcher(file_pattern, search_path) if file_pattern else None

        for root, dirs, filenames in os.walk(search_path):
            # Filter out excluded directories in-place
            dirs[:] = [d for d in dirs if not is_excluded_dir(d, self.EXCLUDED_DIRS)]

            for filename in filenames:
                if filename.startswith("."):
                    continue

                file_path = Path(root) / filename

                # Apply file pattern filter if specified
                if matches and not matches(
                    file_path.relative_to(search_path).as_posix()
                ):
                    continue

                if not is_binary_file(file_path):
                    files.append(file_path)
                    if len(files) >= MAX_FILES_SEARCHED:
                        return files

        return files
