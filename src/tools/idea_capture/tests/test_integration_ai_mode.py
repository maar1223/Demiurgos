"""End-to-end integration tests for the AI-gated idea capture (task 5.1).

Threads the plugin's intake hook, the ``capture_idea`` tool, and the runtime
(processor + media enrichment) together for both ``ai`` and ``strict`` modes:

- ai mode: an authorized text/photo/voice turn falls through the hook (``None``,
  the assistant sees it) and the assistant can then capture via the tool, which
  persists and returns a receipt.
- strict mode: the hook still skips unconditionally and ``service.accept`` is
  invoked (pre-change behavior).
- media enrichment end-to-end: IMAGE with vision on -> body = ``descripcion``,
  type = ``map_tags_to_taxonomy(tags)`` (S-5.2); VOICE -> body = transcript,
  type = classifier label (S-5.4).
- fail-open: vision off -> body = caption, type = ``sin_clasificar`` (S-5.3);
  transcription failure -> body = empty, type = ``sin_clasificar``, record
  RETRYABLE (S-5.5 / S-5.7).
- flag precedence: ai vs strict both paths and env > yaml > default (task 4.1).

The unit-level scenarios S-1.1..S-6.3 are covered by the PR 1/2 test files; this
file adds the cross-component flows those unit tests do not exercise.
"""

import asyncio
import importlib.util
import json
import sys
import tempfile
import types
from pathlib import Path
from types import SimpleNamespace

_HERE = Path(__file__).resolve().parent
_TOOLS = Path(__file__).resolve().parents[2]  # src/tools
for _p in (str(_TOOLS),):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import idea_capture.hermes_handler as hermes_handler  # noqa: E402
from idea_capture.config import CaptureConfig, CaptureLimits  # noqa: E402
from idea_capture.enrich import MediaEnrichProvider  # noqa: E402
from idea_capture.hermes_handler import IdeaCaptureHandler  # noqa: E402
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


# ---------------------------------------------------------------------------
# Fixtures / helpers (mirror test_intake_hook + test_media_enrich_wiring)
# ---------------------------------------------------------------------------


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


def _source(chat_id=7, user_id=8, *, chat_type="dm", profile="default"):
    return SimpleNamespace(
        platform=SimpleNamespace(value="telegram"),
        chat_id=str(chat_id),
        user_id=str(user_id),
        chat_type=chat_type,
        thread_id=None,
        profile=profile,
    )


def _event(update_id, source, *, text="", media_urls=None, media_types=None,
           message_type="text"):
    value = SimpleNamespace(value=message_type)
    return SimpleNamespace(
        platform_update_id=update_id,
        source=source,
        text=text,
        media_urls=media_urls or [],
        media_types=media_types or [],
        media_durations=[],
        message_type=value,
        get_command=lambda: None,
    )


class FakeAdapter:
    def __init__(self):
        self.sent = []

    async def send(self, chat_id, content, **kwargs):
        self.sent.append((chat_id, content, kwargs))


class FakeGateway:
    def __init__(self, adapter):
        self._adapter = adapter

    def _adapter_for_source(self, source):
        return self._adapter


def _handler(root: Path, *, media_reader=None, enrich=None):
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
        enrich=enrich,
        global_ideas_root=root / "ideas",
    )
    handler = IdeaCaptureHandler(
        repo_root=root,
        config_path=root / "idea-capture.yaml",
        mundos_root=root / "mundos",
        runtime=runtime,
        media_reader=media_reader or (lambda _: b"\x89PNG\r\n\x1a\nraw-image"),
    )
    return handler, runtime


def _run_hook(plugin, **kwargs):
    """Run the sync hook inside a running loop so scheduled tasks can fire."""

    async def _run():
        result = plugin.capture_intake_hook(**kwargs)
        await asyncio.sleep(0)
        return result

    return asyncio.run(_run())


