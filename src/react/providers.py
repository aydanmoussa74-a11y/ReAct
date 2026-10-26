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


# Providers with an OpenAI-compatible chat-completions endpoint. API keys are
# read from environment variables only; they are never persisted by ReAct.
PROVIDER_CATALOG = {
    "openrouter": {
        "label": "OpenRouter",
        "base_url": "https://openrouter.ai/api/v1",
        "key_env": "OPENROUTER_API_KEY",
        "url": "https://openrouter.ai/keys",
        "default_model": "openrouter/auto",
    },
    "openai": {
        "label": "OpenAI",
        "base_url": "https://api.openai.com/v1",
        "key_env": "OPENAI_API_KEY",
        "url": "https://platform.openai.com/api-keys",
        "default_model": "gpt-4.1-mini",
    },
    "groq": {
        "label": "Groq",
        "base_url": "https://api.groq.com/openai/v1",
        "key_env": "GROQ_API_KEY",
        "url": "https://console.groq.com/keys",
        "default_model": "llama-3.3-70b-versatile",
    },
    "google": {
        "label": "Google Gemini (OpenAI-compatible endpoint)",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "key_env": "GOOGLE_API_KEY",
        "url": "https://aistudio.google.com/apikey",
        "default_model": "gemini-2.5-flash",
    },
    "deepseek": {
        "label": "DeepSeek",
        "base_url": "https://api.deepseek.com",
        "key_env": "DEEPSEEK_API_KEY",
        "url": "https://platform.deepseek.com/api_keys",
        "default_model": "deepseek-chat",
    },
    "mistral": {
        "label": "Mistral AI",
        "base_url": "https://api.mistral.ai/v1",
        "key_env": "MISTRAL_API_KEY",
        "url": "https://console.mistral.ai/api-keys/",
        "default_model": "mistral-small-latest",
    },
    "together": {
        "label": "Together AI",
        "base_url": "https://api.together.xyz/v1",
        "key_env": "TOGETHER_API_KEY",
        "url": "https://api.together.ai/settings/api-keys",
        "default_model": "meta-llama/Llama-3.3-70B-Instruct-Turbo",
    },
    "fireworks": {
        "label": "Fireworks AI",
        "base_url": "https://api.fireworks.ai/inference/v1",
        "key_env": "FIREWORKS_API_KEY",
        "url": "https://fireworks.ai/account/api-keys",
        "default_model": "accounts/fireworks/models/llama-v3p3-70b-instruct",
    },
    "cerebras": {
        "label": "Cerebras",
        "base_url": "https://api.cerebras.ai/v1",
        "key_env": "CEREBRAS_API_KEY",
        "url": "https://cloud.cerebras.ai/",
        "default_model": "llama-3.3-70b",
    },
    "xai": {
        "label": "xAI",
        "base_url": "https://api.x.ai/v1",
        "key_env": "XAI_API_KEY",
        "url": "https://console.x.ai/",
        "default_model": "grok-3-mini",
    },
    "custom": {
        "label": "Custom OpenAI-compatible endpoint",
        "base_url_env": "REACT_BASE_URL",
        "key_env": "REACT_API_KEY",
        "url": "https://platform.openai.com/docs/api-reference",
        "default_model": "",
    },
}


class OpenAICompatibleClient:
    """Standard-library adapter for OpenAI-compatible chat-completions APIs."""

    def __init__(self, provider: str, api_key: str | None = None, timeout: int = 60):
        if provider not in PROVIDER_CATALOG:
            raise RuntimeError(f"Unsupported API provider: {provider}")
        self.provider = provider
        self.config = PROVIDER_CATALOG[provider]
        key_name = self.config["key_env"]
        self.api_key = api_key or os.environ.get(key_name, "")
        self.timeout = timeout
        base_env = self.config.get("base_url_env")
        self.base_url = (os.environ.get(base_env, "") if base_env else self.config.get("base_url", "")).rstrip("/")
        if not self.base_url:
            raise RuntimeError("Custom endpoint needs REACT_BASE_URL, e.g. https://api.example.com/v1")
        if not self.api_key:
            raise RuntimeError(
                f"{self.config['label']} API key missing. Set {key_name}; "
                f"get a key at {self.config['url']}. Never commit or share API keys."
            )

    def _request(self, path: str, payload: dict | None = None) -> dict:
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        if self.provider == "openrouter":
            headers.update({"HTTP-Referer": "https://github.com/aydanmoussa74-a11y/ReAct", "X-Title": "ReAct"})
        req = Request(f"{self.base_url}{path}", data=data, headers=headers)
        try:
            with urlopen(req, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            if exc.code in (401, 403):
                raise RuntimeError(f"{self.config['label']} rejected the API key or account access. Check {self.config['key_env']}.") from None
            if exc.code == 402:
                raise RuntimeError(f"{self.config['label']} reports insufficient credits or spending balance.") from None
            raise RuntimeError(f"{self.config['label']} API error ({exc.code}): {detail}") from None
        except URLError as exc:
            raise RuntimeError(f"Could not reach {self.config['label']}: {getattr(exc, 'reason', exc)}") from None
        except TimeoutError:
            raise RuntimeError(f"{self.config['label']} request timed out. Try again.") from None
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise RuntimeError(f"{self.config['label']} returned an unreadable response.") from None

    def list(self) -> dict:
        try:
            result = self._request("/models")
            return {"models": result.get("data", [])}
        except RuntimeError:
            # Some compatible endpoints do not expose a models-list route.
            return {"models": []}

    def show(self, model: str) -> dict:
        return {"model": model, "capabilities": []}

    def chat(self, *, model: str, messages: list[dict], stream: bool = False, **kwargs) -> dict:
        normalized = []
        for item in messages:
            role = item.get("role", "user")
            if role == "tool":
                normalized.append({"role": "user", "content": "[ReAct tool result]\\n" + str(item.get("content", ""))})
            elif role in {"system", "user", "assistant"}:
                normalized.append({"role": role, "content": item.get("content", "")})
        result = self._request("/chat/completions", {"model": model, "messages": normalized, "stream": False})
        choices = result.get("choices") or []
        if not choices:
            raise RuntimeError(f"{self.config['label']} returned no model response.")
        content = (choices[0].get("message") or {}).get("content") or ""
        if not isinstance(content, str):
            content = json.dumps(content, ensure_ascii=False)
        return {"message": {"role": "assistant", "content": content}, "done": True}


class OpenRouterClient(OpenAICompatibleClient):
    """Backward-compatible OpenRouter client name."""

    def __init__(self, api_key: str | None = None, timeout: int = 60):
        super().__init__("openrouter", api_key=api_key, timeout=timeout)


def get_provider_name() -> str:
    name = os.environ.get("REACT_PROVIDER", "ollama").strip().lower()
    if name not in {"ollama", *PROVIDER_CATALOG.keys()}:
        options = ", ".join(["ollama", *PROVIDER_CATALOG.keys()])
        raise RuntimeError(f"Unsupported REACT_PROVIDER '{name}'. Choose one of: {options}")
    return name


def get_client(provider: str | None = None):
    """Return a client for the selected local or hosted provider."""
    selected = (provider or get_provider_name()).strip().lower()
    if selected == "ollama":
        return ollama.Client()
    if selected in PROVIDER_CATALOG:
        return OpenRouterClient() if selected == "openrouter" else OpenAICompatibleClient(selected)
    raise RuntimeError(f"Unsupported provider '{selected}'.")
