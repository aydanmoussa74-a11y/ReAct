"""Provider selection and stdlib HTTP adapters for ReAct.

Cloud adapters deliberately avoid provider SDK dependencies so ReAct can run in
constrained Python environments such as Android/Termux.
"""
from __future__ import annotations

import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .ollama_compat import ollama


class _HTTPProviderClient:
    """Shared JSON-over-HTTP helper with safe, actionable errors."""

    def __init__(self, timeout: int = 60) -> None:
        self.timeout = timeout

    def _json_request(self, url: str, *, headers: dict[str, str], payload: dict | None = None) -> dict:
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = Request(url, data=data, headers=headers)
        try:
            with urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:600]
            if exc.code in (401, 403):
                raise RuntimeError("Provider rejected the API key or account access. Check the selected provider's key and account.") from None
            if exc.code == 402:
                raise RuntimeError("Provider reports insufficient credits or balance. Check account limits and model pricing.") from None
            if exc.code == 429:
                raise RuntimeError("Provider rate limit or quota reached. Check your usage limits and retry later.") from None
            raise RuntimeError(f"Provider API error ({exc.code}): {detail}") from None
        except URLError as exc:
            raise RuntimeError(f"Could not reach the model provider: {getattr(exc, 'reason', exc)}. Check your internet connection.") from None
        except TimeoutError:
            raise RuntimeError("Model provider request timed out. Try again.") from None
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise RuntimeError("Model provider returned an unreadable response.") from None


def _messages_for_openai(messages: list[dict]) -> list[dict]:
    result = []
    for item in messages:
        role = item.get("role", "user")
        content = str(item.get("content", "") or "")
        if role == "tool":
            result.append({"role": "user", "content": "[ReAct tool result]\n" + content})
        elif role in {"system", "user", "assistant"}:
            result.append({"role": role, "content": content})
    return result


class OpenAIClient(_HTTPProviderClient):
    """OpenAI Chat Completions adapter; ReAct parses tool calls from text."""

    def __init__(self, api_key: str | None = None, timeout: int = 60) -> None:
        super().__init__(timeout)
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self.base_url = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
        if not self.api_key:
            raise RuntimeError("OpenAI API key is missing. Set OPENAI_API_KEY in your terminal session.")

    def list(self) -> dict:
        result = self._json_request(self.base_url + "/models", headers={"Authorization": f"Bearer {self.api_key}"})
        return {"models": result.get("data", [])}

    def show(self, model: str) -> dict:
        return {"model": model, "capabilities": []}

    def chat(self, *, model: str, messages: list[dict], stream: bool = False, **kwargs) -> dict:
        result = self._json_request(
            self.base_url + "/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            payload={"model": model, "messages": _messages_for_openai(messages), "stream": False},
        )
        choices = result.get("choices") or []
        if not choices:
            raise RuntimeError("OpenAI returned no model response.")
        content = (choices[0].get("message") or {}).get("content") or ""
        if not isinstance(content, str):
            content = json.dumps(content, ensure_ascii=False)
        return {"message": {"role": "assistant", "content": content}, "done": True}


class GeminiClient(_HTTPProviderClient):
    """Google Gemini generateContent adapter using the standard-library HTTP stack."""

    def __init__(self, api_key: str | None = None, timeout: int = 60) -> None:
        super().__init__(timeout)
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY", "") or os.environ.get("GOOGLE_API_KEY", "")
        self.base_url = os.environ.get("GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta").rstrip("/")
        if not self.api_key:
            raise RuntimeError("Gemini API key is missing. Set GEMINI_API_KEY in your terminal session.")

    def _call(self, path: str, payload: dict | None = None) -> dict:
        headers = {"x-goog-api-key": self.api_key, "Content-Type": "application/json"}
        return self._json_request(self.base_url + path, headers=headers, payload=payload)

    def list(self) -> dict:
        result = self._call("/models")
        return {"models": [{"model": item.get("name", "").removeprefix("models/")} for item in result.get("models", [])]}

    def show(self, model: str) -> dict:
        return {"model": model, "capabilities": []}

    def chat(self, *, model: str, messages: list[dict], stream: bool = False, **kwargs) -> dict:
        system_parts = []
        contents = []
        for item in messages:
            role = item.get("role", "user")
            content = str(item.get("content", "") or "")
            if role == "system":
                system_parts.append({"text": content})
            elif role == "tool":
                contents.append({"role": "user", "parts": [{"text": "[ReAct tool result]\n" + content}]})
            elif role in {"user", "assistant"}:
                contents.append({"role": "model" if role == "assistant" else "user", "parts": [{"text": content}]})
        payload: dict = {"contents": contents, "generationConfig": {"temperature": 0.2}}
        if system_parts:
            payload["systemInstruction"] = {"parts": system_parts}
        result = self._call(f"/models/{model}:generateContent", payload)
        candidates = result.get("candidates") or []
        if not candidates:
            feedback = result.get("promptFeedback", {}).get("blockReason", "no candidate returned")
            raise RuntimeError(f"Gemini returned no model response ({feedback}).")
        parts = (candidates[0].get("content") or {}).get("parts") or []
        content = "".join(str(part.get("text", "")) for part in parts)
        return {"message": {"role": "assistant", "content": content}, "done": True}


class OpenRouterClient(_HTTPProviderClient):
    """OpenRouter's OpenAI-compatible API adapter."""

    def __init__(self, api_key: str | None = None, timeout: int = 60) -> None:
        super().__init__(timeout)
        self.api_key = api_key or os.environ.get("OPENROUTER_API_KEY", "")
        self.base_url = os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1").rstrip("/")
        if not self.api_key:
            raise RuntimeError("OpenRouter API key is missing. Set OPENROUTER_API_KEY in your terminal session.")

    def _request(self, path: str, payload: dict | None = None) -> dict:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/aydanmoussa74-a11y/ReAct",
            "X-Title": "ReAct",
        }
        return self._json_request(self.base_url + path, headers=headers, payload=payload)

    def list(self) -> dict:
        result = self._request("/models")
        return {"models": result.get("data", [])}

    def show(self, model: str) -> dict:
        return {"model": model, "capabilities": []}

    def chat(self, *, model: str, messages: list[dict], stream: bool = False, **kwargs) -> dict:
        result = self._request("/chat/completions", {
            "model": model, "messages": _messages_for_openai(messages), "stream": False,
        })
        choices = result.get("choices") or []
        if not choices:
            raise RuntimeError("OpenRouter returned no model response.")
        content = (choices[0].get("message") or {}).get("content") or ""
        if not isinstance(content, str):
            content = json.dumps(content, ensure_ascii=False)
        return {"message": {"role": "assistant", "content": content}, "done": True}


CLOUD_DEFAULT_MODELS = {
    "openai": "gpt-4.1-mini",
    "gemini": "gemini-2.5-flash",
    "openrouter": "openrouter/auto",
}


def get_provider_name() -> str:
    name = os.environ.get("REACT_PROVIDER", "ollama").strip().lower()
    if name not in {"ollama", "openrouter", "openai", "gemini"}:
        raise RuntimeError("Unsupported REACT_PROVIDER. Choose ollama, openrouter, openai, or gemini.")
    return name


def get_client(provider: str | None = None):
    selected = (provider or get_provider_name()).strip().lower()
    if selected == "ollama":
        return ollama.Client()
    if selected == "openrouter":
        return OpenRouterClient()
    if selected == "openai":
        return OpenAIClient()
    if selected == "gemini":
        return GeminiClient()
    raise RuntimeError(f"Unsupported provider '{selected}'. Choose ollama, openrouter, openai, or gemini.")