def _session(monkeypatch, chat_id="7", user_id="8", profile="default"):
    monkeypatch.setenv("HERMES_SESSION_PLATFORM", "telegram")
    monkeypatch.setenv("HERMES_SESSION_CHAT_ID", chat_id)
    monkeypatch.setenv("HERMES_SESSION_USER_ID", user_id)
    monkeypatch.setenv("HERMES_SESSION_PROFILE", profile)


# ---------------------------------------------------------------------------
# ai mode end-to-end: turn falls through, then the tool captures (S-2.1/S-3.1)
# ---------------------------------------------------------------------------


def test_ai_mode_text_turn_falls_through_then_tool_captures(monkeypatch):
    """S-2.1 + S-3.1: hook None (assistant sees turn), then capture_idea persists."""
    with tempfile.TemporaryDirectory() as directory:
        handler, runtime = _handler(Path(directory))
        plugin = _load_plugin()
        plugin._handler = handler
        plugin._CAPTURE_MODE = "ai"
        adapter = FakeAdapter()
        try:
            result = _run_hook(plugin, event=_event(1, _source(), text="una idea"),
                               gateway=FakeGateway(adapter), session_store=None)
            assert result is None  # assistant sees the turn
            assert runtime.store.count() == 0  # nothing captured yet

            _session(monkeypatch)
            receipt = json.loads(
                plugin._capture_idea_tool({"text": "una idea"}))
            assert receipt["status"] == "RAW_PERSISTED"
            assert runtime.store.count() == 1
            record = runtime.store.get(receipt["capture_id"])
            assert record.media_kind is MediaKind.TEXT
            assert record.raw_text == "una idea"
        finally:
            runtime.close()


def test_ai_mode_photo_and_voice_fall_through(monkeypatch):
    """S-2.3: ai + authorized binding + photo/voice -> None (assistant sees them)."""
    with tempfile.TemporaryDirectory() as directory:
        handler, runtime = _handler(
            Path(directory), media_reader=lambda _: _VOICE_BYTES)
        plugin = _load_plugin()
        plugin._handler = handler
        plugin._CAPTURE_MODE = "ai"
        adapter = FakeAdapter()
        try:
            photo = _event(1, _source(), text="caption",
                           media_urls=[".hermes/cache/images/img.png"],
                           media_types=["image/png"], message_type="photo")
            voice = _event(2, _source(),
                           media_urls=[".hermes/cache/audio/note.ogg"],
                           media_types=["audio/ogg"], message_type="voice")
            assert _run_hook(plugin, event=photo, gateway=FakeGateway(adapter),
                             session_store=None) is None
            assert _run_hook(plugin, event=voice, gateway=FakeGateway(adapter),
                             session_store=None) is None
            assert runtime.store.count() == 0
            assert adapter.sent == []
        finally:
            runtime.close()


# ---------------------------------------------------------------------------
# strict mode end-to-end: hook skips and service.accept is invoked (S-2.2)
# ---------------------------------------------------------------------------


def test_strict_mode_text_photo_voice_skip_and_accept(monkeypatch):
    """S-2.2: strict + authorized text/photo/voice -> skip, accept invoked."""
    with tempfile.TemporaryDirectory() as directory:

        def _reader(path):
            return _VOICE_BYTES if "audio" in str(path) else _IMAGE_BYTES

        handler, runtime = _handler(Path(directory), media_reader=_reader)
        plugin = _load_plugin()
        plugin._handler = handler
        plugin._CAPTURE_MODE = "strict"
        adapter = FakeAdapter()
        monkeypatch.setattr(hermes_handler, "_probe_voice_duration",
                            lambda path: 30.0)
        try:
            text = _event(1, _source(), text="una idea")
            assert _run_hook(plugin, event=text, gateway=FakeGateway(adapter),
                             session_store=None) == {"action": "skip",
                                                     "reason": "idea-capture"}
            photo = _event(2, _source(), text="caption",
                           media_urls=[".hermes/cache/images/img.png"],
                           media_types=["image/png"], message_type="photo")
            assert _run_hook(plugin, event=photo, gateway=FakeGateway(adapter),
                             session_store=None) == {"action": "skip",
                                                     "reason": "idea-capture"}
            voice = _event(3, _source(),
                           media_urls=[".hermes/cache/audio/note.ogg"],
                           media_types=["audio/ogg"], message_type="voice")
            assert _run_hook(plugin, event=voice, gateway=FakeGateway(adapter),
                             session_store=None) == {"action": "skip",
                                                     "reason": "idea-capture"}
            # service.accept was invoked for all three -> three records persisted.
            assert runtime.store.count() == 3
            kinds = {r.media_kind for r in
                     (runtime.store.get(i) for i in runtime.store.list_capture_ids())}
            assert kinds == {MediaKind.TEXT, MediaKind.IMAGE, MediaKind.VOICE}
        finally:
            runtime.close()


