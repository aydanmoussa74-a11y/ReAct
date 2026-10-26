"""Optional Ollama client shim with a stdlib HTTP fallback.

The base install stays usable on constrained Python platforms (including Android
terminals) without compiling optional SDK dependencies. If the official Ollama
Python package is installed, use it; otherwise speak the small HTTP API subset
ReAct needs. An Ollama server still has to be installed and running separately.
"""
from __future__ import annotations

import json
import os
from types import SimpleNamespace
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class _StdlibOllamaClient:
    def __init__(self, host: str | None = None, timeout: int = 60, **kwargs) -> None:
        self.host = (host or os.environ.get("OLLAMA_HOST") or "http://127.0.0.1:11434").rstrip("/")
        self.timeout = timeout

    def _request(self, path: str, payload: dict | None = None) -> dict:
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = Request(
            self.host + path,
            data=data,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            raise RuntimeError(f"Ollama HTTP error ({exc.code}): {detail}") from None
        except URLError as exc:
            reason = getattr(exc, "reason", exc)
            raise RuntimeError(
                f"Cannot reach Ollama at {self.host}: {reason}. "
                "Start a reachable Ollama server, or configure a hosted provider."
            ) from None
        except TimeoutError:
            raise RuntimeError(f"Ollama request timed out at {self.host}.") from None
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise RuntimeError("Ollama returned an unreadable response.") from None

    def list(self) -> dict:
        return self._request("/api/tags")

    def show(self, model: str) -> dict:
        return self._request("/api/show", {"name": model})

    def chat(self, *, model: str, messages: list[dict], stream: bool = False, **kwargs) -> dict:
        payload = {"model": model, "messages": messages, "stream": False}
        if kwargs.get("tools"):
            payload["tools"] = kwargs["tools"]
        return self._request("/api/chat", payload)

    def generate(self, **kwargs) -> dict:
        kwargs["stream"] = False
        return self._request("/api/generate", kwargs)


try:
    import ollama as ollama  # type: ignore[no-redef]
except ImportError:
    ollama = SimpleNamespace(Client=_StdlibOllamaClient)
