"""R-6 tests: the one-shot wake-up notice (WU3, tasks 3.1-3.4).

The plugin module is loaded by file path exactly as the gateway does. The
notice is armed by the FIRST authorized capture-chat ``capture_intake_hook``
invocation and fires after ``_WAKE_NOTICE_DELAY`` (~5s in production; collapsed
to 0 here). Covers S-6.1 (one notice with correct N/M counts + one keyboard per
parked capture), S-6.2 (no re-fire within the same boot), S-6.3 (media
auto-captured as RAW_PERSISTED counts in N but not M) and task 3.4 (M=0 -> no
notice at all), plus the no-loop fallback.
"""

import asyncio
import importlib.util
import sys
import tempfile
import time
import types
from pathlib import Path
from types import SimpleNamespace

from idea_capture.config import CaptureConfig, CaptureLimits
from idea_capture.hermes_handler import IdeaCaptureHandler
from idea_capture.models import MediaInput, MediaKind, TelegramUpdate
from idea_capture.runtime import IdeaCaptureRuntime
from idea_capture.telegram import IngressPolicy

_PLUGIN_PATH = (
    Path(__file__).resolve().parents[4]
    / ".hermes" / "plugins" / "demiurgos-idea-capture" / "__init__.py"
)

_PNG = b"\x89PNG\r\n\x1a\n" + b"fake-image-bytes"


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


def _source(chat_id=7, user_id=8, *, chat_type="dm", profile="default"):
    return SimpleNamespace(
        platform=SimpleNamespace(value="telegram"),
        chat_id=str(chat_id),
        user_id=str(user_id),
        chat_type=chat_type,
        thread_id=None,
        profile=profile,
    )


def _event(update_id, source, *, text="", message_type="text"):
    return SimpleNamespace(
        platform_update_id=update_id,
        source=source,
        text=text,
        media_urls=[],
        media_types=[],
        media_durations=[],
        message_type=SimpleNamespace(value=message_type),
        get_command=lambda: None,
    )


class FakeAdapter:
    """Records both outbound shapes: plain summary sends and keyboards."""

    def __init__(self):
        self.sent = []  # ("summary"|"keyboard", chat_id, payload, thread_id)

    async def send(self, chat_id, content, **kwargs):
        self.sent.append(("summary", chat_id, content, kwargs.get("metadata")))

    async def send_capture_prompt(self, *, chat_id, capture_id, thread_id=None):
        self.sent.append(("keyboard", chat_id, capture_id, thread_id))


class FakeGateway:
    def __init__(self, adapter):
        self._adapter = adapter

    def _adapter_for_source(self, source):
        return self._adapter


def _offline_update(update_id, *, text="offline idea", kind=MediaKind.TEXT):
    """A Telegram message sent BEFORE boot (event_ts < boot_ts), ingested now."""
    media = MediaInput(kind, text=text,
                       mime="image/png" if kind is MediaKind.IMAGE else "")
    return TelegramUpdate(
        update_id=update_id,
        chat_id=7,
        sender_id=8,
        is_group=False,
        media=media,
        event_timestamp=time.time() - 3600.0,
    )


def _seed_offline(store, counts: dict) -> list[str]:
    """Reserve ``counts`` offline captures; ``counts`` maps kind -> count.

    Returns capture ids in creation order. Update ids start at 1000 so they
    never collide with the hook event's ``platform_update_id`` (1) — a
    collision would dedup the seeded row against the hook's own capture.
    """
    capture_ids = []
    update_id = 1000
    for kind, n in counts.items():
        for _ in range(n):
            record = store.reserve(
                _offline_update(update_id, kind=kind, text=f"{kind}-{update_id}"))
            update_id += 1
            capture_ids.append(record.capture_id)
    return capture_ids


def _arm_and_settle(plugin, gateway, *, event=None):
    """Invoke the hook inside a running loop and let the notice (delay 0) fire."""

    async def _run():
        result = plugin.capture_intake_hook(
            event=event or _event(1, _source(), text="wake me"),
            gateway=gateway,
            session_store=None,
        )
        await asyncio.sleep(0.02)  # wake task + keyboard tasks run to completion
        return result

    return asyncio.run(_run())


def _setup(plugin, handler, *, parked: int, offline_counts):
    """Common scaffolding: fresh boot, seeded offline captures, fake gateway.

    ``offline_counts`` maps MediaKind -> number of offline rows (all
    RAW_PERSISTED); ``parked`` of the TEXT rows are transitioned to
    AWAITING_CONFIRM. Returns ``(adapter, parked_ids)``.
    """
    plugin._handler = handler
    plugin._CAPTURE_MODE = "ai"  # text turns fall through; notice still arms
    plugin._WAKE_NOTICE_DELAY = 0
    plugin._boot_ts = time.time()  # boot happens BEFORE the offline drain
    capture_ids = _seed_offline(handler.runtime.store, offline_counts)
    parked_ids = []
    for capture_id in capture_ids:
        if len(parked_ids) < parked and \
                handler.runtime.store.get(capture_id).media_kind is MediaKind.TEXT:
            handler.runtime.store.set_awaiting_confirm(capture_id)
            parked_ids.append(capture_id)
    adapter = FakeAdapter()
    return adapter, parked_ids


