#!/usr/bin/env python3
"""ReAct tools — Phase 1 (read-only) + Phase 2 (write with confirmation).

  read_file(path)    — read a file within the working directory
  search_code(query) — search for a substring across common source files
  write_file(path, content) — overwrite a file (requires confirmation)
  edit_file(path, diff)     — apply a unified diff (requires confirmation)
  undo()                    — restore the most recent snapshot

Path safety: all paths are resolved and must stay inside CWD.
Dotfiles (.env, .git/*, etc.) are blocked unless allow_dotfiles=True.
Snapshots are stored under ~/.react/snapshots/{timestamp}/ before any write.
"""

from __future__ import annotations

import os
import shutil
from datetime import datetime
from pathlib import Path

_WORKSPACE_ROOT = Path.cwd()
MAX_READ_BYTES = 50 * 1024  # 50 KB
SNAPSHOT_ROOT = Path.home() / ".react" / "snapshots"

ALLOW_DOTFILES = False


def _safe_path(path: str) -> Path:
    resolved = (_WORKSPACE_ROOT / path).resolve()
    resolved.relative_to(_WORKSPACE_ROOT)
    return resolved


def _is_dotfile(path: Path) -> bool:
    return any(part.startswith(".") and part not in (".", "..") for part in path.parts)


def _check_write_safety(path: str) -> Path | str:
    try:
        safe = _safe_path(path)
    except ValueError:
        return f"[error] Path '{path}' is outside the working directory."
    if _is_dotfile(safe) and not ALLOW_DOTFILES:
        return (f"[error] Refusing to write to dotfile '{path}'. "
                "Use --dangerously-allow-dotfiles to override.")
    return safe


def _snapshot(path: Path) -> None:
    SNAPSHOT_ROOT.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    snap_dir = SNAPSHOT_ROOT / ts
    snap_dir.mkdir()
    rel = path.relative_to(_WORKSPACE_ROOT) if path.exists() else Path(path.name)
    dest = snap_dir / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        shutil.copy2(path, dest)
    else:
        dest.write_text("", encoding="utf-8")
    (snap_dir / ".react-path").write_text(str(rel), encoding="utf-8")


def read_file(path: str) -> str:
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
            text = src_file.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            if query in line:
                rel = src_file.relative_to(_WORKSPACE_ROOT)
                matches.append(f"{rel}:{lineno}: {line.rstrip()}")
    return "\n".join(matches) if matches else f"No matches for '{query}' in source files."


def write_file(path: str, content: str) -> str:
    safe = _check_write_safety(path)
    if isinstance(safe, str):
        return safe
    try:
        _snapshot(safe)
        safe.parent.mkdir(parents=True, exist_ok=True)
        safe.write_text(content, encoding="utf-8")
        return f"[ok] Wrote {len(content)} bytes to {path}"
    except OSError as exc:
        return f"[error] write_file failed: {exc}"


def _apply_unified_diff(original: str, diff: str) -> str | None:
    lines = original.splitlines(keepends=True)
    diff_lines = diff.splitlines(keepends=True)
    i = 0
    result: list[str] = []
    src_idx = 0
    while i < len(diff_lines):
        line = diff_lines[i]
        if line.startswith("@@"):
            try:
                header = line.split("@@")[1].strip().split()
                old_part = header[0]
                start = int(old_part.split(",")[0].lstrip("-"))
            except (IndexError, ValueError):
                return None
            while src_idx < start - 1 and src_idx < len(lines):
                result.append(lines[src_idx])
                src_idx += 1
            i += 1
            while i < len(diff_lines) and not diff_lines[i].startswith("@@") and not diff_lines[i].startswith("---"):
                dline = diff_lines[i]
                if dline.startswith("+") and not dline.startswith("+++"):
                    result.append(dline[1:])
                elif dline.startswith("-") and not dline.startswith("---"):
                    src_idx += 1
                elif dline.startswith(" "):
                    if src_idx < len(lines):
                        result.append(lines[src_idx])
                        src_idx += 1
                    else:
                        result.append(dline[1:])
                else:
                    if src_idx < len(lines):
                        result.append(lines[src_idx])
                        src_idx += 1
                i += 1
            continue
        i += 1
    while src_idx < len(lines):
        result.append(lines[src_idx])
        src_idx += 1
    return "".join(result)


def edit_file(path: str, diff: str) -> str:
    safe = _check_write_safety(path)
    if isinstance(safe, str):
        return safe
    if not safe.exists():
        return f"[error] File not found: {path}"
    try:
        original = safe.read_text(encoding="utf-8")
        new_content = _apply_unified_diff(original, diff)
        if new_content is None:
            return "[error] Diff failed to apply. Check the unified diff format and try again."
        _snapshot(safe)
        safe.write_text(new_content, encoding="utf-8")
        return f"[ok] Applied diff to {path}"
    except OSError as exc:
        return f"[error] edit_file failed: {exc}"


def undo() -> str:
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


TOOL_DEFINITIONS = [
    {"type": "function", "function": {
        "name": "read_file",
        "description": "Read a file within the working directory.",
        "parameters": {"type": "object", "required": ["path"],
                       "properties": {"path": {"type": "string",
                                               "description": "Relative path to the file."}}},
    }},
    {"type": "function", "function": {
        "name": "search_code",
        "description": "Search for a substring across common source files.",
        "parameters": {"type": "object", "required": ["query"],
                       "properties": {"query": {"type": "string",
                                                "description": "The substring to search for."}}},
    }},
    {"type": "function", "function": {
        "name": "write_file",
        "description": "Write or overwrite a file. Requires user confirmation.",
        "parameters": {"type": "object", "required": ["path", "content"],
                       "properties": {
                           "path": {"type": "string", "description": "Relative path."},
                           "content": {"type": "string", "description": "Full file content."},
                       }},
    }},
    {"type": "function", "function": {
        "name": "edit_file",
        "description": "Apply a unified diff to an existing file. Requires user confirmation.",
        "parameters": {"type": "object", "required": ["path", "diff"],
                       "properties": {
                           "path": {"type": "string", "description": "Relative path."},
                           "diff": {"type": "string", "description": "Unified diff text."},
                       }},
    }},
    {"type": "function", "function": {
        "name": "undo",
        "description": "Restore the most recent file snapshot.",
        "parameters": {"type": "object", "properties": {}, "required": []},
    }},
]

_TOOL_CALLABLES = {
    "read_file": read_file,
    "search_code": search_code,
    "write_file": write_file,
    "edit_file": edit_file,
    "undo": undo,
}


def execute_tool(name: str, args: dict) -> str:
    fn = _TOOL_CALLABLES.get(name)
    if fn is None:
        return f"[error] Unknown tool: {name}"
    try:
        return fn(**args)
    except Exception as exc:
        return f"[error] {name} failed: {exc}"
