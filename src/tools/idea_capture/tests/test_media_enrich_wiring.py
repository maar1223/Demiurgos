"""Media enrichment wiring tests (SDD idea-capture-ai-gate, Phase 3, R-5).

Covers the production wiring: in ``ai`` mode ``register()`` builds the FULL
``MediaEnrichProvider`` and injects it into the handler/runtime; in ``strict``
mode the runtime's text-only ``_default_enrich`` fallback is kept (R-5). Also
covers the expanded processor seam (``media_kind`` / ``media_path`` / ``mime``
reach the provider, legacy single-arg providers still work) and the spec
scenarios S-5.3 (image + vision off -> caption + sin_clasificar), S-5.5
(audio unavailable -> empty body, raw retained), and S-5.7 (voice fails with
no caption -> RETRYABLE with ``enrichment produced empty idea``).
"""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import types
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_TOOLS = Path(__file__).resolve().parents[2]  # src/tools
for _p in (str(_TOOLS),):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from idea_capture.config import CaptureConfig, CaptureLimits  # noqa: E402
from idea_capture.enrich import DEFAULT_TYPE, MediaEnrichProvider  # noqa: E402
from idea_capture.hermes_handler import build_language_resolver  # noqa: E402
from idea_capture.models import (  # noqa: E402
    CaptureState,
    MediaInput,
    MediaKind,
    TelegramUpdate,
    WorldAction,
)
from idea_capture.runtime import IdeaCaptureRuntime  # noqa: E402
from idea_capture.telegram import IngressPolicy  # noqa: E402

_PLUGIN_PATH = (
    Path(__file__).resolve().parents[4]
    / ".hermes" / "plugins" / "demiurgos-idea-capture" / "__init__.py"
)

_IMAGE_BYTES = b"\x89PNG\r\n\x1a\nraw-image"
_VOICE_BYTES = b"OggS\x01fake-voice"


def _runtime(root: Path, enrich):
    (root / "mundos" / "vibrantes").mkdir(parents=True)
    policy = IngressPolicy(
        frozenset(), {},
        authorized_bindings=frozenset({"telegram:7:8:default"}),
        require_binding=True,
    )
    return IdeaCaptureRuntime(
        config=CaptureConfig(policy, CaptureLimits()),
        state_path=root / "capture.sqlite3",
        mundos_root=root / "mundos",
        active_world="vibrantes",
        enrich=enrich,
        global_ideas_root=root / "ideas",
    )


def _voice_update(update_id: int, audio_path: str, caption: str = ""):
    return TelegramUpdate(
        update_id, 7, 8, False,
        MediaInput(MediaKind.VOICE, data=_VOICE_BYTES,
                   mime="audio/ogg", duration_seconds=30, path=audio_path,
                   text=caption),
    )


def _image_update(update_id: int, caption: str = ""):
    return TelegramUpdate(
        update_id, 7, 8, False,
        MediaInput(MediaKind.IMAGE, data=_IMAGE_BYTES,
                   mime="image/png", text=caption),
    )


# ---------------------------------------------------------------------------
# Processor seam: media_kind/media_path/mime reach the provider (S-5.4)
# ---------------------------------------------------------------------------


class TestProcessorSeamWiring:
    def test_voice_capture_reaches_provider_with_media_context(self, tmp_path):
        audio = tmp_path / "voice.ogg"
        audio.write_bytes(_VOICE_BYTES)
        seen = {}

        def transcribe_fn(path, language):
            seen["path"] = path
            seen["language"] = language
            return "una idea hablada"

        def hermes_fn(raw):
            seen["classified"] = str(raw)
            return "concepto"

        provider = MediaEnrichProvider(
            hermes=hermes_fn,
            transcribe_fn=transcribe_fn,
            language_resolver=lambda: "es",
        )
        runtime = _runtime(tmp_path, provider)
        try:
            receipt = runtime.service.accept(_voice_update(1, str(audio)))
            runtime.confirm(receipt.capture_id, WorldAction.SAVE_GLOBAL)
            saved = runtime.wait_state(receipt.capture_id, CaptureState.SAVED)

            content = (tmp_path / "ideas" / f"{saved.slug}.md").read_text(encoding="utf-8")
            assert "una idea hablada" in content
            assert "type: concepto" in content
            # The seam passes the persisted media path + kind + mime through.
            assert seen["path"] == str(audio)
            assert seen["language"] == "es"
            assert seen["classified"] == "una idea hablada"
        finally:
            runtime.close()

    def test_legacy_single_arg_enrich_still_works(self, tmp_path):
        # Providers that predate the seam accept only the raw input; the
        # processor retries without the seam keywords instead of crashing.
        runtime = _runtime(tmp_path, lambda raw: (str(raw).strip(), "sin_clasificar"))
        try:
            receipt = runtime.service.accept(
                TelegramUpdate(1, 7, 8, False, MediaInput(MediaKind.TEXT, text="idea")))
            runtime.confirm(receipt.capture_id, WorldAction.SAVE_GLOBAL)
            saved = runtime.wait_state(receipt.capture_id, CaptureState.SAVED)
            assert saved.state is CaptureState.SAVED
        finally:
            runtime.close()

    def test_internal_provider_typeerror_is_not_masked(self, tmp_path):
        def broken(raw, **kwargs):
            raise TypeError("internal bug, not a rejected keyword")

        runtime = _runtime(tmp_path, broken)
        try:
            receipt = runtime.service.accept(
                TelegramUpdate(1, 7, 8, False, MediaInput(MediaKind.TEXT, text="idea")))
            runtime.confirm(receipt.capture_id, WorldAction.SAVE_GLOBAL)
            with pytest.raises(TypeError):
                runtime.processor.process(receipt.capture_id)
        finally:
            runtime.close()


