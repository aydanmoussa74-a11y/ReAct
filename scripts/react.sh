#!/bin/sh
# ReAct portable bootstrap + launcher. Run from the repository root:
#   sh scripts/react.sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"

find_python() {
  for candidate in python3 python; do
    if command -v "$candidate" >/dev/null 2>&1; then
      if "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)' >/dev/null 2>&1; then
        printf '%s\n' "$candidate"
        return 0
      fi
    fi
  done
  return 1
}

PYTHON=$(find_python) || {
  echo "ReAct needs Python 3.10 or newer. Install Python, reopen this terminal, and retry." >&2
  exit 1
}

if [ ! -x ".venv/bin/python" ]; then
  echo "[ReAct] Creating an isolated Python environment..."
  "$PYTHON" -m venv .venv || {
    echo "Could not create .venv. Ensure this Python installation includes venv/ensurepip support." >&2
    exit 1
  }
fi

if ! .venv/bin/python -c 'import textual, typer, rich' >/dev/null 2>&1; then
  echo "[ReAct] Installing ReAct and required terminal UI dependencies..."
  .venv/bin/python -m pip install --upgrade pip
  .venv/bin/python -m pip install -e .
fi

if [ "${1-}" = "--classic" ]; then
  shift
  exec .venv/bin/react --classic "$@"
fi

exec .venv/bin/react "$@"
