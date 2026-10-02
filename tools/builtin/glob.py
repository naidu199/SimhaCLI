import fnmatch
import os
from pathlib import Path
import re
from tools.base import Tool, ToolInvocation, ToolKind, ToolResult
from pydantic import BaseModel, Field

from utils.paths import is_binary_file, resolve_path


def is_excluded_dir(name: str, excluded: set[str]) -> bool:
    """Check a directory name against exclusions (supports wildcards like '*.egg-info')."""
    if name in excluded:
        return True
    return any(
        fnmatch.fnmatchcase(name, pattern)
        for pattern in excluded
        if any(ch in pattern for ch in "*?[")
    )


def glob_to_regex(pattern: str) -> re.Pattern:
    """Translate a glob pattern into a regex matched against a POSIX relative path.

    - ``**/`` matches zero or more directories, a trailing ``/**`` matches
      everything below a directory, any other ``**`` matches any characters
    - ``*`` matches within a single path segment, ``?`` one character
    - ``[...]`` character classes (``[!...]`` negates)
    """
    i, n = 0, len(pattern)
    parts: list[str] = []
    while i < n:
        c = pattern[i]
        if c == "*":
            if pattern.startswith("**", i):
                i += 2
                if i < n and pattern[i] == "/":
                    parts.append("(?:.*/)?")
                    i += 1
                else:
                    parts.append(".*")
                continue
            parts.append("[^/]*")
        elif c == "?":
            parts.append("[^/]")
        elif c == "[":
            j = i + 1
            if j < n and pattern[j] in "!^":
                j += 1
            if j < n and pattern[j] == "]":
                j += 1
            while j < n and pattern[j] != "]":
                j += 1
            if j >= n:
                parts.append(re.escape(c))
            else:
                body = pattern[i + 1 : j].replace("\\", "\\\\")
                if body and body[0] in "!^":
                    body = "^" + body[1:]
                parts.append(f"[{body}]")
                i = j
        else:
            parts.append(re.escape(c))
        i += 1
    return re.compile("".join(parts) + r"\Z", re.DOTALL)


def make_path_matcher(pattern: str, root: Path | None = None):
    """Build a predicate ``(rel_posix_path) -> bool`` for a glob pattern.

    Patterns without a slash match the file name at any depth (``*.py``).
    Patterns with a slash match relative to the search root (``src/**/*.py``),
    or as a trailing path suffix (``components/*.tsx`` also matches
    ``app/components/Button.tsx``). Absolute patterns under ``root`` are made
    relative to it.
    """
    pattern = pattern.replace("\\", "/").strip()
    if root is not None and Path(pattern).is_absolute():
        try:
            pattern = Path(pattern).relative_to(root.resolve()).as_posix()
        except ValueError:
            pass
    while pattern.startswith("./"):
        pattern = pattern[2:]

    if "/" not in pattern:
        regex = glob_to_regex(pattern)
        return lambda rel: regex.match(rel.rsplit("/", 1)[-1]) is not None

    pattern = pattern.lstrip("/")
    regex = glob_to_regex(pattern)
    suffix_regex = glob_to_regex(
        pattern if pattern.startswith("**/") else "**/" + pattern
    )
    return lambda rel: (
        regex.match(rel) is not None or suffix_regex.match(rel) is not None
    )


class GlobParams(BaseModel):
    pattern: str = Field(
        ...,
        description=(
            "Glob pattern to match. Patterns without '/' match file names at any depth "
            "(e.g. '*.py'); patterns with '/' match paths relative to the search path "
            "or any trailing part of them (e.g. 'src/**/*.py')."
        ),
    )
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
            matches = self._glob_with_exclusions(
                search_path, params.pattern, Path(invocation.cwd)
            )
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

    def _glob_with_exclusions(
        self, search_path: Path, pattern: str, cwd: Path | None = None
    ) -> list[Path]:
        """Recursively glob with directory exclusions.

        The pattern is matched against the path relative to ``search_path``
        (and, as a convenience, relative to ``cwd`` when the file is under it).
        """
        results = []
        matches = make_path_matcher(pattern, search_path)

        for root, dirs, files in os.walk(search_path):
            # Filter out excluded directories in-place
            dirs[:] = [d for d in dirs if not is_excluded_dir(d, self.EXCLUDED_DIRS)]

            root_path = Path(root)

            for file in files:
                file_path = root_path / file
                # Match only the path relative to the search root
                rel_path = file_path.relative_to(search_path).as_posix()
                if matches(rel_path):
                    results.append(file_path)
                    continue
                if cwd is not None and cwd != search_path:
                    try:
                        cwd_rel = file_path.relative_to(cwd).as_posix()
                    except ValueError:
                        continue
                    if matches(cwd_rel):
                        results.append(file_path)

        return results

    def _find_files(self, search_path: Path) -> list[Path]:
        files = []

        for root, dirs, filenames in os.walk(search_path):
            dirs[:] = [d for d in dirs if not is_excluded_dir(d, self.EXCLUDED_DIRS)]

            for filename in filenames:
                if filename.startswith("."):
                    continue

                file_path = Path(root) / filename
                if not is_binary_file(file_path):
                    files.append(file_path)
                    if len(files) >= 500:
                        return files

        return files
