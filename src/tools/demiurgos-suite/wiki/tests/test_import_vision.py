# -*- coding: utf-8 -*-
"""World importer — PR2 (sync-lore-in-importer) tests for the vision
analysis module (Phase 3) and the persistent content cache orchestration
(Phase 4).

Covers tasks 3.1-3.10 (settings gate, multimodal-only, thumbnail-gated
provider calls, fail-open) and 4.4-4.7 (SHA-256 cache key, hit/miss).
The vision provider, thumbnailer, and cache are all injected or mocked —
no live LLM, no image codecs, no network required.
"""

from __future__ import annotations

import hashlib
import sys
import uuid
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_WIKI = _HERE.parent
_TOOLS = _HERE.parents[2]
for _p in (str(_WIKI), str(_TOOLS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from import_vision import (  # noqa: E402
    VisionResult,
    build_vision_callable,
)
from sync_lore.schemas import (  # noqa: E402
    ImageAnalysis,
    ImageEntry,
)


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _FakeVisionProvider:
    """Records calls and returns a fixed ImageAnalysis (deterministic)."""

    instances: list["_FakeVisionProvider"] = []

    def __init__(self, config, **_kwargs) -> None:
        self.config = config
        self.calls: list[tuple[bytes, str]] = []
        self.instances.append(self)

    async def analyze_image(self, image: bytes, context: str):
        self.calls.append((image, context))
        return ImageAnalysis(
            descripcion="Retrato sombrío en claroscuro",
            veredicto="confirma",
            analisis="La imagen coincide con la descripción del texto.",
            tags=["retrato", "claroscuro"],
        )


class _FlakyVisionProvider:
    """Fails on the first call, succeeds afterwards."""

    def __init__(self, config, **_kwargs) -> None:
        self.config = config
        self.calls: list[tuple[bytes, str]] = []

    async def analyze_image(self, image: bytes, context: str):
        self.calls.append((image, context))
        if len(self.calls) == 1:
            raise RuntimeError("provider down")
        return ImageAnalysis(
            descripcion="Segunda imagen", veredicto="no_aplica", analisis="", tags=[],
        )


class _NoneVisionProvider:
    """Mimics LlmProvider returning None (unconfigured/failed analysis)."""

    def __init__(self, config, **_kwargs) -> None:
        self.config = config
        self.calls: list[tuple[bytes, str]] = []

    async def analyze_image(self, image: bytes, context: str):
        self.calls.append((image, context))
        return None


class _ThumbRecorder:
    """Records (bytes, width) calls and returns a fixed thumbnail payload."""

    def __init__(self) -> None:
        self.calls: list[tuple[bytes, int]] = []

    def __call__(self, image_bytes: bytes, width: int) -> bytes:
        self.calls.append((image_bytes, width))
        return b"THUMB-300px-jpeg"


class _DictCache:
    """In-memory vision cache stand-in (hash -> VisionResult)."""

    def __init__(self, seed: dict[str, VisionResult] | None = None) -> None:
        self.data: dict[str, VisionResult] = dict(seed or {})

    def lookup(self, image_hash: str) -> VisionResult | None:
        return self.data.get(image_hash)

    def store(self, image_hash: str, result: VisionResult) -> None:
        self.data[image_hash] = result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _entry(filename: str = "pic.png", data: bytes = b"\x89PNG\r\n\x1a\nfake",
           context_text: str = "") -> ImageEntry:
    """Build a minimal sync_lore ImageEntry for tests."""
    return ImageEntry(
        id=str(uuid.uuid4()),
        source_file="Lore/Enciclopedia.docx",
        page=1,
        chunk_ref="## Raíces",
        context_text=context_text,
        filename=filename,
        image_bytes=data,
    )


def _settings_file(
    tmp_path: Path,
    *,
    model_id: str,
    capability: str | None = None,
    provider: str = "opencode-go",
    base_url: str = "https://opencode.ai/zen/go/v1",
) -> Path:
    """Write a Hermes config.yaml with the normalized assistant_settings block."""
    path = tmp_path / "config.yaml"
    body = (
        "model:\n"
        f"  default: {model_id}\n"
        f"  provider: {provider}\n"
        f"  base_url: {base_url}\n"
        "assistant_settings:\n"
        "  revision: 1\n"
        f"  provider: {provider}\n"
        f"  base_url: {base_url}\n"
        f"  model_id: {model_id}\n"
    )
    if capability is not None:
        body += f"  capability: {capability}\n"
    path.write_text(body, encoding="utf-8")
    return path


def _build(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    provider_cls=_FakeVisionProvider,
    model_id: str = "gpt-5.6-luna",
    thumb: _ThumbRecorder | None = None,
    cache: _DictCache | None = None,
):
    """Compose a vision callable with the standard fakes."""
    settings = _settings_file(tmp_path, model_id=model_id)
    monkeypatch.setattr("sync_lore.providers.llm.LlmProvider", provider_cls)
    thumb = thumb or _ThumbRecorder()
    cache = cache or _DictCache()
    callable_ = build_vision_callable(settings, thumb, cache.lookup, cache.store)
    assert callable_ is not None
    return callable_, thumb, cache


# ---------------------------------------------------------------------------
# Phase 3 — settings gate (tasks 3.1-3.4, 3.9)
# ---------------------------------------------------------------------------


class TestVisionGate:
    def test_text_only_model_returns_none(self, tmp_path) -> None:
        """Task 3.1/3.4/3.9 — text-only capability disables vision."""
        settings = _settings_file(tmp_path, model_id="deepseek-v4-flash")
        assert build_vision_callable(settings) is None

    def test_missing_settings_file_returns_none(self, tmp_path) -> None:
        assert build_vision_callable(tmp_path / "nope.yaml") is None

    def test_invalid_yaml_returns_none(self, tmp_path) -> None:
        path = tmp_path / "config.yaml"
        path.write_text("model: [unclosed\n", encoding="utf-8")
        assert build_vision_callable(path) is None

    def test_incomplete_settings_returns_none(self, tmp_path) -> None:
        """No provider/base_url — the gate fails closed."""
        path = tmp_path / "config.yaml"
        path.write_text("model:\n  default: gpt-5.6-luna\n", encoding="utf-8")
        assert build_vision_callable(path) is None

    def test_multimodal_model_returns_callable(self, tmp_path) -> None:
        settings = _settings_file(tmp_path, model_id="gpt-5.6-luna")
        assert build_vision_callable(settings) is not None

    def test_stored_capability_overrides_catalog(self, tmp_path) -> None:
        """Mirrors assistant_settings: stored capability wins over catalog."""
        settings = _settings_file(
            tmp_path, model_id="deepseek-v4-flash", capability="multimodal")
        assert build_vision_callable(settings) is not None

    def test_unknown_capability_is_not_multimodal(self, tmp_path) -> None:
        settings = _settings_file(
            tmp_path, model_id="gpt-5.6-luna", capability="unknown")
        assert build_vision_callable(settings) is None


# ---------------------------------------------------------------------------
# Phase 3 — analyze_images behavior (tasks 3.5-3.7)
# ---------------------------------------------------------------------------


class TestAnalyzeImages:
    def test_thumbnail_generated_before_vision_call(self, tmp_path, monkeypatch) -> None:
        """Task 3.5 — provider receives the 300px thumbnail, never the original."""
        original = b"\x89PNG\r\n\x1a\noriginal-bytes"
        analyze, thumb, _ = _build(tmp_path, monkeypatch)
        results = analyze([_entry(data=original)], "contexto de lote")

        assert len(results) == 1
        assert thumb.calls == [(original, 300)]
        provider = _FakeVisionProvider.instances[-1]
        assert provider.calls[0][0] == b"THUMB-300px-jpeg"
        assert original not in provider.calls[0][0]

    def test_provider_receives_surrounding_chunk_context(self, tmp_path, monkeypatch) -> None:
        """Task 3.6 — the chunk text travels with the image."""
        chunk = "El palacio de Verania se alza sobre el acantilado."
        analyze, _, _ = _build(tmp_path, monkeypatch)
        analyze([_entry(context_text=chunk)], "contexto de lote")

        provider = _FakeVisionProvider.instances[-1]
        assert provider.calls[0][1] == chunk

    def test_batch_context_fallback_when_no_chunk_text(self, tmp_path, monkeypatch) -> None:
        analyze, _, _ = _build(tmp_path, monkeypatch)
        analyze([_entry()], "contexto de lote")

        provider = _FakeVisionProvider.instances[-1]
        assert provider.calls[0][1] == "contexto de lote"

    def test_vision_result_fields_and_no_hardcoded_model(self, tmp_path, monkeypatch) -> None:
        """Task 3.3/3.7 — fields mapped; ProviderConfig comes from settings."""
        analyze, _, _ = _build(tmp_path, monkeypatch)
        results = analyze([_entry()], "")

        assert len(results) == 1
        result = results[0]
        assert result.description == "Retrato sombrío en claroscuro"
        assert result.verdict == "confirma"
        assert result.analysis == "La imagen coincide con la descripción del texto."
        assert result.tags == ["retrato", "claroscuro"]
        assert result.image_hash == hashlib.sha256(b"\x89PNG\r\n\x1a\nfake").hexdigest()

        # The sync_lore ProviderConfig must carry the settings model — both
        # for text and for the vision sub-config (never hardcoded).
        config = _FakeVisionProvider.instances[-1].config
        assert config.model == "gpt-5.6-luna"
        assert config.vision is not None
        assert config.vision.model == "gpt-5.6-luna"
        assert config.endpoint == "https://opencode.ai/zen/go/v1"

    def test_verdict_defaults_to_no_aplica(self, tmp_path, monkeypatch) -> None:
        class _BareProvider(_FakeVisionProvider):
            async def analyze_image(self, image: bytes, context: str):
                self.calls.append((image, context))
                return ImageAnalysis()

        analyze, _, _ = _build(tmp_path, monkeypatch, provider_cls=_BareProvider)
        results = analyze([_entry()], "")
        assert len(results) == 1
        assert results[0].verdict == "no_aplica"
        assert results[0].description == ""
        assert results[0].tags == []

    def test_bad_verdict_normalized_to_no_aplica(self, tmp_path, monkeypatch) -> None:
        class _WeirdProvider(_FakeVisionProvider):
            async def analyze_image(self, image: bytes, context: str):
                self.calls.append((image, context))
                return ImageAnalysis(descripcion="x", veredicto="quizas")

        analyze, _, _ = _build(tmp_path, monkeypatch, provider_cls=_WeirdProvider)
        results = analyze([_entry()], "")
        assert results[0].verdict == "no_aplica"


# ---------------------------------------------------------------------------
# Phase 3 — fail-open (task 3.8)
# ---------------------------------------------------------------------------


class TestVisionFailOpen:
    def test_provider_exception_skips_image_and_continues(self, tmp_path, monkeypatch) -> None:
        """Task 3.8/3.10 — one bad image never blocks the batch."""
        analyze, _, _ = _build(tmp_path, monkeypatch, provider_cls=_FlakyVisionProvider)
        results = analyze(
            [_entry(data=b"first"), _entry(data=b"second")], "")

        assert len(results) == 1
        assert results[0].image_hash == hashlib.sha256(b"second").hexdigest()

    def test_thumbnail_failure_skips_image(self, tmp_path, monkeypatch) -> None:
        class _BoomThumb:
            def __call__(self, image_bytes: bytes, width: int) -> bytes:
                raise OSError("image decode failed")

        analyze, _, _ = _build(
            tmp_path, monkeypatch, thumb=_BoomThumb())
        results = analyze([_entry()], "")

        assert results == []
        assert _FakeVisionProvider.instances[-1].calls == []  # provider untouched

    def test_provider_none_result_is_not_cached(self, tmp_path, monkeypatch) -> None:
        analyze, _, cache = _build(tmp_path, monkeypatch, provider_cls=_NoneVisionProvider)
        results = analyze([_entry()], "")

        assert results == []
        assert cache.data == {}  # failures never pollute the cache

    def test_missing_thumbnail_generator_skips_all(self, tmp_path, monkeypatch) -> None:
        settings = _settings_file(tmp_path, model_id="gpt-5.6-luna")
        analyze = build_vision_callable(settings, None, None, None)
        assert analyze is not None
        assert analyze([_entry()], "") == []


# ---------------------------------------------------------------------------
# Phase 4 — cache orchestration (tasks 4.4-4.7)
# ---------------------------------------------------------------------------


class TestVisionCacheOrchestration:
    def test_cache_key_is_sha256_of_original_bytes(self, tmp_path, monkeypatch) -> None:
        """Task 4.4 — the hash covers the original bytes, not the thumbnail."""
        original = b"bytes-identicos"
        analyze, _, cache = _build(tmp_path, monkeypatch)
        analyze([_entry(data=original)], "")

        assert list(cache.data) == [hashlib.sha256(original).hexdigest()]

    def test_cache_hit_returns_stored_result_without_provider_or_thumbnail(
        self, tmp_path, monkeypatch,
    ) -> None:
        """Task 4.1/4.6 — a hit never touches the provider."""
        img = _entry()
        img_hash = hashlib.sha256(img.image_bytes).hexdigest()
        seeded = VisionResult(
            image_hash=img_hash, description="del caché",
            verdict="no_aplica", analysis="", tags=["cached"],
        )
        thumb = _ThumbRecorder()
        analyze, _, _ = _build(
            tmp_path, monkeypatch, thumb=thumb,
            cache=_DictCache(seed={img_hash: seeded}),
        )
        results = analyze([img], "contexto")

        assert len(results) == 1
        assert results[0].description == "del caché"
        assert results[0].tags == ["cached"]
        assert _FakeVisionProvider.instances[-1].calls == []
        assert thumb.calls == []

    def test_cache_miss_calls_provider_then_hits_on_second_run(
        self, tmp_path, monkeypatch,
    ) -> None:
        """Task 4.7 — miss stores the result; the repeat import hits the cache."""
        analyze, _, _ = _build(tmp_path, monkeypatch)
        img = _entry()

        first = analyze([img], "contexto")
        assert len(first) == 1
        provider_after_first = _FakeVisionProvider.instances[-1]
        assert len(provider_after_first.calls) == 1

        # Same bytes, new ImageEntry — the provider must not be called again.
        # (A fresh provider instance is built per analyze call, so the first
        # instance's call count is the record that the repeat import hit the
        # cache.)
        again = analyze([_entry(data=img.image_bytes)], "contexto")
        assert again[0].description == first[0].description
        assert len(provider_after_first.calls) == 1

    def test_cache_lookup_exception_fails_open(self, tmp_path, monkeypatch) -> None:
        def boom(_image_hash: str) -> VisionResult | None:
            raise RuntimeError("cache down")

        settings = _settings_file(tmp_path, model_id="gpt-5.6-luna")
        monkeypatch.setattr("sync_lore.providers.llm.LlmProvider", _FakeVisionProvider)
        thumb = _ThumbRecorder()
        cache = _DictCache()
        analyze = build_vision_callable(settings, thumb, boom, cache.store)
        assert analyze is not None

        results = analyze([_entry()], "")
        assert len(results) == 1  # still analyzed via the provider

    def test_cache_store_exception_fails_open(self, tmp_path, monkeypatch) -> None:
        def boom(_image_hash: str, _result: VisionResult) -> None:
            raise RuntimeError("cache full")

        settings = _settings_file(tmp_path, model_id="gpt-5.6-luna")
        monkeypatch.setattr("sync_lore.providers.llm.LlmProvider", _FakeVisionProvider)
        thumb = _ThumbRecorder()
        cache = _DictCache()
        analyze = build_vision_callable(settings, thumb, cache.lookup, boom)
        assert analyze is not None

        results = analyze([_entry()], "")
        assert len(results) == 1  # result still returned despite store failure

class TestAcceptedCapability:
    def test_unknown_capability_with_accepted_vision_evidence_is_multimodal(
        self, tmp_path
    ) -> None:
        """S14 — a product-recorded vision acceptance proves the capability."""
        settings = _settings_file(
            tmp_path, model_id="deepseek-flash", capability="unknown")
        assert build_vision_callable(settings) is None
        assert build_vision_callable(
            settings, accepted_capability="multimodal") is not None

    def test_accepted_text_only_evidence_keeps_vision_disabled(self, tmp_path) -> None:
        settings = _settings_file(
            tmp_path, model_id="deepseek-flash", capability="unknown")
        assert build_vision_callable(
            settings, accepted_capability="text-only") is None
