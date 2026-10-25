"""Optional Ollama dependency shim.

Core CLI commands and tests can run without the Ollama client installed.
Actual model operations fail with an actionable message until the optional
`ai` extra is installed in a compatible environment.
"""
from __future__ import annotations


class _MissingOllamaClient:
    def __init__(self, *args, **kwargs) -> None:
        # Permit constructing an Agent for local commands that do not call an LLM.
        pass

    @staticmethod
    def _raise(*args, **kwargs):
        raise RuntimeError(
            "Ollama support is not installed. Install ReAct with "
            "`pip install -e '.[ai]'` in an environment where the ollama "
            "dependency can be installed."
        )

    chat = _raise
    list = _raise
    show = _raise
    generate = _raise


try:
    import ollama as ollama  # type: ignore[no-redef]
except ImportError:
    from types import SimpleNamespace

    ollama = SimpleNamespace(Client=_MissingOllamaClient)
