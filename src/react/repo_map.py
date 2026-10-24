"""Repository structure mapping for ReAct."""

from __future__ import annotations

import ast
from pathlib import Path

_IGNORE_DIRS = {
    "__pycache__", "node_modules", ".venv", "venv", "env",
    "dist", "build", ".next", ".idea", ".vscode",
}
_MAX_FILES = 500


def generate_repo_map(workspace: Path) -> str:
    """Return a deterministic, token-efficient file tree with Python structure hints.

    Ignores hidden paths, common build/cache directories, and enforces a hard
    500-file limit. Never follows symlinks that escape the workspace.
    """
    workspace = workspace.resolve()
    entries: list[tuple[Path, int | None, list[str]]] = []
    count = 0

    for path in sorted(workspace.rglob("*")):
        if not path.is_file():
            continue
        # Skip hidden and ignored directories
        try:
            rel = path.relative_to(workspace)
        except ValueError:
            continue
        if any(part.startswith(".") or part in _IGNORE_DIRS for part in rel.parts):
            continue
        # Skip symlinks that escape the workspace
        if path.is_symlink():
            try:
                path.resolve().relative_to(workspace)
            except ValueError:
                continue

        count += 1
        if count > _MAX_FILES:
            return f"[warning] Repo is too large ({count} files). Please use search_code instead."

        line_count: int | None = None
        symbols: list[str] = []
        if path.suffix == ".py":
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
                line_count = text.count("\n") + (1 if text and not text.endswith("\n") else 0)
                tree = ast.parse(text)
                for node in tree.body:
                    if isinstance(node, ast.ClassDef):
                        symbols.append(f"class {node.name}")
                    elif isinstance(node, ast.FunctionDef):
                        symbols.append(f"def {node.name}")
                    elif isinstance(node, ast.AsyncFunctionDef):
                        symbols.append(f"async def {node.name}")
            except (SyntaxError, OSError, UnicodeDecodeError):
                # Still list the file; just omit structure
                pass

        entries.append((rel, line_count, symbols))

    if not entries:
        return "(empty workspace)"

    # Build deterministic tree text
    lines: list[str] = []
    prev_parts: tuple[str, ...] = ()
    for rel, line_count, symbols in entries:
        parts = rel.parts
        # Directory prefixes
        for depth in range(len(parts) - 1):
            prefix = parts[: depth + 1]
            if prefix != prev_parts[: depth + 1]:
                indent = "  " * depth
                lines.append(f"{indent}{parts[depth]}/")
        indent = "  " * (len(parts) - 1)
        name = parts[-1]
        if line_count is not None:
            lines.append(f"{indent}{name} ({line_count} lines)")
        else:
            lines.append(f"{indent}{name}")
        for sym in symbols:
            lines.append(f"{indent}  - {sym}")
        prev_parts = parts

    return "\n".join(lines)