# ---------------------------------------------------------------------------
# Spec scenarios through the runtime: caption fallback (S-5.3 / S-5.5 / S-5.7)
# ---------------------------------------------------------------------------


class TestCaptionFallback:
    def test_image_vision_off_keeps_caption_and_sin_clasificar(self, tmp_path):
        """S-5.3: image + vision disabled -> body is the caption, type sin_clasificar."""
        provider = MediaEnrichProvider(vision_enabled=False)
        runtime = _runtime(tmp_path, provider)
        try:
            receipt = runtime.service.accept(
                _image_update(1, caption="el castillo al amanecer"))
            runtime.confirm(receipt.capture_id, WorldAction.SAVE_GLOBAL)
            saved = runtime.wait_state(receipt.capture_id, CaptureState.SAVED)
            assert saved.state is CaptureState.SAVED
            content = (tmp_path / "ideas" / f"{saved.slug}.md").read_text(encoding="utf-8")
            assert "el castillo al amanecer" in content
            assert "type: sin_clasificar" in content
        finally:
            runtime.close()

    def test_voice_transcription_unavailable_keeps_caption(self, tmp_path):
        """S-5.5 + S-5.7: voice fails open; a caption keeps the capture SAVED."""
        audio = tmp_path / "voice.ogg"
        audio.write_bytes(_VOICE_BYTES)
        provider = MediaEnrichProvider(transcribe_fn=None)
        runtime = _runtime(tmp_path, provider)
        try:
            receipt = runtime.service.accept(
                _voice_update(1, str(audio), caption="un recuerdo de la corte"))
            runtime.confirm(receipt.capture_id, WorldAction.SAVE_GLOBAL)
            saved = runtime.wait_state(receipt.capture_id, CaptureState.SAVED)
            content = (tmp_path / "ideas" / f"{saved.slug}.md").read_text(encoding="utf-8")
            assert "un recuerdo de la corte" in content
            assert "type: sin_clasificar" in content
        finally:
            runtime.close()

    def test_voice_transcription_fails_without_caption_is_retryable(self, tmp_path):
        """S-5.7: voice transcription fails AND no caption -> RETRYABLE."""
        audio = tmp_path / "voice.ogg"
        audio.write_bytes(_VOICE_BYTES)

        def failing(_path, _language):
            raise RuntimeError("whisper down")

        provider = MediaEnrichProvider(transcribe_fn=failing, language_resolver=lambda: "es")
        runtime = _runtime(tmp_path, provider)
        try:
            receipt = runtime.service.accept(_voice_update(1, str(audio)))
            runtime.confirm(receipt.capture_id, WorldAction.SAVE_GLOBAL)
            record = runtime.wait_state(receipt.capture_id, CaptureState.RETRYABLE)
            assert record.state is CaptureState.RETRYABLE
            assert "enrichment produced empty idea" in record.error
            assert record.raw_bytes == _VOICE_BYTES  # raw media retained
        finally:
            runtime.close()


# ---------------------------------------------------------------------------
# Locale resolver: es / en / unreadable / runtime change
# ---------------------------------------------------------------------------


def _locale_state(tmp_path: Path, conversation: str) -> Path:
    path = tmp_path / "local-state.json"
    path.write_text(json.dumps({
        "schema_version": 1,
        "revision": 0,
        "locale": {
            "ui": conversation,
            "conversation": conversation,
            "content": conversation,
            "region": None,
            "region_explicit": False,
            "iana_timezone": "UTC",
        },
    }), encoding="utf-8")
    return path


