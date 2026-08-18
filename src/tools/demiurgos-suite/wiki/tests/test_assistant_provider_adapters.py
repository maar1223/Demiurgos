# -*- coding: utf-8 -*-
"""Provider adapter contract tests: Ollama/LM Studio, available vs loaded (ONB-2.2)."""

from pathlib import Path
import sys

import pytest

_HERE = Path(__file__).resolve().parent
_WIKI = _HERE.parent
_SUITE = _WIKI.parent
for _path in (str(_WIKI), str(_SUITE)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from assistant_provider_adapters import (  # noqa: E402
    ProviderRegistry,
    candidate_from_payload,
    normalize_model,
)


class TestLocalProviderAdapters:
    """ONB-2.2: Ollama/LM Studio adapters report installed vs loaded, keyless local."""

    def test_ollama_discovery_reports_installed_and_loaded(self):
        calls: list[str] = []

        def transport(method, url, headers):
            calls.append(url)
            if url.endswith("/api/tags"):
                return 200, {"models": [{"name": "llama3:8b"}, {"name": "llava:7b"}]}
            if url.endswith("/api/ps"):
                return 200, {"models": [{"name": "llama3:8b"}]}
            return 404, {}

        registry = ProviderRegistry(transport=transport)
        result = registry.discover({"provider": "ollama"})

        assert result["outcome"] == "discovered"
        assert [model["id"] for model in result["models"]] == ["llama3:8b", "llava:7b"]
        assert result["loaded_models"] == ["llama3:8b"]
        assert result["jit_load_allowed"] is True
        assert any(url.endswith("/api/tags") for url in calls)
        assert any(url.endswith("/api/ps") for url in calls)

    def test_lm_studio_discovery_uses_v0_state_and_v1_jit(self):
        calls: list[str] = []

        def transport(method, url, headers):
            calls.append(url)
            if url.endswith("/api/v0/models"):
                return 200, [
                    {"id": "qwen2.5:7b", "state": "loaded"},
                    {"id": "deepseek-r1:14b", "state": "not-loaded"},
                ]
            if url.endswith("/v1/models"):
                return 200, {"data": [{"id": "qwen2.5:7b"}]}
            return 404, {}

        registry = ProviderRegistry(transport=transport)
        result = registry.discover({"provider": "lm-studio"})

        assert result["outcome"] == "discovered"
        assert result["loaded_models"] == ["qwen2.5:7b"]
        assert result["jit_load_allowed"] is True
        assert any(url.endswith("/api/v0/models") for url in calls)
        assert any(url.endswith("/v1/models") for url in calls)

    def test_local_providers_require_no_key_remote_still_do(self):
        assert candidate_from_payload({"provider": "ollama"}).api_key == ""
        assert candidate_from_payload({"provider": "lm-studio"}).api_key == ""
        assert candidate_from_payload({"provider": "openai"}) is None

        registry = ProviderRegistry(transport=lambda *_: (200, {"models": [{"name": "m"}]}))
        assert registry.validate({"provider": "ollama"})["outcome"] == "validated"

    def test_validate_hits_provider_specific_discovery_endpoint(self):
        seen: list[str] = []

        def transport(method, url, headers):
            seen.append(url)
            return (200, []) if url.endswith("/api/v0/models") else (404, {})

        registry = ProviderRegistry(transport=transport)

        assert registry.validate({"provider": "lm-studio"})["outcome"] == "validated"
        assert seen[-1].endswith("/api/v0/models")

    def test_connection_state_and_load_state_distinguish_available_and_loaded(self):
        def transport(method, url, headers):
            if url.endswith("/api/tags"):
                return 200, {"models": [{"name": "a"}, {"name": "b"}]}
            if url.endswith("/api/ps"):
                return 200, {"models": [{"name": "a"}]}
            return 404, {}

        registry = ProviderRegistry(transport=transport)
        state = registry.connection_state({"provider": "ollama"})

        assert state["outcome"] == "ok"
        assert state["available_models"] == ["a", "b"]
        assert state["loaded_models"] == ["a"]
        assert state["jit_load_allowed"] is True

        loaded = registry.load_state({"provider": "ollama"})
        assert loaded["models"] == [{"id": "a", "loaded": True}, {"id": "b", "loaded": False}]

    def test_remote_connection_state_marks_all_available_and_loaded(self):
        registry = ProviderRegistry(transport=lambda *_: (200, {"data": [{"id": "m1"}, {"id": "m2"}]}))
        state = registry.connection_state({"provider": "openai", "api_key": "fixture-secret-value"})

        assert state["outcome"] == "ok"
        assert state["available_models"] == ["m1", "m2"]
        assert state["loaded_models"] == ["m1", "m2"]
        assert state["jit_load_allowed"] is False

    def test_normalize_model_accepts_name_style_items(self):
        model = normalize_model({"name": "llama3:8b", "capabilities": ["multimodal"]})

        assert model == {"id": "llama3:8b", "label": "llama3:8b", "capability": "multimodal", "pricing": None}