def test_wake_notice_fires_once_with_correct_counts():
    """S-6.1: 5 offline-drained (3 parked) -> ONE summary + 3 keyboards."""
    with tempfile.TemporaryDirectory() as directory:
        handler, runtime = _handler(Path(directory))
        plugin = _load_plugin()
        try:
            adapter, parked_ids = _setup(
                plugin, handler, parked=3, offline_counts={MediaKind.TEXT: 5})
            gateway = FakeGateway(adapter)

            result = _arm_and_settle(plugin, gateway)

            assert result is None  # ai-mode text falls through, never captured
            summaries = [s for s in adapter.sent if s[0] == "summary"]
            keyboards = [s for s in adapter.sent if s[0] == "keyboard"]
            assert len(summaries) == 1, adapter.sent
            assert summaries[0][2] == \
                "Llegaron 5 mensajes; tengo 3 por confirmar. ¿Las reviso?"
            assert len(keyboards) == 3
            assert {k[2] for k in keyboards} == set(parked_ids)
        finally:
            runtime.close()


def test_wake_notice_does_not_refire_same_boot():
    """S-6.2: a second hook invocation adds no notice and no keyboards."""
    with tempfile.TemporaryDirectory() as directory:
        handler, runtime = _handler(Path(directory))
        plugin = _load_plugin()
        try:
            adapter, parked_ids = _setup(
                plugin, handler, parked=2, offline_counts={MediaKind.TEXT: 4})
            gateway = FakeGateway(adapter)

            _arm_and_settle(plugin, gateway)
            first = list(adapter.sent)
            assert len([s for s in first if s[0] == "summary"]) == 1

            _arm_and_settle(plugin, gateway, event=_event(2, _source(), text="again"))

            assert adapter.sent == first, "notice must not re-fire this boot"
        finally:
            runtime.close()


def test_wake_notice_media_counts_in_n_not_m():
    """S-6.3: 2 media (RAW_PERSISTED) + 2 parked text -> N=4, M=2."""
    with tempfile.TemporaryDirectory() as directory:
        handler, runtime = _handler(Path(directory))
        plugin = _load_plugin()
        try:
            adapter, parked_ids = _setup(
                plugin, handler, parked=2,
                offline_counts={MediaKind.IMAGE: 2, MediaKind.TEXT: 2})
            gateway = FakeGateway(adapter)

            _arm_and_settle(plugin, gateway)

            summaries = [s for s in adapter.sent if s[0] == "summary"]
            keyboards = [s for s in adapter.sent if s[0] == "keyboard"]
            assert len(summaries) == 1
            assert summaries[0][2] == \
                "Llegaron 4 mensajes; tengo 2 por confirmar. ¿Las reviso?"
            assert len(keyboards) == 2
            assert {k[2] for k in keyboards} == set(parked_ids)
        finally:
            runtime.close()


def test_wake_notice_silent_when_nothing_parked():
    """Task 3.4: offline captures but M=0 -> no summary, no keyboards."""
    with tempfile.TemporaryDirectory() as directory:
        handler, runtime = _handler(Path(directory))
        plugin = _load_plugin()
        try:
            adapter, _ = _setup(
                plugin, handler, parked=0, offline_counts={MediaKind.TEXT: 3})
            gateway = FakeGateway(adapter)

            _arm_and_settle(plugin, gateway)

            assert adapter.sent == [], "M=0 must stay silent"
        finally:
            runtime.close()


def test_wake_notice_skips_without_running_loop():
    """Fallback: hook outside a running loop logs and never breaks dispatch."""
    with tempfile.TemporaryDirectory() as directory:
        handler, runtime = _handler(Path(directory))
        plugin = _load_plugin()
        try:
            plugin._handler = handler
            plugin._CAPTURE_MODE = "ai"
            plugin._boot_ts = time.time()
            adapter = FakeAdapter()

            # Sync call, no asyncio.run: get_running_loop() raises -> skipped.
            result = plugin.capture_intake_hook(
                event=_event(1, _source(), text="wake me"),
                gateway=FakeGateway(adapter),
                session_store=None,
            )

            assert result is None  # ai-mode text fall-through, no crash
            assert plugin._wake_notice_sent is True  # flag set, one-shot intact
            assert adapter.sent == []  # nothing could be scheduled
        finally:
            runtime.close()