class TestLocaleResolver:
    def test_es_locale(self, tmp_path):
        assert build_language_resolver(_locale_state(tmp_path, "es"))() == "es"

    def test_en_locale(self, tmp_path):
        assert build_language_resolver(_locale_state(tmp_path, "en"))() == "en"

    def test_unreadable_locale_fails_closed_to_es(self, tmp_path):
        path = tmp_path / "local-state.json"
        path.write_text("{corrupt", encoding="utf-8")
        assert build_language_resolver(path)() == "es"

    def test_runtime_change_picked_up_per_call(self, tmp_path):
        state = _locale_state(tmp_path, "es")
        resolver = build_language_resolver(state)
        assert resolver() == "es"
        _locale_state(tmp_path, "en")
        assert resolver() == "en"


# ---------------------------------------------------------------------------
# Production plugin wiring (R-5): ai mode builds the provider; strict keeps
# the runtime default.
# ---------------------------------------------------------------------------


class RecordingCtx:
    """Fake PluginContext recording the registration surface."""

    def __init__(self):
        self.hooks = []
        self.tools = []
        self.platforms = []

    def register_hook(self, hook_name, callback):
        self.hooks.append((hook_name, callback))

    def register_tool(self, **kwargs):
        self.tools.append(kwargs)

    def register_platform(self, **kwargs):
        self.platforms.append(kwargs)


def _load_plugin():
    """Load the plugin the way Hermes does: ``hermes_plugins.<slug>`` package."""
    plugin_dir = _PLUGIN_PATH.parent
    module_name = "hermes_plugins.demiurgos_idea_capture"
    if "hermes_plugins" not in sys.modules:
        ns_pkg = types.ModuleType("hermes_plugins")
        ns_pkg.__path__ = []
        ns_pkg.__package__ = "hermes_plugins"
        sys.modules["hermes_plugins"] = ns_pkg
    spec = importlib.util.spec_from_file_location(
        module_name, _PLUGIN_PATH, submodule_search_locations=[str(plugin_dir)])
    module = importlib.util.module_from_spec(spec)
    module.__package__ = module_name
    module.__path__ = [str(plugin_dir)]
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _project_dirs(tmp_path: Path) -> None:
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "idea-capture.yaml").write_text(
        "authorized_bindings: []\n", encoding="utf-8")
    (tmp_path / "mundos").mkdir()
    (tmp_path / "data").mkdir()


class TestProductionWiring:
    def test_ai_mode_wires_media_enrich_provider(self, tmp_path, monkeypatch):
        """R-5: in ai mode register() injects the full provider into the runtime."""
        monkeypatch.setenv("DEMIURGOS_ROOT", str(tmp_path))
        monkeypatch.setenv("DEMIURGOS_IDEA_CAPTURE_MODE", "ai")
        # Opt out of vision so the test isolates the non-vision wiring.
        monkeypatch.setenv("DEMIURGOS_IDEA_CAPTURE_IMAGE_VISION", "0")
        _project_dirs(tmp_path)

        plugin = _load_plugin()
        plugin.register(RecordingCtx())

        provider = plugin._handler.runtime.processor.enrich
        assert isinstance(provider, MediaEnrichProvider)
        # Zero injection builds a REAL Hermes gateway classifier, so TEXT and
        # AUDIO transcripts classify with real taxonomy types and fail open
        # to sin_clasificar when the gateway is unavailable.
        assert provider._hermes._hermes is not None
        assert callable(provider._hermes._hermes)
        assert provider._vision_enabled is False

    def test_ai_mode_wires_vision_when_enabled(self, tmp_path, monkeypatch):
        """R-5: with vision ON (default) the provider attempts real vision wiring."""
        monkeypatch.setenv("DEMIURGOS_ROOT", str(tmp_path))
        monkeypatch.setenv("DEMIURGOS_IDEA_CAPTURE_MODE", "ai")
        monkeypatch.delenv("DEMIURGOS_IDEA_CAPTURE_IMAGE_VISION", raising=False)
        _project_dirs(tmp_path)

        plugin = _load_plugin()
        plugin.register(RecordingCtx())

        provider = plugin._handler.runtime.processor.enrich
        assert isinstance(provider, MediaEnrichProvider)
        assert provider._vision_enabled is True
        # Vision may fail open (no profile / no PIL / no vision modules) but
        # never crashes registration.
        assert provider._vision_fn is None or callable(provider._vision_fn)

    def test_strict_mode_keeps_runtime_default_enrich(self, tmp_path, monkeypatch):
        """R-5: in strict mode the text-only _default_enrich fallback remains."""
        monkeypatch.setenv("DEMIURGOS_ROOT", str(tmp_path))
        monkeypatch.setenv("DEMIURGOS_IDEA_CAPTURE_MODE", "strict")
        _project_dirs(tmp_path)

        plugin = _load_plugin()
        plugin.register(RecordingCtx())

        provider = plugin._handler.runtime.processor.enrich
        assert not isinstance(provider, MediaEnrichProvider)
        assert provider is IdeaCaptureRuntime._default_enrich