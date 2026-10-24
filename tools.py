#!/usr/bin/env python3
"""ReAct tools — Phase 1 (read-only).

  read_file(path)    — read a file within the working directory
  search_code(query) — search for a substring across common source files
Both are path-safe: paths outside the working directory are rejected.
"""

from __future__ import annotations

from pathlib import Path

_WORKSPACE_ROOT = Path.cwd()
MAX_READ_BYTES = 50 * 1024  # 50 KB


def _safe_path(path: str) -> Path:
    """Resolve *path* and ensure it stays inside the working directory."""
    resolved = (_WORKSPACE_ROOT / path).resolve()
    resolved.relative_to(_WORKSPACE_ROOT)
    return resolved


def read_file(path: str) -> str:
    """Return contents of *path* (must be inside the working directory).

    Files >50 KB are truncated with a warning.
    """
    try:
        safe = _safe_path(path)
    except ValueError:
        return f"[error] Path '{path}' is outside the working directory."
    if not safe.exists():
        return f"[error] File not found: {path}"
    try:
        size = safe.stat().st_size
        if size > MAX_READ_BYTES:
            with open(safe, "rb") as f:
                data = f.read(MAX_READ_BYTES)
            return (f"[truncated: file is {size} bytes, showing first 50KB]\n"
                    + data.decode("utf-8", errors="replace"))
        return safe.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError) as exc:
        return f"[error] {exc}"


SEARCH_EXTENSIONS = (".py", ".js", ".ts", ".md", ".json", ".yaml", ".yml",
                     ".toml", ".txt", ".cfg", ".ini")
_SKIP_DIRS = {"venv", "__pycache__", ".git", ".venv", "node_modules", "dist", "build"}


def search_code(query: str) -> str:
    """Search for *query* as a substring in source files under CWD.

    Searches .py .js .ts .md .json .yaml .yml .toml .txt .cfg .ini.
    Skips binary files and common dependency/build directories.
    """
    matches: list[str] = []
    for src_file in sorted(_WORKSPACE_ROOT.rglob("*")):
        if not src_file.is_file():
            continue
        if src_file.suffix.lower() not in SEARCH_EXTENSIONS:
            continue
        if any(part in _SKIP_DIRS or part.startswith(".")
               for part in src_file.parts):
            continue
        try:
            raw = src_file.read_bytes()
            text = raw.decode("utf-8")
        except (UnicodeDecodeError, OSError):
            continue  # skip binary / unreadable files
        for lineno, line in enumerate(text.splitlines(), start=1):
            if query in line:
                rel = src_file.relative_to(_WORKSPACE_ROOT)
                matches.append(f"{rel}:{lineno}: {line.rstrip()}")
    return "\n".join(matches) if matches else (
        f"No matches for '{query}' in source files.")


TOOL_DEFINITIONS = [
    {"type": "function", "function": {
        "name": "read_file",
        "description": "Read a file within the working directory.",
        "parameters": {"type": "object", "required": ["path"],
                       "properties": {"path": {"type": "string",
                                               "description": "Relative path to the file."}}}},
    },
    {"type": "function", "function": {
        "name": "search_code",
        "description": "Search for a substring across common source files.",
        "parameters": {"type": "object", "required": ["query"],
                       "properties": {"query": {"type": "string",
                                                "description": "The substring to search for."}}}},
    },
]

_TOOL_CALLABLES = {"read_file": read_file, "search_code": search_code}


def execute_tool(name: str, args: dict) -> str:
    """Execute a tool by name and return its string result."""
    fn = _TOOL_CALLABLES.get(name)
    if fn is None:
        return f"[error] Unknown tool: {name}"
    try:
        return fn(**args)
    except Exception as exc:  # broad: any tool failure becomes a clean error string
        return f"[error] {name} failed: {exc}"
