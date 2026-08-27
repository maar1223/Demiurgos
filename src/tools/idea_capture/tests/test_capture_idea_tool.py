"""R-3 tests: the capture_idea tool (ai mode).

The tool is registered only in ``ai`` mode and lets the assistant capture an
idea/seed by calling ``service.accept`` through a synthetic ``TelegramUpdate``
built from the tool payload. It must reject sessions that are not the
authorized capture binding before any accept happens.
"""

import importlib.util
import json
import sys
import tempfile
import types
from pathlib import Path

import idea_capture.hermes_handler as hermes_handler
from idea_capture.config import CaptureConfig, CaptureLimits
from idea_capture.hermes_handler import IdeaCaptureHandler
from idea_capture.models import CaptureState, MediaKind
from idea_capture.runtime import IdeaCaptureRuntime
from idea_capture.telegram import IngressPolicy

_PLUGIN_PATH = (
    Path(__file__).resolve().parents[4]
    / ".hermes" / "plugins" / "demiurgos-idea-capture" / "__init__.py"
)

_PNG = b"\x89PNG\r\n\x1a\n" + b"fake-image-bytes"
_OGG = b"OggS" + b"fake-audio-bytes"


def _load_plugin():
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


def _handler(root: Path):
    (root / "mundos" / "vibrantes").mkdir(parents=True)
    policy = IngressPolicy(
        frozenset(), {},
        authorized_bindings=frozenset({"telegram:7:8:default"}),
        require_binding=True,
    )
    runtime = IdeaCaptureRuntime(
        config=CaptureConfig(policy, CaptureLimits()),
        state_path=root / "capture.sqlite3",
        mundos_root=root / "mundos",
        active_world="vibrantes",
        global_ideas_root=root / "ideas",
    )
    handler = IdeaCaptureHandler(
        repo_root=root,
        config_path=root / "idea-capture.yaml",
        mundos_root=root / "mundos",
        runtime=runtime,
    )
    return handler, runtime


def _setup_tool(monkeypatch, *, mode="ai", chat_id="7", user_id="8",
                profile="default"):
    """Load a fresh plugin, bind the authorized handler, and stamp session env.

    The session env vars mirror what the gateway binds per inbound message
    (``HERMES_SESSION_*`` ContextVars with an os.environ fallback), so the
    tool resolves the same binding key the intake hook authorizes against.
    """
    plugin = _load_plugin()
    plugin._CAPTURE_MODE = mode
    monkeypatch.setenv("HERMES_SESSION_PLATFORM", "telegram")
    monkeypatch.setenv("HERMES_SESSION_CHAT_ID", chat_id)
    monkeypatch.setenv("HERMES_SESSION_USER_ID", user_id)
    monkeypatch.setenv("HERMES_SESSION_PROFILE", profile)
    return plugin


def _call(plugin, args) -> dict:
    return json.loads(plugin._capture_idea_tool(args))


def test_text_capture_accepts_and_returns_receipt(monkeypatch):
    """S-3.1: capture_idea(text=...) -> service.accept invoked, receipt returned."""
    with tempfile.TemporaryDirectory() as directory:
        handler, runtime = _handler(Path(directory))
        plugin = _setup_tool(monkeypatch)
        plugin._handler = handler
        try:
            result = _call(plugin, {"text": "a floating city over a dead sea"})
            assert result["status"] == "RAW_PERSISTED"
            assert result["capture_id"]
            assert runtime.store.count() == 1
            record = runtime.store.get(result["capture_id"])
            assert record.media_kind is MediaKind.TEXT
            assert record.raw_text == "a floating city over a dead sea"
        finally:
            runtime.close()


