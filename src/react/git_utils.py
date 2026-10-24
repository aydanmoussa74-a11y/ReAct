"""Git helpers for the ReAct /commit command."""

from __future__ import annotations

import subprocess
from pathlib import Path


def _run(cmd: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=cwd or Path.cwd(),
        timeout=30,
    )


def is_git_repo(cwd: Path | None = None) -> bool:
    """Return True if the directory is inside a valid git repository."""
    try:
        proc = _run(["git", "rev-parse", "--is-inside-work-tree"], cwd)
        return proc.returncode == 0 and proc.stdout.strip() == "true"
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return False


def get_staged_diff(cwd: Path | None = None) -> str | None:
    """Return the staged diff, or None if there are no staged changes."""
    try:
        proc = _run(["git", "diff", "--cached"], cwd)
        if proc.returncode != 0:
            return None
        diff = proc.stdout.strip()
        return diff if diff else None
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None


def execute_commit(message: str, cwd: Path | None = None) -> tuple[bool, str]:
    """Run `git commit -m message`. Returns (success, output_or_error)."""
    try:
        proc = _run(["git", "commit", "-m", message], cwd)
        out = (proc.stdout or "") + (proc.stderr or "")
        return proc.returncode == 0, out.strip()
    except subprocess.TimeoutExpired:
        return False, "git commit timed out"
    except FileNotFoundError:
        return False, "git not found"
    except OSError as exc:
        return False, str(exc)
