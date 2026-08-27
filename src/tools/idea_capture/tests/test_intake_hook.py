"""Unit tests for the plugin's synchronous pre_gateway_dispatch intake hook.

The hook lives in ``.hermes/plugins/demiurgos-idea-capture/__init__.py`` (the
design's override point) and is loaded here by file path; the ``idea_capture``
runtime is built with a temporary root so no test touches the repo.
"""

import asyncio
import importlib.util
import sys
import tempfile
import types
from pathlib import Path
from types import SimpleNamespace

import idea_capture.hermes_handler as hermes_handler
from idea_capture.config import CaptureConfig, CaptureLimits
from idea_capture.hermes_handler import IdeaCaptureHandler
from idea_capture.media import MediaValidationError
from idea_capture.models import MediaKind
from idea_capture.runtime import IdeaCaptureRuntime
from idea_capture.telegram import IngressPolicy, UnauthorizedUpdate

_PLUGIN_PATH = (
    Path(__file__).resolve().parents[4]
    / ".hermes" / "plugins" / "demiurgos-idea-capture" / "__init__.py"
)


def _load_plugin():
    """Load the plugin the way Hermes does: ``hermes_plugins.<slug>`` package.

    Mirrors ``hermes_cli.plugins._load_directory_module``: the plugin dir
    becomes the package path so the relative import of ``.capture_adapter``
    (PR 2) resolves exactly like it does at gateway runtime.
    """
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
           message_type="text", durations=None):
    value = SimpleNamespace(value=message_type)
    return SimpleNamespace(
        platform_update_id=update_id,
        source=source,
        text=text,
        media_urls=media_urls or [],
        media_types=media_types or [],
        media_durations=durations or [],
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


def _handler(root: Path, *, media_reader=None):
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


def test_hook_is_sync_and_returns_skip_dict():
    """1.8 / user req: the hook returns a dict, never a coroutine."""
    with tempfile.TemporaryDirectory() as directory:
        handler, runtime = _handler(Path(directory))
        plugin = _load_plugin()
        plugin._handler = handler
        adapter = FakeAdapter()
        try:
            result = _run_hook(plugin, event=_event(1, _source(), text="idea"),
                               gateway=FakeGateway(adapter), session_store=None)
            assert isinstance(result, dict)
            assert not asyncio.iscoroutine(result)
            assert result == {"action": "skip", "reason": "idea-capture"}
        finally:
            runtime.close()


def test_hook_accepts_telemetry_schema_version_kwarg():
    """Hermes appends ``telemetry_schema_version`` to every plugin-hook callback.

    Regression: ``capture_intake_hook`` previously used a keyword-only signature
    without ``**kwargs``, so the real runtime invoked it with the extra
    ``telemetry_schema_version="hermes.observer.v1"`` marker and raised a
    TypeError. That exception made the hook fall through to the assistant flow
    instead of returning ``skip``, so capture never fired. The hook must absorb
    the marker and still return the skip dict.
    """
    with tempfile.TemporaryDirectory() as directory:
        handler, runtime = _handler(Path(directory))
        plugin = _load_plugin()
        plugin._handler = handler
        adapter = FakeAdapter()
        try:
            result = _run_hook(
                plugin,
                event=_event(1, _source(), text="idea with telemetry marker"),
                gateway=FakeGateway(adapter),
                session_store=None,
                telemetry_schema_version="hermes.observer.v1",
            )
            assert result == {"action": "skip", "reason": "idea-capture"}
            assert runtime.store.count() == 1
        finally:
            runtime.close()


def test_authorized_text_captured_and_prompt_scheduled():
    """1.3 / user req: authorized text -> skip dict, sync accept, task scheduled."""
    with tempfile.TemporaryDirectory() as directory:
        handler, runtime = _handler(Path(directory))
        plugin = _load_plugin()
        plugin._handler = handler
        adapter = FakeAdapter()
        try:
            result = _run_hook(plugin, event=_event(1, _source(), text="raw idea"),
                               gateway=FakeGateway(adapter), session_store=None)
            assert result == {"action": "skip", "reason": "idea-capture"}
            assert runtime.store.count() == 1
            record = runtime.store.get(runtime.store.list_capture_ids()[0])
            assert record.raw_text == "raw idea"
            assert record.media_kind is MediaKind.TEXT
            assert len(adapter.sent) == 1
            chat_id, text, kwargs = adapter.sent[0]
            assert chat_id == "7"
            assert text == "Idea capturada (id=`%s`). Elegí una acción:" % record.capture_id
            assert kwargs == {"metadata": None}
        finally:
            runtime.close()


def test_authorized_photo_captured():
    """Photo media is inferred as image and captured through the hook."""
    with tempfile.TemporaryDirectory() as directory:
        handler, runtime = _handler(Path(directory))
        plugin = _load_plugin()
        plugin._handler = handler
        adapter = FakeAdapter()
        try:
            event = _event(
                2, _source(), text="caption", media_urls=[".hermes/cache/images/img.png"],
                media_types=["image/png"], message_type="photo",
            )
            result = _run_hook(plugin, event=event,
                               gateway=FakeGateway(adapter), session_store=None)
            assert result == {"action": "skip", "reason": "idea-capture"}
            record = runtime.store.get(runtime.store.list_capture_ids()[0])
            assert record.media_kind is MediaKind.IMAGE
            assert record.raw_text == "caption"
            assert len(adapter.sent) == 1
        finally:
            runtime.close()


def test_non_capture_chat_returns_none():
    """1.5 / user req: a non-capture chat falls through to the assistant."""
    with tempfile.TemporaryDirectory() as directory:
        handler, runtime = _handler(Path(directory))
        plugin = _load_plugin()
        plugin._handler = handler
        adapter = FakeAdapter()
        try:
            result = _run_hook(plugin, event=_event(1, _source(chat_id=999), text="idea"),
                               gateway=FakeGateway(adapter), session_store=None)
            assert result is None
            assert runtime.store.count() == 0
            assert adapter.sent == []
        finally:
            runtime.close()


def test_unauthorized_sender_not_captured():
    """1.4 / user req: an unauthorized sender is never captured nor prompted."""
    with tempfile.TemporaryDirectory() as directory:
        handler, runtime = _handler(Path(directory))
        plugin = _load_plugin()
        plugin._handler = handler
        adapter = FakeAdapter()
        try:
            result = _run_hook(plugin, event=_event(1, _source(user_id=99), text="idea"),
                               gateway=FakeGateway(adapter), session_store=None)
            assert result is None
            assert runtime.store.count() == 0
            assert adapter.sent == []
        finally:
            runtime.close()


def test_non_telegram_platform_returns_none():
    """1.5: only the telegram platform is captured."""
    with tempfile.TemporaryDirectory() as directory:
        handler, runtime = _handler(Path(directory))
        plugin = _load_plugin()
        plugin._handler = handler
        source = _source()
        source.platform = SimpleNamespace(value="discord")
        try:
            result = _run_hook(plugin, event=_event(1, source, text="idea"),
                               gateway=FakeGateway(FakeAdapter()), session_store=None)
            assert result is None
            assert runtime.store.count() == 0
        finally:
            runtime.close()


def test_unsupported_media_falls_through():
    """S-10.3: video/document is not capturable -> None, assistant handles."""
    with tempfile.TemporaryDirectory() as directory:
        handler, runtime = _handler(Path(directory))
        plugin = _load_plugin()
        plugin._handler = handler
        try:
            event = _event(3, _source(), media_urls=["/tmp/clip.mp4"],
                           media_types=["video/mp4"], message_type="video")
            result = _run_hook(plugin, event=event,
                               gateway=FakeGateway(FakeAdapter()), session_store=None)
            assert result is None
            assert runtime.store.count() == 0
        finally:
            runtime.close()


def test_unauthorized_update_returns_skip_rejected(monkeypatch):
    """1.6: a capture-path UnauthorizedUpdate consumes the message, no prompt."""
    with tempfile.TemporaryDirectory() as directory:
        handler, runtime = _handler(Path(directory))
        plugin = _load_plugin()
        plugin._handler = handler
        adapter = FakeAdapter()

        def _boom(update):
            raise UnauthorizedUpdate("policy race")

        monkeypatch.setattr(runtime.service, "accept", _boom)
        try:
            result = _run_hook(plugin, event=_event(1, _source(), text="idea"),
                               gateway=FakeGateway(adapter), session_store=None)
            assert result == {"action": "skip", "reason": "idea-capture-rejected"}
            assert adapter.sent == []
        finally:
            runtime.close()


def test_media_validation_failure_returns_skip_rejected(monkeypatch):
    """A MediaValidationError consumes the message without leaking to assistant."""
    with tempfile.TemporaryDirectory() as directory:
        handler, runtime = _handler(Path(directory))
        plugin = _load_plugin()
        plugin._handler = handler
        adapter = FakeAdapter()

        def _boom(update):
            raise MediaValidationError("image exceeds 20 MB limit")

        monkeypatch.setattr(runtime.service, "accept", _boom)
        try:
            result = _run_hook(plugin, event=_event(1, _source(), text="idea"),
                               gateway=FakeGateway(adapter), session_store=None)
            assert result == {"action": "skip", "reason": "idea-capture-rejected"}
            assert adapter.sent == []
        finally:
            runtime.close()


def test_duplicate_returns_skip_no_prompt():
    """1.7 / R-4: replaying the same update is silent — no second prompt."""
    with tempfile.TemporaryDirectory() as directory:
        handler, runtime = _handler(Path(directory))
        plugin = _load_plugin()
        plugin._handler = handler
        adapter = FakeAdapter()
        event = _event(1, _source(), text="idea")
        try:
            first = _run_hook(plugin, event=event,
                              gateway=FakeGateway(adapter), session_store=None)
            second = _run_hook(plugin, event=event,
                               gateway=FakeGateway(adapter), session_store=None)
            assert first == {"action": "skip", "reason": "idea-capture"}
            assert second == {"action": "skip", "reason": "idea-capture-duplicate"}
            assert runtime.store.count() == 1
            assert len(adapter.sent) == 1
        finally:
            runtime.close()


def test_register_registers_pre_gateway_dispatch_hook(monkeypatch):
    """1.1: register() wires the sync hook and makes no fictional API calls."""
    plugin = _load_plugin()
    with tempfile.TemporaryDirectory() as directory:
        monkeypatch.setenv("DEMIURGOS_ROOT", directory)
        monkeypatch.setenv("DEMIURGOS_IDEA_CAPTURE_MODE", "ai")
        calls = []

        def _register_hook(name, cb):
            calls.append(("register_hook", name, cb))

        def _register_platform(**kwargs):
            calls.append(("register_platform", kwargs))

        def _register_tool(**kwargs):
            calls.append(("register_tool", kwargs))

        ctx = SimpleNamespace(register_hook=_register_hook,
                              register_platform=_register_platform,
                              register_tool=_register_tool)
        plugin.register(ctx)
    assert ("register_hook", "pre_gateway_dispatch", plugin.capture_intake_hook) in calls
    assert plugin._handler is not None
    assert plugin._CAPTURE_MODE == "ai"
    # ai mode (default) also wires the assistant-facing surface (R-3/R-4).
    assert ("register_hook", "pre_llm_call", plugin.capture_guidance_hook) in calls
    tool = [c for c in calls if c[0] == "register_tool"]
    assert len(tool) == 2
    assert [t[1]["name"] for t in tool] == ["capture_idea", "update_idea"]
    assert callable(tool[0][1]["handler"])
    assert callable(tool[1][1]["handler"])
    platform = [c for c in calls if c[0] == "register_platform"]
    assert len(platform) == 1
    kwargs = platform[0][1]
    assert kwargs["name"] == "telegram"
    assert kwargs["required_env"] == ["TELEGRAM_BOT_TOKEN"]
    assert callable(kwargs["adapter_factory"])
    assert callable(kwargs["check_fn"])


def test_register_platform_factory_builds_capture_adapter(monkeypatch):
    """2.8: the registered factory returns a CaptureTelegramAdapter subclass."""
    plugin = _load_plugin()
    with tempfile.TemporaryDirectory() as directory:
        monkeypatch.setenv("DEMIURGOS_ROOT", directory)
        captured = {}

        def _register_platform(**kwargs):
            captured.update(kwargs)

        ctx = SimpleNamespace(
            register_hook=lambda name, cb: None,
            register_platform=_register_platform,
            register_tool=lambda **kw: None,
        )
        plugin.register(ctx)
    adapter = captured["adapter_factory"](SimpleNamespace(name="telegram", extra={}))
    from plugins.platforms.telegram.adapter import TelegramAdapter
    assert isinstance(adapter, TelegramAdapter)
    assert type(adapter).__name__ == "CaptureTelegramAdapter"
    assert adapter._capture_handler is plugin._handler


# -- PR 3: voice probe through the hook + intake edge cases -----------------


def test_voice_over_300s_rejected_via_hook(monkeypatch):
    """PR 3 / S-2.4: an over-300s voice is consumed (skip-rejected), never leaks."""
    with tempfile.TemporaryDirectory() as directory:
        handler, runtime = _handler(
            Path(directory), media_reader=lambda _: b"OggS raw-voice",
        )
        plugin = _load_plugin()
        plugin._handler = handler
        adapter = FakeAdapter()
        try:
            monkeypatch.setattr(hermes_handler, "_probe_voice_duration", lambda path: 320)
            event = _event(1, _source(), media_urls=[".hermes/cache/audio/long.ogg"],
                           media_types=["audio/ogg"], message_type="voice")
            result = _run_hook(plugin, event=event,
                               gateway=FakeGateway(adapter), session_store=None)
            assert result == {"action": "skip", "reason": "idea-capture-rejected"}
            assert runtime.store.count() == 0
            assert adapter.sent == []  # no prompt, no acknowledgment
        finally:
            runtime.close()


def test_unsupported_media_returns_none():
    """3.7 / S-10.3: video and document are not capturable -> None, no prompt."""
    with tempfile.TemporaryDirectory() as directory:
        handler, runtime = _handler(Path(directory))
        plugin = _load_plugin()
        plugin._handler = handler
        adapter = FakeAdapter()
        try:
            cases = [
                (".hermes/cache/video/clip.mp4", "video/mp4", "video"),
                (".hermes/cache/documents/doc.pdf", "application/pdf", "document"),
            ]
            for url, mime, mtype in cases:
                event = _event(4, _source(), media_urls=[url],
                               media_types=[mime], message_type=mtype)
                result = _run_hook(plugin, event=event,
                                   gateway=FakeGateway(adapter), session_store=None)
                assert result is None
            assert runtime.store.count() == 0
            assert adapter.sent == []
        finally:
            runtime.close()


def test_missing_identity_returns_none():
    """3.8 / S-10.4: a missing Telegram identity is never captured."""
    with tempfile.TemporaryDirectory() as directory:
        handler, runtime = _handler(Path(directory))
        plugin = _load_plugin()
        plugin._handler = handler
        adapter = FakeAdapter()
        try:
            no_user = _event(5, _source(user_id=None), text="ghost")
            result = _run_hook(plugin, event=no_user,
                               gateway=FakeGateway(adapter), session_store=None)
            assert result is None
            no_chat = _event(6, _source(chat_id=None), text="ghost")
            result = _run_hook(plugin, event=no_chat,
                               gateway=FakeGateway(adapter), session_store=None)
            assert result is None
            assert runtime.store.count() == 0
            assert adapter.sent == []
        finally:
            runtime.close()


# -- PR idea-capture-ai-gate: gate fall-through (R-2, R-6) -------------------


def test_ai_mode_authorized_text_falls_through(monkeypatch):
    """S-2.1: ai + authorized binding + text -> None, message reaches assistant."""
    with tempfile.TemporaryDirectory() as directory:
        handler, runtime = _handler(Path(directory))
        plugin = _load_plugin()
        plugin._handler = handler
        plugin._CAPTURE_MODE = "ai"
        adapter = FakeAdapter()
        try:
            result = _run_hook(plugin, event=_event(1, _source(), text="an idea"),
                               gateway=FakeGateway(adapter), session_store=None)
            assert result is None
            assert runtime.store.count() == 0
            assert adapter.sent == []  # no skip, no capture prompt
        finally:
            runtime.close()


def test_strict_mode_authorized_text_skips(monkeypatch):
    """S-2.2: strict + authorized binding -> unconditional skip (current behavior)."""
    with tempfile.TemporaryDirectory() as directory:
        handler, runtime = _handler(Path(directory))
        plugin = _load_plugin()
        plugin._handler = handler
        plugin._CAPTURE_MODE = "strict"
        adapter = FakeAdapter()
        try:
            result = _run_hook(plugin, event=_event(1, _source(), text="an idea"),
                               gateway=FakeGateway(adapter), session_store=None)
            assert result == {"action": "skip", "reason": "idea-capture"}
            assert runtime.store.count() == 1
        finally:
            runtime.close()


def test_ai_mode_voice_and_photo_captured_directly(monkeypatch):
    """S-2.3 (adjusted): ai mode — text-only turns fall through to the assistant
    (None, so the assistant decides), while voice/photo turns are captured
    directly by the hook (skip) so their real bytes reach ideas/media/ (the
    assistant only sees an injected description, which would lose the media)."""
    with tempfile.TemporaryDirectory() as directory:

        def _reader(path):
            return b"OggS raw-voice" if "audio" in str(path) else b"\x89PNG\r\n\x1a\nraw-image"

        handler, runtime = _handler(Path(directory), media_reader=_reader)
        plugin = _load_plugin()
        plugin._handler = handler
        plugin._CAPTURE_MODE = "ai"
        adapter = FakeAdapter()
        monkeypatch.setattr(hermes_handler, "_probe_voice_duration",
                            lambda path: 30.0)
        try:
            voice = _event(1, _source(), media_urls=[".hermes/cache/audio/note.ogg"],
                           media_types=["audio/ogg"], message_type="voice")
            result = _run_hook(plugin, event=voice,
                               gateway=FakeGateway(adapter), session_store=None)
            assert result == {"action": "skip", "reason": "idea-capture"}
            photo = _event(2, _source(), text="caption",
                           media_urls=[".hermes/cache/images/img.png"],
                           media_types=["image/png"], message_type="photo")
            result = _run_hook(plugin, event=photo,
                               gateway=FakeGateway(adapter), session_store=None)
            assert result == {"action": "skip", "reason": "idea-capture"}
            # both media turns persisted; the hook prompts the owner to confirm
            assert runtime.store.count() == 2
            assert adapter.sent != []
        finally:
            runtime.close()


def test_ai_mode_non_telegram_returns_none(monkeypatch):
    """S-6.1: non-telegram platform -> None in ai mode (authorization gate first)."""
    with tempfile.TemporaryDirectory() as directory:
        handler, runtime = _handler(Path(directory))
        plugin = _load_plugin()
        plugin._handler = handler
        plugin._CAPTURE_MODE = "ai"
        source = _source()
        source.platform = SimpleNamespace(value="discord")
        try:
            result = _run_hook(plugin, event=_event(1, source, text="idea"),
                               gateway=FakeGateway(FakeAdapter()), session_store=None)
            assert result is None
            assert runtime.store.count() == 0
        finally:
            runtime.close()


def test_ai_mode_unauthorized_binding_returns_none(monkeypatch):
    """S-6.2: unauthorized sender -> None in ai mode (binding gate still first)."""
    with tempfile.TemporaryDirectory() as directory:
        handler, runtime = _handler(Path(directory))
        plugin = _load_plugin()
        plugin._handler = handler
        plugin._CAPTURE_MODE = "ai"
        try:
            result = _run_hook(plugin, event=_event(1, _source(user_id=99), text="idea"),
                               gateway=FakeGateway(FakeAdapter()), session_store=None)
            assert result is None
            assert runtime.store.count() == 0
        finally:
            runtime.close()


def test_ai_mode_conversion_value_error_returns_none(monkeypatch):
    """S-6.3: _update_from_event_with_voice_probe raises ValueError -> None.

    In ai mode the authorized binding returns before conversion; this proves
    the ValueError path still returns None (never leaks, never crashes) when
    mode is ai and the conversion is forced.
    """
    with tempfile.TemporaryDirectory() as directory:
        handler, runtime = _handler(Path(directory))
        plugin = _load_plugin()
        plugin._handler = handler
        plugin._CAPTURE_MODE = "ai"
        try:
            def _boom(event, gateway=None):
                raise ValueError("unsupported media")

            monkeypatch.setattr(handler, "_update_from_event_with_voice_probe", _boom)
            result = _run_hook(plugin, event=_event(1, _source(), text="idea"),
                               gateway=FakeGateway(FakeAdapter()), session_store=None)
            assert result is None
            assert runtime.store.count() == 0
        finally:
            runtime.close()