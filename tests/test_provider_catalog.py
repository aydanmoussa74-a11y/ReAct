"""Coverage for the OpenAI-compatible provider catalog."""
from __future__ import annotations

import pytest

from react.providers import OpenAICompatibleClient, PROVIDER_CATALOG


@pytest.mark.parametrize("provider", sorted(PROVIDER_CATALOG))
def test_catalog_provider_requires_its_own_key(monkeypatch, provider):
    cfg = PROVIDER_CATALOG[provider]
    monkeypatch.delenv(cfg["key_env"], raising=False)
    if cfg.get("base_url_env"):
        monkeypatch.delenv(cfg["base_url_env"], raising=False)
        with pytest.raises(RuntimeError, match="Custom endpoint needs"):
            OpenAICompatibleClient(provider)
    else:
        with pytest.raises(RuntimeError, match="API key missing"):
            OpenAICompatibleClient(provider)


def test_custom_provider_accepts_custom_base_url(monkeypatch):
    monkeypatch.setenv("REACT_BASE_URL", "https://example.test/v1")
    monkeypatch.setenv("REACT_API_KEY", "test-key")
    client = OpenAICompatibleClient("custom")
    assert client.base_url == "https://example.test/v1"
    assert client.api_key == "test-key"


def test_catalog_has_official_key_link_and_model_defaults():
    for provider, config in PROVIDER_CATALOG.items():
        assert config["label"]
        assert config["url"].startswith("https://")
        assert config["key_env"]
        assert "default_model" in config
