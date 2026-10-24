"""Optional Ollama dependency shim.

The CLI and local tools can be inspected and tested without installing the
Ollama client. Install the `ai` extra to connect to an Ollama server.
"""
from __future__ import annotations

from types import SimpleNamespace


def _missing_client(*args, **kwargs):
    raise RuntimeError(
        "Ollama support is not installed. Install ReAct with "
        "`pip install -e '.[ai]'` in an environment where the ollama "
        "dependency can be installed."
    )


try:
    import ollama as ollama  # type: ignore[no-redef]
except ImportError:
    ollama = SimpleNamespace(Client=_missing_client)