# ---------------------------------------------------------------------------
# Media enrichment end-to-end (S-5.2 / S-5.4 / S-5.3 / S-5.5 / S-5.7)
# ---------------------------------------------------------------------------


def test_media_enrich_image_vision_on_end_to_end(tmp_path):
    """S-5.2: IMAGE vision on -> body = descripcion, type = map_tags_to_taxonomy."""
    provider = MediaEnrichProvider(
        vision_fn=lambda raw, ctx: {
            "descripcion": "un mapa de la corte real",
            "tags": ["ambientacion"],
            "veredicto": "ambientacion",
        },
        vision_enabled=True,
    )
    handler, runtime = _handler(tmp_path, enrich=provider)
    try:
        receipt = runtime.service.accept(
            TelegramUpdate(1, 7, 8, False,
                           MediaInput(MediaKind.IMAGE, data=_IMAGE_BYTES,
                                      mime="image/png", text="el mapa")))
        runtime.confirm(receipt.capture_id, WorldAction.SAVE_GLOBAL)
        saved = runtime.wait_state(receipt.capture_id, CaptureState.SAVED)
        content = (tmp_path / "ideas" / f"{saved.slug}.md").read_text(encoding="utf-8")
        assert "un mapa de la corte real" in content
        assert "type: ambientacion" in content
    finally:
        runtime.close()


def test_media_enrich_voice_transcript_end_to_end(tmp_path):
    """S-5.4: VOICE -> body = transcript, type = classifier label."""
    audio = tmp_path / "voice.ogg"
    audio.write_bytes(_VOICE_BYTES)
    provider = MediaEnrichProvider(
        hermes=lambda raw: "personaje",
        transcribe_fn=lambda path, lang: "una idea hablada",
        language_resolver=lambda: "es",
    )
    handler, runtime = _handler(tmp_path, enrich=provider)
    try:
        receipt = runtime.service.accept(
            TelegramUpdate(1, 7, 8, False,
                           MediaInput(MediaKind.VOICE, data=_VOICE_BYTES,
                                      mime="audio/ogg", duration_seconds=30,
                                      path=str(audio))))
        runtime.confirm(receipt.capture_id, WorldAction.SAVE_GLOBAL)
        saved = runtime.wait_state(receipt.capture_id, CaptureState.SAVED)
        content = (tmp_path / "ideas" / f"{saved.slug}.md").read_text(encoding="utf-8")
        assert "una idea hablada" in content
        assert "type: personaje" in content
    finally:
        runtime.close()


def test_media_enrich_image_vision_off_caption_fail_open(tmp_path):
    """S-5.3: vision off -> body = caption, type = sin_clasificar (end-to-end)."""
    provider = MediaEnrichProvider(vision_enabled=False)
    handler, runtime = _handler(tmp_path, enrich=provider)
    try:
        receipt = runtime.service.accept(
            TelegramUpdate(1, 7, 8, False,
                           MediaInput(MediaKind.IMAGE, data=_IMAGE_BYTES,
                                      mime="image/png", text="el castillo al amanecer")))
        runtime.confirm(receipt.capture_id, WorldAction.SAVE_GLOBAL)
        saved = runtime.wait_state(receipt.capture_id, CaptureState.SAVED)
        content = (tmp_path / "ideas" / f"{saved.slug}.md").read_text(encoding="utf-8")
        assert "el castillo al amanecer" in content
        assert "type: sin_clasificar" in content
    finally:
        runtime.close()


