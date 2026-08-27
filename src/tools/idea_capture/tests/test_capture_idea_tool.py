"""R-3 tests: the capture_idea tool (ai mode).

The tool is registered only in ``ai`` mode and lets the assistant capture an
idea/seed by calling ``service.accept`` through a synthetic ``TelegramUpdate``
built from the tool payload. It must reject sessions that are not the
authorized capture binding before any accept happens.
"""

import asyncio
import gc
import importlib.util
import json
import sys
import tempfile
import time
import types
import warnings
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


def test_tool_always_parks_for_confirmation(monkeypatch):
    """Opción A: capture_idea NEVER auto-saves — always parks + schedules keyboard.

    There is no more auto-SAVE_GLOBAL from the tool: the capture lands in
    AWAITING_CONFIRM and the Guardar/Descartar keyboard is scheduled; only the
    user's tap (``runtime.confirm`` SAVE_GLOBAL via the keyboard or the web
    review panel) moves it to the Taller de Ideas.
    """
    with tempfile.TemporaryDirectory() as directory:
        handler, runtime = _handler(Path(directory))
        plugin = _setup_tool(monkeypatch)
        plugin._handler = handler
        scheduled = []
        confirms = []

        class FakeAdapter:
            pass

        class FakeGateway:
            def _adapter_for_source(self, source):
                return FakeAdapter()

        plugin._active_gateway = FakeGateway()
        monkeypatch.setattr(
            plugin, "_schedule_capture_prompt",
            lambda adapter, source, capture_id: scheduled.append(capture_id))
        monkeypatch.setattr(
            runtime, "confirm",
            lambda capture_id, action, selected_world=None: confirms.append(
                (capture_id, action)))
        try:
            result = _call(plugin, {"text": "a forge that remembers"})
            assert result["status"] == "RAW_PERSISTED"
            record = runtime.store.get(result["capture_id"])
            assert record.state is CaptureState.AWAITING_CONFIRM
            assert runtime.store.count_pending_confirm() == 1
            assert scheduled == [result["capture_id"]]  # keyboard scheduled
            assert confirms == []  # NO auto-SAVE_GLOBAL from the tool
        finally:
            runtime.close()


def test_same_payload_dedupes(monkeypatch):
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


# -- idea-capture-confirm-queue (Opción A): capture_idea always parks ----------


def test_confirm_true_parks_too(monkeypatch):
    """Opción A: even confirm=true parks — the field no longer auto-saves.

    The park path is unconditional; the deprecated ``confirm`` value never
    triggers SAVE_GLOBAL (the capture stays AWAITING_CONFIRM for the user).
    """
    with tempfile.TemporaryDirectory() as directory:
        handler, runtime = _handler(Path(directory))
        plugin = _setup_tool(monkeypatch)
        plugin._handler = handler
        confirms = []
        monkeypatch.setattr(
            runtime, "confirm",
            lambda capture_id, action, selected_world=None: confirms.append(
                (capture_id, action)))
        try:
            result = _call(plugin, {"text": "explicit save idea", "confirm": True})
            assert result["status"] == "RAW_PERSISTED"
            record = runtime.store.get(result["capture_id"])
            assert record.state is CaptureState.AWAITING_CONFIRM
            assert record.state is not CaptureState.SAVED
            assert runtime.store.count_pending_confirm() == 1
            assert confirms == []  # confirm=true never auto-saves anymore
        finally:
            runtime.close()


def test_confirm_false_parks_without_autosave(monkeypatch):
    """S-4.2: confirm=false -> AWAITING_CONFIRM, no auto-save, prompt scheduled.

    The park branch must NOT call runtime.confirm (no SAVE_GLOBAL, no worker
    submit): the capture stays raw until the user taps Guardar/Descartar.
    ``_schedule_park_prompt`` resolves the adapter through ``_active_gateway``
    and hands off to ``_schedule_capture_prompt`` — spied here so the test does
    not need a running loop.
    """
    with tempfile.TemporaryDirectory() as directory:
        handler, runtime = _handler(Path(directory))
        plugin = _setup_tool(monkeypatch)
        plugin._handler = handler
        scheduled = []

        class FakeAdapter:
            pass

        class FakeGateway:
            def _adapter_for_source(self, source):
                return FakeAdapter()

        plugin._active_gateway = FakeGateway()
        monkeypatch.setattr(
            plugin, "_schedule_capture_prompt",
            lambda adapter, source, capture_id: scheduled.append(capture_id))
        try:
            result = _call(plugin, {"text": "maybe an idea", "confirm": False})
            assert result["status"] == "RAW_PERSISTED"
            record = runtime.store.get(result["capture_id"])
            assert record.state is CaptureState.AWAITING_CONFIRM
            assert record.state not in (CaptureState.PROCESSING, CaptureState.SAVED)
            assert runtime.store.count_pending_confirm() == 1
            assert scheduled == [result["capture_id"]]  # keyboard scheduled
        finally:
            runtime.close()


