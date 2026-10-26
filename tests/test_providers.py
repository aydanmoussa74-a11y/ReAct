"""Tests for the provider adapters."""
from __future__ import annotations

import json
from io import BytesIO

import pytest

from react.providers import OpenRouterClient


def test_openrouter_requires_api_key(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="OPENROUTER_API_KEY"):
        OpenRouterClient()


def test_openrouter_chat_normalizes_response(monkeypatch):
    client = OpenRouterClient(api_key="test-key")

    def fake_request(path, payload=None):
        assert path == "/chat/completions"
        assert payload["model"] == "openrouter/auto"
        assert payload["stream"] is False
        return {"choices": [{"message": {"role": "assistant", "content": "DONE: hello"}}]}

    monkeypatch.setattr(client, "_request", fake_request)
    response = client.chat(
        model="openrouter/auto",
        messages=[{"role": "system", "content": "system"}, {"role": "user", "content": "hi"}],
        stream=True,
    )
    assert response == {
        "message": {"role": "assistant", "content": "DONE: hello"},
        "done": True,
    }


def test_openrouter_auth_error_is_actionable(monkeypatch):
    from urllib.error import HTTPError

    client = OpenRouterClient(api_key="invalid")
    def fail(*args, **kwargs):
        raise HTTPError("https://openrouter.ai", 401, "Unauthorized", {}, BytesIO(b"secret detail"))

    monkeypatch.setattr("react.providers.urlopen", fail)
    with pytest.raises(RuntimeError, match="rejected the API key"):
        client._request("/models")



def test_openai_requires_api_key(monkeypatch):
    from react.providers import OpenAIClient

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        OpenAIClient()


def test_gemini_requires_api_key(monkeypatch):
    from react.providers import GeminiClient

    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        GeminiClient()


def test_openai_chat_normalizes_response(monkeypatch):
    from react.providers import OpenAIClient

    client = OpenAIClient(api_key="test-key")

    def fake_request(url, *, headers, payload=None):
        assert url.endswith("/chat/completions")
        assert payload["model"] == "gpt-4.1-mini"
        assert payload["stream"] is False
        return {"choices": [{"message": {"role": "assistant", "content": "DONE: hello"}}]}

    monkeypatch.setattr(client, "_json_request", fake_request)
    response = client.chat(
        model="gpt-4.1-mini",
        messages=[{"role": "system", "content": "system"}, {"role": "user", "content": "hi"}],
        stream=True,
    )
    assert response == {"message": {"role": "assistant", "content": "DONE: hello"}, "done": True}


def test_gemini_chat_normalizes_response(monkeypatch):
    from react.providers import GeminiClient

    client = GeminiClient(api_key="test-key")

    def fake_call(path, payload=None):
        assert path == "/models/gemini-2.5-flash:generateContent"
        assert payload["contents"][-1]["parts"][0]["text"] == "hi"
        return {"candidates": [{"content": {"parts": [{"text": "DONE: hello"}]}}]}

    monkeypatch.setattr(client, "_call", fake_call)
    response = client.chat(
        model="gemini-2.5-flash",
        messages=[{"role": "system", "content": "system"}, {"role": "user", "content": "hi"}],
        stream=True,
    )
    assert response == {"message": {"role": "assistant", "content": "DONE: hello"}, "done": True}


def test_provider_selection_accepts_all_supported_providers(monkeypatch):
    from react.providers import get_provider_name

    for provider in ("ollama", "openrouter", "openai", "gemini"):
        monkeypatch.setenv("REACT_PROVIDER", provider)
        assert get_provider_name() == provider