def test_media_enrich_voice_transcription_fails_retryable(tmp_path):
    """S-5.5 + S-5.7: transcription fails + no caption -> RETRYABLE, raw retained."""
    audio = tmp_path / "voice.ogg"
    audio.write_bytes(_VOICE_BYTES)

    def failing(_path, _lang):
        raise RuntimeError("whisper down")

    provider = MediaEnrichProvider(transcribe_fn=failing,
                                   language_resolver=lambda: "es")
    handler, runtime = _handler(tmp_path, enrich=provider)
    try:
        receipt = runtime.service.accept(
            TelegramUpdate(1, 7, 8, False,
                           MediaInput(MediaKind.VOICE, data=_VOICE_BYTES,
                                      mime="audio/ogg", duration_seconds=30,
                                      path=str(audio))))
        runtime.confirm(receipt.capture_id, WorldAction.SAVE_GLOBAL)
        record = runtime.wait_state(receipt.capture_id, CaptureState.RETRYABLE)
        assert "enrichment produced empty idea" in record.error
        assert record.raw_bytes == _VOICE_BYTES  # raw media retained
    finally:
        runtime.close()


# ---------------------------------------------------------------------------
# Flag precedence end-to-end: env > yaml > default (task 4.1 / R-1)
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


def _register_plugin(tmp_path, monkeypatch, *, yaml_mode, env_mode=None):
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "idea-capture.yaml").write_text(
        f"capture_mode: {yaml_mode}\n", encoding="utf-8")
    (tmp_path / "mundos").mkdir()
    (tmp_path / "data").mkdir()
    monkeypatch.setenv("DEMIURGOS_ROOT", str(tmp_path))
    if env_mode is None:
        monkeypatch.delenv("DEMIURGOS_IDEA_CAPTURE_MODE", raising=False)
    else:
        monkeypatch.setenv("DEMIURGOS_IDEA_CAPTURE_MODE", env_mode)
    plugin = _load_plugin()
    ctx = RecordingCtx()
    plugin.register(ctx)
    return plugin, ctx


def test_flag_yaml_strict_when_env_unset(tmp_path, monkeypatch):
    """Task 4.1: env unset + yaml strict -> plugin mode strict."""
    plugin, ctx = _register_plugin(tmp_path, monkeypatch, yaml_mode="strict")
    assert plugin._CAPTURE_MODE == "strict"
    assert plugin._handler is not None
    # strict mode does not expose the assistant-facing tool/guidance surface.
    assert ("pre_llm_call", plugin.capture_guidance_hook) not in ctx.hooks
    assert ctx.tools == []


def test_flag_env_wins_over_yaml(tmp_path, monkeypatch):
    """Task 4.1: env ai + yaml strict -> env wins, mode ai."""
    plugin, _ = _register_plugin(tmp_path, monkeypatch, yaml_mode="strict",
                                 env_mode="ai")
    assert plugin._CAPTURE_MODE == "ai"


def test_flag_env_strict_wins_over_yaml(tmp_path, monkeypatch):
    """Task 4.1: env strict + yaml ai -> env wins, mode strict."""
    plugin, _ = _register_plugin(tmp_path, monkeypatch, yaml_mode="ai",
                                 env_mode="strict")
    assert plugin._CAPTURE_MODE == "strict"


def test_flag_yaml_ai_default_when_env_unset(tmp_path, monkeypatch):
    """Task 4.1: env unset + yaml ai -> mode ai (default)."""
    plugin, _ = _register_plugin(tmp_path, monkeypatch, yaml_mode="ai")
    assert plugin._CAPTURE_MODE == "ai"
