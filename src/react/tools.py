"""Tool implementations for ReAct."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from .repo_map import generate_repo_map
from .mcp_client import get_mcp_tools, call_mcp_tool
from .utils import (
    _WORKSPACE_ROOT,
    check_write_safety,
    safe_path,
    snapshot,
    apply_unified_diff,
)

MAX_READ_BYTES = 50 * 1024

DANGEROUS_PREFIXES = (
    "rm -rf", "rm -fr", "sudo ", "sudo\t", "dd ", "mkfs", ":> ",
    ": >", "shutdown", "reboot", "halt", "poweroff",
    "chmod 777", "chown ", "mkfs.", "fdisk", "parted",
    "wget ", "curl ",
)


def read_file(path: str) -> str:
    try:
        safe = safe_path(path)
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
    matches: list[str] = []
    for src_file in sorted(_WORKSPACE_ROOT.rglob("*")):
        if not src_file.is_file():
            continue
        if src_file.suffix.lower() not in SEARCH_EXTENSIONS:
            continue
        if any(part in _SKIP_DIRS or part.startswith(".") for part in src_file.parts):
            continue
        try:
            text = src_file.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            if query in line:
                rel = src_file.relative_to(_WORKSPACE_ROOT)
                matches.append(f"{rel}:{lineno}: {line.rstrip()}")
    return "\n".join(matches) if matches else f"No matches for '{query}' in source files."


def write_file(path: str, content: str) -> str:
    safe = check_write_safety(path)
    if isinstance(safe, str):
        return safe
    try:
        snapshot(safe)
        safe.parent.mkdir(parents=True, exist_ok=True)
        safe.write_text(content, encoding="utf-8")
        return f"[ok] Wrote {len(content)} bytes to {path}"
    except OSError as exc:
        return f"[error] write_file failed: {exc}"


def edit_file(path: str, diff: str) -> str:
    safe = check_write_safety(path)
    if isinstance(safe, str):
        return safe
    if not safe.exists():
        return f"[error] File not found: {path}"
    try:
        original = safe.read_text(encoding="utf-8")
        new_content = apply_unified_diff(original, diff)
        if new_content is None:
            return "[error] Diff failed to apply. Check the unified diff format and try again."
        snapshot(safe)
        safe.write_text(new_content, encoding="utf-8")
        return f"[ok] Applied diff to {path}"
    except OSError as exc:
        return f"[error] edit_file failed: {exc}"


def undo() -> str:
    from .utils import SNAPSHOT_ROOT
    if not SNAPSHOT_ROOT.exists():
        return "[error] No snapshots found."
    snaps = sorted(SNAPSHOT_ROOT.iterdir(), key=lambda p: p.name, reverse=True)
    if not snaps:
        return "[error] No snapshots found."
    latest = snaps[0]
    path_file = latest / ".react-path"
    if not path_file.exists():
        return "[error] Snapshot is missing path metadata."
    rel = path_file.read_text(encoding="utf-8").strip()
    dest = _WORKSPACE_ROOT / rel
    candidates = list(latest.rglob("*"))
    src = next((p for p in candidates if p.is_file() and p.name != ".react-path"), None)
    if src is None:
        return "[error] Snapshot contains no file."
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        if src.stat().st_size == 0 and not dest.exists():
            if dest.exists():
                dest.unlink()
            return f"[ok] Removed newly created file {rel} (undo)"
        shutil.copy2(src, dest)
        return f"[ok] Restored {rel} from snapshot {latest.name}"
    except OSError as exc:
        return f"[error] undo failed: {exc}"


def run_command(cmd: str) -> str:
    """Run a shell command in the working directory with a 30s timeout."""
    stripped = cmd.strip()
    for bad in DANGEROUS_PREFIXES:
        if stripped.startswith(bad) or f" {bad}" in stripped or stripped.startswith(bad.strip()):
            return "[error] Dangerous command blocked."
    try:
        proc = subprocess.run(
            stripped,
            shell=True,
            capture_output=True,
            text=True,
            timeout=30,
            cwd=_WORKSPACE_ROOT,
        )
        out = proc.stdout or ""
        err = proc.stderr or ""
        return (
            f"Exit Code: {proc.returncode}\n"
            f"STDOUT:\n{out}\n"
            f"STDERR:\n{err}"
        )
    except subprocess.TimeoutExpired:
        return "[error] Command timed out after 30 seconds."
    except Exception as exc:
        return f"[error] run_command failed: {exc}"


def get_repo_map() -> str:
    """Return a structural map of the current workspace."""
    return generate_repo_map(_WORKSPACE_ROOT)


TOOL_DEFINITIONS = [
    {"type": "function", "function": {
        "name": "get_repo_map",
        "description": "Get a high-level structural map of the current project, including filtered file paths and Python class/function names. Use this first when exploring an unfamiliar codebase before reading specific files.",
        "parameters": {"type": "object", "properties": {}, "required": []},
    }},
    {"type": "function", "function": {
        "name": "read_file",
        "description": "Read a file within the working directory.",
        "parameters": {"type": "object", "required": ["path"],
                       "properties": {"path": {"type": "string", "description": "Relative path."}}},
    }},
    {"type": "function", "function": {
        "name": "search_code",
        "description": "Search for a substring across common source files.",
        "parameters": {"type": "object", "required": ["query"],
                       "properties": {"query": {"type": "string", "description": "Substring to find."}}},
    }},
    {"type": "function", "function": {
        "name": "write_file",
        "description": "Write or overwrite a file. Requires user confirmation.",
        "parameters": {"type": "object", "required": ["path", "content"],
                       "properties": {
                           "path": {"type": "string"},
                           "content": {"type": "string"},
                       }},
    }},
    {"type": "function", "function": {
        "name": "edit_file",
        "description": "Apply a unified diff. Requires user confirmation.",
        "parameters": {"type": "object", "required": ["path", "diff"],
                       "properties": {
                           "path": {"type": "string"},
                           "diff": {"type": "string"},
                       }},
    }},
    {"type": "function", "function": {
        "name": "undo",
        "description": "Restore the most recent file snapshot.",
        "parameters": {"type": "object", "properties": {}, "required": []},
    }},
    {"type": "function", "function": {
        "name": "run_command",
        "description": "Run a shell command in the working directory (30s timeout). Dangerous commands are blocked.",
        "parameters": {"type": "object", "required": ["cmd"],
                       "properties": {"cmd": {"type": "string"}}},
    }},
]

_TOOL_CALLABLES = {
    "get_repo_map": get_repo_map,
    "read_file": read_file,
    "search_code": search_code,
    "write_file": write_file,
    "edit_file": edit_file,
    "undo": undo,
    "run_command": run_command,
}


def execute_tool(name: str, args: dict) -> str:
    # MCP tools take priority if loaded
    for tool in get_mcp_tools():
        if tool["function"]["name"] == name:
            return call_mcp_tool(name, args)
    fn = _TOOL_CALLABLES.get(name)
    if fn is None:
        return f"[error] Unknown tool: {name}"
    try:
        return fn(**args)
    except Exception as exc:
        return f"[error] {name} failed: {exc}"
