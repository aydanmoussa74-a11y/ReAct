"""Provider selection and OpenRouter BYOK client.

OpenRouter uses an OpenAI-compatible HTTP API. This adapter intentionally uses
only Python's standard library so it can run in constrained environments such
as Termux without installing another SDK.
"""
from __future__ import annotations

import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .ollama_compat import ollama


class OpenRouterClient:
    """Small synchronous client exposing the subset of the Ollama API ReAct uses."""

    def __init__(self, api_key: str | None = None, timeout: int = 60) -> None:
        self.api_key = api_key or os.environ.get("OPENROUTER_API_KEY", "")
        self.timeout = timeout
        self.base_url = os.environ.get(
            "OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"
        ).rstrip("/")
        if not self.api_key:
            raise RuntimeError(
                "OpenRouter API key is missing. Set OPENROUTER_API_KEY in your "
                "Termux session, then retry. Never paste your key into source code."
            )

    def _request(self, path: str, payload: dict | None = None) -> dict:
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/aydanmoussa74-a11y/ReAct",
            "X-Title": "ReAct",
        }
        req = Request(f"{self.base_url}{path}", data=data, headers=headers)
        try:
            with urlopen(req, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            try:
                detail = exc.read().decode("utf-8", errors="replace")[:800]
            except Exception:
                detail = str(exc)
            if exc.code in (401, 403):
                raise RuntimeError(
                    "OpenRouter rejected the API key or account access. Check "
                    "OPENROUTER_API_KEY and your OpenRouter account."
                ) from None
            if exc.code == 402:
                raise RuntimeError(
                    "OpenRouter reports insufficient credits or spending balance. "
                    "Check your account and model pricing."
                ) from None
            raise RuntimeError(f"OpenRouter API error ({exc.code}): {detail}") from None
        except URLError as exc:
            raise RuntimeError(
                f"Could not reach OpenRouter: {getattr(exc, 'reason', exc)}. "
                "Check your internet connection."
            ) from None
        except TimeoutError:
            raise RuntimeError("OpenRouter request timed out. Try again.") from None
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise RuntimeError("OpenRouter returned an unreadable response.") from None

    def list(self) -> dict:
        """Validate connectivity and credentials; return a model list."""
        result = self._request("/models")
        return {"models": result.get("data", [])}

    def show(self, model: str) -> dict:
        """OpenRouter currently uses ReAct's JSON-tool fallback mode."""
        return {"model": model, "capabilities": []}

    def chat(self, *, model: str, messages: list[dict], stream: bool = False, **kwargs) -> dict:
        # ReAct's current agent loop consumes Ollama-shaped responses and parses
        # JSON tool calls from assistant text. Keep this adapter non-streaming
        # and normalize the response rather than adding an SDK dependency.
        payload = {
            "model": model,
            "messages": [
                {"role": m.get("role", "user"), "content": m.get("content", "")}
                for m in messages
                if m.get("role") in {"system", "user", "assistant"}
            ],
            "stream": False,
        }
        result = self._request("/chat/completions", payload)
        choices = result.get("choices") or []
        if not choices:
            raise RuntimeError("OpenRouter returned no model response.")
        message = choices[0].get("message") or {}
        return {
            "message": {"role": "assistant", "content": message.get("content") or ""},
            "done": True,
        }


def get_provider_name() -> str:
    name = os.environ.get("REACT_PROVIDER", "ollama").strip().lower()
    if name not in {"ollama", "openrouter"}:
        raise RuntimeError(
            f"Unsupported REACT_PROVIDER '{name}'. Choose 'ollama' or 'openrouter'."
        )
    return name


def get_client(provider: str | None = None):
    """Return a client for the selected provider."""
    selected = (provider or get_provider_name()).strip().lower()
    if selected == "openrouter":
        return OpenRouterClient()
    if selected == "ollama":
        return ollama.Client()
    raise RuntimeError(f"Unsupported provider '{selected}'. Choose ollama or openrouter.")