def test_tool_confirms_save_and_invokes_worker(monkeypatch):
    """Regression: the tool must confirm SAVE_GLOBAL so the idea reaches SAVED.

    ``service.accept`` only reserves the capture (RAW_PERSISTED). In ai mode
    there is no inline Guardar/Descartar keyboard to trigger ``confirm``, so
    the ``capture_idea`` tool must do it itself; without this the capture stays
    RAW_PERSISTED forever and never lands in the Taller de Ideas.
    """
    with tempfile.TemporaryDirectory() as directory:
        handler, runtime = _handler(Path(directory))
        plugin = _setup_tool(monkeypatch)
        plugin._handler = handler
        try:
            result = _call(plugin, {"text": "a forge that remembers"})
            assert result["status"] == "RAW_PERSISTED"
            record = runtime.wait_state(result["capture_id"], CaptureState.SAVED, timeout=5.0)
            assert record.state is CaptureState.SAVED
            assert record.global_
        finally:
            runtime.close()
    """S-3.2: same payload -> same update id -> DUPLICATE, no second record."""
    with tempfile.TemporaryDirectory() as directory:
        handler, runtime = _handler(Path(directory))
        plugin = _setup_tool(monkeypatch)
        plugin._handler = handler
        try:
            first = _call(plugin, {"text": "the same idea twice"})
            second = _call(plugin, {"text": "the same idea twice"})
            assert first["status"] == "RAW_PERSISTED"
            assert second["status"] == "DUPLICATE"
            assert second["capture_id"] == first["capture_id"]
            assert runtime.store.count() == 1  # no new record persisted
        finally:
            runtime.close()


def test_unauthorized_session_rejected_before_accept(monkeypatch):
    """S-3.3: non-authorized chat -> error, service.accept NOT called."""
    with tempfile.TemporaryDirectory() as directory:
        handler, runtime = _handler(Path(directory))
        plugin = _setup_tool(monkeypatch, chat_id="999")
        plugin._handler = handler
        accepted = []

        def _spy_accept(update):
            accepted.append(update)
            return handler.runtime.service.accept(update)

        monkeypatch.setattr(runtime.service, "accept", _spy_accept)
        try:
            result = _call(plugin, {"text": "should never land"})
            assert result == {"error": "unauthorized session"}
            assert accepted == []  # service.accept never invoked
            assert runtime.store.count() == 0
        finally:
            runtime.close()


def test_image_payload_builds_image_update(monkeypatch):
    """S-3.4: image_bytes -> MediaInput(MediaKind.IMAGE) accepted."""
    with tempfile.TemporaryDirectory() as directory:
        handler, runtime = _handler(Path(directory))
        plugin = _setup_tool(monkeypatch)
        plugin._handler = handler
        try:
            result = _call(plugin, {"image_bytes": _PNG, "mime": "image/png",
                                    "text": "a petrified forest"})
            assert result["status"] == "RAW_PERSISTED"
            record = runtime.store.get(result["capture_id"])
            assert record.media_kind is MediaKind.IMAGE
            assert record.raw_bytes == _PNG
            assert record.mime == "image/png"
        finally:
            runtime.close()


def test_audio_payload_builds_voice_update_with_probed_duration(monkeypatch):
    """S-3.5: audio_bytes -> MediaInput(MediaKind.VOICE) with probed duration.

    The probe reuses ``IdeaCaptureHandler._probe_voice_duration`` via the
    module reference, so a monkeypatched probe supplies the duration and
    ``validate_media`` accepts the voice note.
    """
    with tempfile.TemporaryDirectory() as directory:
        handler, runtime = _handler(Path(directory))
        plugin = _setup_tool(monkeypatch)
        plugin._handler = handler
        monkeypatch.setattr(hermes_handler, "_probe_voice_duration",
                            lambda path: 12.5)
        try:
            result = _call(plugin, {"audio_bytes": _OGG, "mime": "audio/ogg"})
            assert result["status"] == "RAW_PERSISTED"
            record = runtime.store.get(result["capture_id"])
            assert record.media_kind is MediaKind.VOICE
            assert record.mime == "audio/ogg"
            assert record.media_duration_seconds == 12.5
        finally:
            runtime.close()


def test_tool_rejects_non_ai_mode(monkeypatch):
    """Guard: the tool surface exists only in ai mode (R-3 registration gate)."""
    with tempfile.TemporaryDirectory() as directory:
        handler, runtime = _handler(Path(directory))
        plugin = _setup_tool(monkeypatch, mode="strict")
        plugin._handler = handler
        try:
            result = _call(plugin, {"text": "nope"})
            assert result["error"] == "capture_idea is only available in ai mode"
            assert runtime.store.count() == 0
        finally:
            runtime.close()