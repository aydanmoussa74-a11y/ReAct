#!/bin/sh
# ReAct bootstrap: create a local venv, install base dependencies, launch.
# Run from any directory: sh /path/to/ReAct/scripts/react.sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"

find_python() {
  for candidate in python3 python; do
    if command -v "$candidate" >/dev/null 2>&1 &&
       "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)' >/dev/null 2>&1; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done
  return 1
}
PYTHON=$(find_python) || {
  echo "ReAct requires Python 3.10+. Install Python in this terminal and retry." >&2
  exit 1
}
if [ ! -x ".venv/bin/python" ]; then
  echo "[ReAct] Creating project virtual environment..."
  "$PYTHON" -m venv .venv || {
    echo "Could not create .venv. This terminal's Python may lack venv/ensurepip support." >&2
    echo "Install the terminal's Python venv package, or use a terminal that supports Python venv." >&2
    exit 1
  }
fi
if ! .venv/bin/python -c 'import typer, rich' >/dev/null 2>&1; then
  echo "[ReAct] Installing ReAct dependencies (first run needs internet)..."
  .venv/bin/python -m pip install --upgrade pip
  .venv/bin/python -m pip install -e .
fi
if [ "${1-}" = "--classic" ]; then
  # The default branch currently provides the classic REPL; the TUI flag is
  # available on the fullscreen-tui feature branch after its merge.
  shift
fi
exec .venv/bin/react "$@"