def test_park_schedules_keyboard_via_active_gateway(monkeypatch):
    """2.x: the park branch schedules the real send_capture_prompt coroutine.

    With a running loop, ``_schedule_capture_prompt`` must actually schedule
    ``send_capture_prompt`` on the adapter resolved via ``_active_gateway`` —
    the Guardar/Descartar keyboard really goes out (S-4.2).
    """
    with tempfile.TemporaryDirectory() as directory:
        handler, runtime = _handler(Path(directory))
        plugin = _setup_tool(monkeypatch)
        plugin._handler = handler
        sent = []

        class FakeAdapter:
            async def send_capture_prompt(self, *, chat_id, capture_id, thread_id=None):
                sent.append((chat_id, capture_id, thread_id))

        class FakeGateway:
            def _adapter_for_source(self, source):
                return FakeAdapter()

        plugin._active_gateway = FakeGateway()

        async def _run():
            result = _call(plugin, {"text": "parked via gateway", "confirm": False})
            await asyncio.sleep(0)  # let the scheduled prompt task fire
            return result

        try:
            result = asyncio.run(_run())
            record = runtime.store.get(result["capture_id"])
            assert record.state is CaptureState.AWAITING_CONFIRM
            assert sent, "park branch must schedule the keyboard prompt"
            chat_id, capture_id, thread_id = sent[0]
            assert chat_id == "7"  # session chat
            assert capture_id == result["capture_id"]
            assert thread_id is None
        finally:
            runtime.close()


def test_park_sends_keyboard_without_running_loop(monkeypatch):
    """Bug fix: a loop-less (sync) tool handler still sends the keyboard.

    The tool handler runs on a gateway worker thread with NO running event
    loop, so the old ``asyncio.create_task`` raised "no running event loop"
    and the Guardar/Descartar keyboard never reached the user (only a
    warning, plus a leaked un-awaited coroutine). The fix must send the
    prompt from a background thread's own loop: the keyboard really goes out,
    no coroutine is left un-awaited, and the turn is never blocked.
    """
    with tempfile.TemporaryDirectory() as directory:
        handler, runtime = _handler(Path(directory))
        plugin = _setup_tool(monkeypatch)
        plugin._handler = handler
        sent = []

        class FakeAdapter:
            async def send_capture_prompt(self, *, chat_id, capture_id, thread_id=None):
                sent.append((chat_id, capture_id, thread_id))

        class FakeGateway:
            def _adapter_for_source(self, source):
                return FakeAdapter()

        plugin._active_gateway = FakeGateway()
        try:
            # Plain sync call, NO asyncio.run: exactly the loop-less worker
            # thread the gateway uses for sync tool handlers.
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                result = _call(plugin, {"text": "parked without loop",
                                        "confirm": False})
                gc.collect()  # force any leaked coroutine to warn immediately
            assert result["status"] == "RAW_PERSISTED"
            record = runtime.store.get(result["capture_id"])
            assert record.state is CaptureState.AWAITING_CONFIRM

            # The background thread must deliver the keyboard prompt.
            deadline = time.monotonic() + 5.0
            while not sent and time.monotonic() < deadline:
                time.sleep(0.02)
            assert sent, "no-loop park must still send the keyboard prompt"
            chat_id, capture_id, thread_id = sent[0]
            assert chat_id == "7"  # session chat
            assert capture_id == result["capture_id"]
            assert thread_id is None

            # No coroutine may leak un-awaited (the live-test RuntimeWarning).
            unawaited = [w for w in caught
                         if "never awaited" in str(w.message)]
            assert unawaited == [], f"leaked coroutine warnings: {unawaited}"
        finally:
            runtime.close()


def test_dedup_hash_excludes_confirm(monkeypatch):
    """S-4.3: confirm=true / confirm=false / omitted -> the same update id.

    The dedup hash keys on capture CONTENT only; the confirm intent (which the
    guidance picks per turn) must never split the same material into two rows.
    """
    plugin = _setup_tool(monkeypatch)
    assert plugin._synthetic_update_id({"text": "same material", "confirm": True}) == \
        plugin._synthetic_update_id({"text": "same material", "confirm": False})
    assert plugin._synthetic_update_id({"text": "same material"}) == \
        plugin._synthetic_update_id({"text": "same material", "confirm": False})
    assert plugin._synthetic_update_id({"text": "same material", "confirm": False}) != \
        plugin._synthetic_update_id({"text": "different material", "confirm": False})


def test_same_material_true_then_false_dedupes(monkeypatch):
    """S-4.3 flow: same text with confirm=true then confirm=false -> one row.

    Both calls park under Opción A, and the second is a content DUPLICATE —
    the deprecated confirm value never creates a second row.
    """
    with tempfile.TemporaryDirectory() as directory:
        handler, runtime = _handler(Path(directory))
        plugin = _setup_tool(monkeypatch)
        plugin._handler = handler
        try:
            first = _call(plugin, {"text": "one idea either way", "confirm": True})
            second = _call(plugin, {"text": "one idea either way", "confirm": False})
            assert first["status"] == "RAW_PERSISTED"
            assert second["status"] == "DUPLICATE"
            assert second["capture_id"] == first["capture_id"]
            assert runtime.store.count() == 1  # no new record persisted
        finally:
            runtime.close()


def test_different_material_parks_two_captures(monkeypatch):
    """Opción A: dedup keys on content, so different material -> 2 parked rows.

    Both calls now PARK (no auto-save): each capture lands in AWAITING_CONFIRM
    and waits for the user's Guardar/Descartar decision.
    """
    with tempfile.TemporaryDirectory() as directory:
        handler, runtime = _handler(Path(directory))
        plugin = _setup_tool(monkeypatch)
        plugin._handler = handler
        try:
            first = _call(plugin, {"text": "clear idea"})
            second = _call(plugin, {"text": "vague thought"})
            assert first["capture_id"] != second["capture_id"]
            assert runtime.store.count() == 2
            assert runtime.store.count_pending_confirm() == 2
            assert runtime.store.get(first["capture_id"]).state is \
                CaptureState.AWAITING_CONFIRM
            assert runtime.store.get(second["capture_id"]).state is \
                CaptureState.AWAITING_CONFIRM
        finally:
            runtime.close()