"""Unit tests for the plugin's synchronous pre_gateway_dispatch intake hook.

The hook lives in ``.hermes/plugins/demiurgos-idea-capture/__init__.py`` (the
design's override point) and is loaded here by file path; the ``idea_capture``
runtime is built with a temporary root so no test touches the repo.
"""

import asyncio
import importlib.util
import tempfile
from pathlib import Path
from types import SimpleNamespace

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
    spec = importlib.util.spec_from_file_location(
        "demiurgos_idea_capture_plugin", _PLUGIN_PATH)
    module = importlib.util.module_from_spec(spec)
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
        media_reader=lambda _: b"\x89PNG\r\n\x1a\nraw-image",
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
        calls = []
        ctx = SimpleNamespace(register_hook=lambda name, cb: calls.append((name, cb)))
        plugin.register(ctx)
    assert ("pre_gateway_dispatch", plugin.capture_intake_hook) in calls
    assert plugin._handler is not None