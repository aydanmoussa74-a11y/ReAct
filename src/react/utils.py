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
    rel = path.relative_to(_WORKSPACE_ROOT) if path.exists() else Path(path.name)
    dest = snap_dir / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        shutil.copy2(path, dest)
    else:
        dest.write_text("", encoding="utf-8")
    (snap_dir / ".react-path").write_text(str(rel), encoding="utf-8")


def apply_unified_diff(original: str, diff: str) -> str | None:
    """Best-effort unified-diff applicator. Returns new content or None on failure."""
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
                start = int(header[0].split(",")[0].lstrip("-"))
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
