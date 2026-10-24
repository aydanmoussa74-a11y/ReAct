"""Path safety, snapshots, and unified-diff helpers."""

from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

_WORKSPACE_ROOT = Path.cwd()
SNAPSHOT_ROOT = Path.home() / ".react" / "snapshots"
ALLOW_DOTFILES = False


def safe_path(path: str) -> Path:
    """Resolve path and ensure it stays inside the working directory."""
    resolved = (_WORKSPACE_ROOT / path).resolve()
    resolved.relative_to(_WORKSPACE_ROOT)
    return resolved


def is_dotfile(path: Path) -> bool:
    return any(part.startswith(".") and part not in (".", "..") for part in path.parts)


def check_write_safety(path: str) -> Path | str:
    try:
        safe = safe_path(path)
    except ValueError:
        return f"[error] Path '{path}' is outside the working directory."
    if is_dotfile(safe) and not ALLOW_DOTFILES:
        return (f"[error] Refusing to write to dotfile '{path}'. "
                "Use --dangerously-allow-dotfiles to override.")
    return safe


def snapshot(path: Path) -> None:
    """Copy file (or mark as new) under a timestamped snapshot directory."""
    SNAPSHOT_ROOT.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    snap_dir = SNAPSHOT_ROOT / ts
    snap_dir.mkdir()
    # Keep the complete workspace-relative path even when the file is new.
    rel = path.relative_to(_WORKSPACE_ROOT)
    dest = snap_dir / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        shutil.copy2(path, dest)
    else:
        (snap_dir / ".react-created").write_text("1", encoding="utf-8")
    (snap_dir / ".react-path").write_text(str(rel), encoding="utf-8")


def apply_unified_diff(original: str, diff: str) -> str | None:
    """Apply a unified diff only when every hunk matches the source exactly."""
    import re

    source = original.splitlines(keepends=True)
    patch = diff.splitlines(keepends=True)
    hunk_re = re.compile(r"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@")
    result: list[str] = []
    src_idx = 0
    i = 0
    saw_hunk = False

    while i < len(patch):
        line = patch[i]
        if line.startswith("--- ") or line.startswith("+++ "):
            i += 1
            continue
        if not line.startswith("@@"):
            # Permit blank lines outside hunks, but reject arbitrary patch text.
            if line.strip():
                return None
            i += 1
            continue

        match = hunk_re.match(line.rstrip("\r\n"))
        if not match:
            return None
        saw_hunk = True
        old_start = int(match.group(1))
        target = max(old_start - 1, 0)
        if target < src_idx or target > len(source):
            return None
        result.extend(source[src_idx:target])
        src_idx = target
        i += 1
        old_seen = 0

        while i < len(patch) and not patch[i].startswith("@@"):
            item = patch[i]
            if item.startswith("\\ No newline at end of file"):
                i += 1
                continue
            if not item:
                return None
            marker, body = item[0], item[1:]
            if marker == " ":
                if src_idx >= len(source) or source[src_idx] != body:
                    return None
                result.append(source[src_idx])
                src_idx += 1
                old_seen += 1
            elif marker == "-":
                if src_idx >= len(source) or source[src_idx] != body:
                    return None
                src_idx += 1
                old_seen += 1
            elif marker == "+":
                result.append(body)
            else:
                return None
            i += 1

    if not saw_hunk:
        return None
    result.extend(source[src_idx:])
    return "".join(result)
