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
