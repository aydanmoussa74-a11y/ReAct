"""Tool implementations for ReAct."""

from __future__ import annotations

import os
import shutil
import shlex
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
MAX_SEARCH_MATCHES = 200
MAX_SEARCH_FILES = 5_000
MAX_SEARCH_FILE_BYTES = 1 * 1024 * 1024
MAX_COMMAND_OUTPUT_CHARS = 20_000

DANGEROUS_COMMANDS = {
    "rm", "sudo", "su", "dd", "mkfs", "mkfs.ext4", "fdisk", "parted",
    "shutdown", "reboot", "halt", "poweroff", "chmod", "chown", "curl", "wget",
}


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
    """Search source files with strict traversal, file-size, and result limits."""
    if not query:
        return "[error] Search query cannot be empty."
    matches: list[str] = []
    files_seen = 0
    truncated = False
    for root, dirs, filenames in os.walk(_WORKSPACE_ROOT, topdown=True, followlinks=False):
        root_path = Path(root)
        dirs[:] = sorted(
            d for d in dirs
            if d not in _SKIP_DIRS and not d.startswith(".")
            and not (root_path / d).is_symlink()
        )
        for filename in sorted(filenames):
            src_file = root_path / filename
            try:
                rel = src_file.relative_to(_WORKSPACE_ROOT)
            except ValueError:
                continue
            if any(part in _SKIP_DIRS or part.startswith(".") for part in rel.parts):
                continue
            if src_file.suffix.lower() not in SEARCH_EXTENSIONS:
                continue
            files_seen += 1
            if files_seen > MAX_SEARCH_FILES:
                truncated = True
                break
            try:
                if src_file.stat().st_size > MAX_SEARCH_FILE_BYTES:
                    continue
                text = src_file.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            for lineno, line in enumerate(text.splitlines(), start=1):
                if query in line:
                    matches.append(f"{rel}:{lineno}: {line.rstrip()}")
                    if len(matches) >= MAX_SEARCH_MATCHES:
                        truncated = True
                        break
            if truncated:
                break
        if truncated:
            break
    if not matches:
        return f"No matches for '{query}' in source files."
    output = "\\n".join(matches)
    if truncated:
        output += f"\\n[truncated: search limits reached; showing at most {MAX_SEARCH_MATCHES} matches]"
    return output


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
    created_marker = latest / ".react-created"
    if created_marker.exists():
        try:
            if dest.exists():
                dest.unlink()
            return f"[ok] Removed newly created file {rel} (undo)"
        except OSError as exc:
            return f"[error] undo failed: {exc}"
    candidates = list(latest.rglob("*"))
    src = next((p for p in candidates if p.is_file() and p.name not in {".react-path", ".react-created"}), None)
    if src is None:
        return "[error] Snapshot contains no file."
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        return f"[ok] Restored {rel} from snapshot {latest.name}"
    except OSError as exc:
        return f"[error] undo failed: {exc}"


def run_command(cmd: str) -> str:
    """Run one explicitly tokenized command (no shell interpretation), with a timeout."""
    try:
        argv = shlex.split(cmd)
    except ValueError as exc:
        return f"[error] Invalid command syntax: {exc}"
    if not argv:
        return "[error] Command cannot be empty."
    executable = Path(argv[0]).name.lower()
    if executable in DANGEROUS_COMMANDS:
        return f"[error] Command blocked by safety policy: {executable}"
    try:
        proc = subprocess.run(
            argv,
            shell=False,
            capture_output=True,
            text=True,
            timeout=30,
            cwd=_WORKSPACE_ROOT,
        )
        out = proc.stdout or ""
        err = proc.stderr or ""
        combined = (
            f"Exit Code: {proc.returncode}\n"
            f"STDOUT:\n{out}\n"
            f"STDERR:\n{err}"
        )
        if len(combined) > MAX_COMMAND_OUTPUT_CHARS:
            combined = combined[:MAX_COMMAND_OUTPUT_CHARS] + "\n[truncated: command output limit reached]"
        return combined
    except subprocess.TimeoutExpired:
        return "[error] Command timed out after 30 seconds."
    except FileNotFoundError:
        return f"[error] Executable not found: {argv[0]}"
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
        "description": "Run one command without shell interpretation (30s timeout); dangerous executables are blocked and user confirmation is required.",
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
