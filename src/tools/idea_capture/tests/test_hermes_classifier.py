"""Hermes gateway idea classifier tests (SDD idea-capture-ai-gate, Phase 3, R-5).

Covers the production TEXT/AUDIO classifier: the happy path (a gateway label
becomes the idea type through the provider, S-5.1), label normalization,
fail-open when the gateway is unconfigured / errors / times out / returns an
unrecognized or malformed response (always ``sin_clasificar``, never
raises), the cheap-offline build contract (config read at call time, no
network at build), and the production wiring assertion that a zero-injection
``build_media_enrich_provider()`` builds a real (non-None) classifier. The
HTTP layer is mocked — no real gateway is ever contacted.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_TOOLS = Path(__file__).resolve().parents[2]  # src/tools
for _p in (str(_TOOLS),):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from idea_capture.enrich import DEFAULT_TYPE, MediaEnrichProvider  # noqa: E402
from idea_capture.hermes_handler import (  # noqa: E402
    CLASSIFY_PROMPT,
    build_hermes_classifier,
    build_media_enrich_provider,
    _normalize_classified_label,
)
from idea_capture.models import MediaKind  # noqa: E402


def _configured_gateway(monkeypatch, *, label: str = "personaje"):
    """Pin gateway config and stub the HTTP seam with a canned label."""
    monkeypatch.setattr(
        "idea_capture.hermes_handler._gateway_config",
        lambda: ("http://gateway.test/v1/chat/completions", "test-key", 10.0),
    )
    monkeypatch.setattr(
        "idea_capture.hermes_handler._gateway_post",
        lambda url, payload, headers, timeout: {
            "choices": [{"message": {"content": label}}],
        },
    )
    return build_hermes_classifier()


class TestHermesClassifier:
    def test_happy_path_returns_taxonomy_label(self, monkeypatch):
        classify = _configured_gateway(monkeypatch, label="trama")
        assert classify("una conspiración en la corte") == "trama"

    def test_happy_path_through_provider_yields_type(self, monkeypatch):
        classify = _configured_gateway(monkeypatch, label="personaje")
        provider = MediaEnrichProvider(hermes=classify)
        result = provider("un mercenario sombrío", media_kind=MediaKind.TEXT)
        assert result.body == "un mercenario sombrío"
        assert result.type == "personaje"

    def test_prompt_mentions_the_full_taxonomy(self):
        for label in ("personaje", "relacion", "ambientacion",
                      "trama", "concepto", "sin_clasificar"):
            assert label in CLASSIFY_PROMPT

    def test_label_is_trimmed_and_lowercased(self, monkeypatch):
        classify = _configured_gateway(monkeypatch, label="  Ambientacion\n")
        assert classify("un bosque") == "ambientacion"

    def test_unrecognized_label_fails_open(self, monkeypatch):
        classify = _configured_gateway(monkeypatch, label="poesia")
        assert classify("un poema") == DEFAULT_TYPE

    def test_empty_label_fails_open(self, monkeypatch):
        classify = _configured_gateway(monkeypatch, label="")
        assert classify("algo") == DEFAULT_TYPE

    def test_non_string_content_fails_open(self, monkeypatch):
        classify = _configured_gateway(monkeypatch, label="")
        monkeypatch.setattr(
            "idea_capture.hermes_handler._gateway_post",
            lambda *args: {"choices": [{"message": {"content": None}}]},
        )
        assert classify("algo") == DEFAULT_TYPE

    def test_unconfigured_gateway_fails_open_without_network(self, monkeypatch):
        called: list = []
        monkeypatch.setattr(
            "idea_capture.hermes_handler._gateway_config",
            lambda: ("", "", 10.0),
        )
        monkeypatch.setattr(
            "idea_capture.hermes_handler._gateway_post",
            lambda *args: called.append(args) or {"choices": []},
        )
        classify = build_hermes_classifier()
        assert classify("un texto") == DEFAULT_TYPE
        assert called == [], "no network attempt when the gateway is unconfigured"

    def test_gateway_error_fails_open(self, monkeypatch):
        _configured_gateway(monkeypatch, label="personaje")
        monkeypatch.setattr(
            "idea_capture.hermes_handler._gateway_post",
            lambda *args: (_ for _ in ()).throw(RuntimeError("gateway down")),
        )
        classify = build_hermes_classifier()
        assert classify("un texto") == DEFAULT_TYPE

    def test_gateway_timeout_fails_open(self, monkeypatch):
        import httpx

        _configured_gateway(monkeypatch, label="personaje")
        monkeypatch.setattr(
            "idea_capture.hermes_handler._gateway_post",
            lambda *args: (_ for _ in ()).throw(httpx.TimeoutException("timed out")),
        )
        classify = build_hermes_classifier()
        assert classify("un texto") == DEFAULT_TYPE

    def test_malformed_response_fails_open(self, monkeypatch):
        _configured_gateway(monkeypatch, label="personaje")
        monkeypatch.setattr(
            "idea_capture.hermes_handler._gateway_post",
            lambda *args: {"choices": []},
        )
        classify = build_hermes_classifier()
        assert classify("un texto") == DEFAULT_TYPE

    def test_build_is_offline_and_defers_config_to_call_time(self, monkeypatch):
        calls: list = []
        monkeypatch.setattr(
            "idea_capture.hermes_handler._gateway_config",
            lambda: calls.append("config") or ("http://gateway.test/v1", "k", 10.0),
        )
        monkeypatch.setattr(
            "idea_capture.hermes_handler._gateway_post",
            lambda *args: {"choices": [{"message": {"content": "trama"}}]},
        )
        classify = build_hermes_classifier()
        assert calls == [], "building the classifier must not read gateway config"
        assert classify("un texto") == "trama"
        assert calls == ["config"], "config is read at call time, once per call"


class TestClassifierWiring:
    def test_production_provider_builds_real_classifier(self, tmp_path, monkeypatch):
        # Hermetic: no profile and no .env under DEMIURGOS_ROOT, so vision
        # and the gateway both resolve to nothing and fail open.
        monkeypatch.setenv("DEMIURGOS_ROOT", str(tmp_path))
        monkeypatch.setenv("HERMES_HOME", str(tmp_path / "no-such-profile"))
        monkeypatch.delenv("HERMES_GATEWAY_URL", raising=False)
        monkeypatch.delenv("HERMES_GATEWAY_KEY", raising=False)
        monkeypatch.delenv("DEMIURGOS_IDEA_CAPTURE_IMAGE_VISION", raising=False)

        # Zero injection: exactly what the plugin passes in production.
        provider = build_media_enrich_provider()

        assert provider._hermes._hermes is not None
        assert callable(provider._hermes._hermes)
        # Unconfigured gateway -> fail open at call time, never raise.
        result = provider("una idea", media_kind=MediaKind.TEXT)
        assert result.body == "una idea"
        assert result.type == DEFAULT_TYPE

    def test_normalize_classified_label(self):
        assert _normalize_classified_label(" Personaje ") == "personaje"
        assert _normalize_classified_label("poesia") == DEFAULT_TYPE
        assert _normalize_classified_label("") == DEFAULT_TYPE
        assert _normalize_classified_label(None) == DEFAULT_TYPE
        assert _normalize_classified_label(42) == DEFAULT_TYPE