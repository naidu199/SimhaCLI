"""Git context utilities for injecting repo status into system prompts."""

import subprocess
from pathlib import Path
from typing import NamedTuple
import logging

logger = logging.getLogger(__name__)


class GitContext(NamedTuple):
    is_git_repo: bool
    current_branch: str | None
    main_branch: str | None
    status: str | None
    recent_commits: str | None


def _run_git(cwd: Path, *args: str, timeout: int = 5) -> str | None:
    """Run a git command and return stdout, or None on failure."""
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode == 0:
            return result.stdout.strip()
        return None
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None


def _detect_main_branch(cwd: Path) -> str | None:
    """Detect the main/master/default branch of the repository."""
    # Check for common remote default branch refs
    for candidate in ("main", "master"):
        ref = _run_git(cwd, "rev-parse", "--verify", f"refs/heads/{candidate}")
        if ref is not None:
            return candidate

    # Fallback: check symbolic-ref of origin/HEAD
    origin_head = _run_git(cwd, "symbolic-ref", "refs/remotes/origin/HEAD")
    if origin_head:
        # e.g. "refs/remotes/origin/main" -> "main"
        return origin_head.rsplit("/", 1)[-1]

    return None


def get_git_context(cwd: Path) -> GitContext | None:
    """Gather git context for the given working directory.

    Returns None if the directory is not inside a git repository.
    """
    # Check if inside a git repo
    toplevel = _run_git(cwd, "rev-parse", "--show-toplevel")
    if toplevel is None:
        return GitContext(
            is_git_repo=False,
            current_branch=None,
            main_branch=None,
            status=None,
            recent_commits=None,
        )

    # Current branch
    branch = _run_git(cwd, "rev-parse", "--abbrev-ref", "HEAD")

    # Main branch detection
    main_branch = _detect_main_branch(cwd)

    # Git status (short format, no untracked-all to avoid perf issues on large repos)
    status_output = _run_git(cwd, "status", "--short", "--branch")
    if status_output:
        lines = status_output.splitlines()
        # First line is "## branch...tracking", rest are file changes
        file_lines = [l for l in lines[1:] if l.strip()] if len(lines) > 1 else []
        if file_lines:
            status = "\n".join(file_lines)
        else:
            status = "(clean)"
    else:
        status = None

    # Recent commits (last 5, one-line format)
    recent_commits = _run_git(cwd, "log", "--oneline", "-n", "5", "--no-decorate")

    return GitContext(
        is_git_repo=True,
        current_branch=branch,
        main_branch=main_branch,
        status=status,
        recent_commits=recent_commits,
    )


def format_git_context(ctx: GitContext) -> str:
    """Format a GitContext into a section suitable for the system prompt."""
    if not ctx.is_git_repo:
        return ""

    parts = ["# Git Context\n"]
    parts.append(f"- **Git Repository**: Yes")

    if ctx.current_branch:
        parts.append(f"- **Current Branch**: `{ctx.current_branch}`")

    if ctx.main_branch:
        parts.append(f"- **Main Branch**: `{ctx.main_branch}`")

    if ctx.status:
        parts.append(f"\n**Status:**\n```\n{ctx.status}\n```")

    if ctx.recent_commits:
        parts.append(f"\n**Recent Commits:**\n```\n{ctx.recent_commits}\n```")

    return "\n".join(parts)
