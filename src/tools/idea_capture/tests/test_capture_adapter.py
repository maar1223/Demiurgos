"""Unit tests for CaptureTelegramAdapter (PR 2): capture callback routing + keyboard.

The adapter is loaded by file path from the project plugin; the bundled Hermes
``TelegramAdapter`` it subclasses comes from the real agent source (resolved via
``HERMES_HOME``/``HERMES_AGENT_ROOT``, see ``capture_adapter.hermes_agent_root``).
The PTB SDK is not installed in this venv, so a minimal ``telegram`` shim
provides ``InlineKeyboardButton``/``InlineKeyboardMarkup`` for the markup
assertions — mirroring the bundled adapter's own ``Any`` fallback when PTB is
absent. The runtime is built with a temporary root so no test touches the repo.
"""

import importlib.util
import sys
import tempfile
import types
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # src/tools

import asyncio

from idea_capture.config import CaptureConfig, CaptureLimits
from idea_capture.hermes_handler import IdeaCaptureHandler
from idea_capture.models import CaptureState
from idea_capture.runtime import IdeaCaptureRuntime
from idea_capture.telegram import IngressPolicy

_PLUGIN_DIR = (
    Path(__file__).resolve().parents[4]
    / ".hermes" / "plugins" / "demiurgos-idea-capture"
)
_ADAPTER_PATH = _PLUGIN_DIR / "capture_adapter.py"
_CAPTURE_PREFIX = "demiurgos-capture:"


# -- shims -------------------------------------------------------------------

class FakeInlineKeyboardButton:
    def __init__(self, *, text, callback_data):
        self.text = text
        self.callback_data = callback_data


class FakeInlineKeyboardMarkup:
    def __init__(self, inline_keyboard):
        self.inline_keyboard = inline_keyboard


def _install_telegram_shim(monkeypatch):
    """Provide a minimal ``telegram`` module when PTB is absent (as in this venv)."""
    shim = types.ModuleType("telegram")
    shim.InlineKeyboardButton = FakeInlineKeyboardButton
    shim.InlineKeyboardMarkup = FakeInlineKeyboardMarkup
    monkeypatch.setitem(sys.modules, "telegram", shim)


class FakeQuery:
    """Minimal PTB CallbackQuery stand-in recording answer/edit calls."""

    def __init__(self, *, user_id=8, chat_id=7, data="", text="Idea capturada..."):
        self.message = SimpleNamespace(chat_id=chat_id, text=text, message_id=1)
        self.from_user = SimpleNamespace(id=user_id, first_name="Tester")
        self.data = data
        self.answers = []
        self.edits = []

    async def answer(self, text=None, **kwargs):
        self.answers.append(text)

    async def edit_message_text(self, **kwargs):
        self.edits.append(kwargs)


# -- helpers -----------------------------------------------------------------


def _load_adapter_module():
    spec = importlib.util.spec_from_file_location(
        "demiurgos_capture_adapter", _ADAPTER_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _adapter(handler):
    """Build a CaptureTelegramAdapter via object.__new__ (skips the heavy
    bundled __init__; mirrors the bundled adapter tests' convention)."""
    mod = _load_adapter_module()
    adapter = mod.CaptureTelegramAdapter.__new__(mod.CaptureTelegramAdapter)
    adapter._capture_handler = handler
    return adapter, mod


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


def _source(chat_id=7, user_id=8):
    return SimpleNamespace(
        platform=SimpleNamespace(value="telegram"),
        chat_id=str(chat_id),
        user_id=str(user_id),
        chat_type="dm",
        thread_id=None,
        profile="default",
    )


def _event(update_id, source, *, text=""):
    return SimpleNamespace(
        platform_update_id=update_id,
        source=source,
        text=text,
        media_urls=[],
        media_types=[],
        media_durations=[],
        message_type=SimpleNamespace(value="text"),
        get_command=lambda: None,
    )


def _accept_capture(handler, runtime, update_id=1, text="raw idea"):
    """Persist one real capture through the runtime and return its capture_id."""
    update = handler._update_from_event(_event(update_id, _source(), text=text))
    receipt = runtime.service.accept(update)
    return receipt.capture_id


async def _run(coro):
    return await coro


# -- callback branch routing -------------------------------------------------


def test_capture_prefix_routes_to_capture_handler(monkeypatch):
    """2.1: demiurgos-capture: taps hit the capture handler, never super()."""
    with tempfile.TemporaryDirectory() as directory:
        handler, runtime = _handler(Path(directory))
        adapter, mod = _adapter(handler)
        capture_id = _accept_capture(handler, runtime)
        query = FakeQuery(data=f"{_CAPTURE_PREFIX}{capture_id}:save_global")

        capture_calls = []
        parent_calls = []

        async def fake_capture(q, data):
            capture_calls.append((q, data))

        async def fake_parent(self, update, context):
            parent_calls.append((update, context))

        monkeypatch.setattr(adapter, "_handle_capture_callback", fake_capture)
        monkeypatch.setattr(mod.TelegramAdapter, "_handle_callback_query", fake_parent)
        try:
            asyncio.run(adapter._handle_callback_query(
                SimpleNamespace(callback_query=query), context=None))
            assert len(capture_calls) == 1
            assert capture_calls[0][1] == f"{_CAPTURE_PREFIX}{capture_id}:save_global"
            assert parent_calls == []
        finally:
            runtime.close()


def test_non_capture_prefix_defers_to_super(monkeypatch):
    """2.1: any other prefix (mp:/cp:/ea:/...) still reaches the parent."""
    with tempfile.TemporaryDirectory() as directory:
        handler, runtime = _handler(Path(directory))
        adapter, mod = _adapter(handler)

        capture_calls = []
        parent_calls = []

        async def fake_capture(self, q, data):
            capture_calls.append((q, data))

        async def fake_parent(self, update, context):
            parent_calls.append((update, context))

        monkeypatch.setattr(adapter, "_handle_capture_callback", fake_capture)
        monkeypatch.setattr(mod.TelegramAdapter, "_handle_callback_query", fake_parent)
        try:
            for prefix in ("mp:", "cp:", "gt:", "ea:once:1", "sc:always:1", "cl:1:0",
                           "update_prompt:y", "unknown-prefix:1"):
                query = FakeQuery(data=prefix)
                asyncio.run(adapter._handle_callback_query(
                    SimpleNamespace(callback_query=query), context=None))
            assert capture_calls == []
            assert len(parent_calls) == 8
        finally:
            runtime.close()


# -- Guardar / Descartar ------------------------------------------------------


def test_save_global_confirms_and_strips_buttons():
    """2.3 / S-6.1: Guardar -> runtime.confirm(id, SAVE_GLOBAL), buttons stripped."""
    with tempfile.TemporaryDirectory() as directory:
        handler, runtime = _handler(Path(directory))
        adapter, _ = _adapter(handler)
        capture_id = _accept_capture(handler, runtime)
        query = FakeQuery(data=f"{_CAPTURE_PREFIX}{capture_id}:save_global")
        try:
            asyncio.run(adapter._handle_capture_callback(query, query.data))
            record = runtime.store.get(capture_id)
            assert record.global_  # SAVE_GLOBAL confirm applied
            assert record.state is not CaptureState.RAW_PERSISTED  # durable path started
            assert query.answers[-1] == "Idea guardada en el Taller de Ideas (procesando...)."
            assert query.edits[-1] == {"text": "Idea guardada en el Taller de Ideas (procesando...).",
                                       "reply_markup": None}
        finally:
            runtime.close()


def test_discard_cancels_capture():
    """Descartar -> runtime.confirm(id, CANCEL), capture cancelled, buttons stripped."""
    with tempfile.TemporaryDirectory() as directory:
        handler, runtime = _handler(Path(directory))
        adapter, _ = _adapter(handler)
        capture_id = _accept_capture(handler, runtime)
        query = FakeQuery(data=f"{_CAPTURE_PREFIX}{capture_id}:cancel")
        try:
            asyncio.run(adapter._handle_capture_callback(query, query.data))
            record = runtime.store.get(capture_id)
            assert record.state is CaptureState.CANCELLED
            assert query.answers[-1] == "Idea cancelada."
            assert query.edits[-1] == {"text": "Idea cancelada.", "reply_markup": None}
        finally:
            runtime.close()


def test_unauthorized_callback_rejected():
    """2.4 / S-6.3: unauthorized user -> 'No autorizado.', no state change."""
    with tempfile.TemporaryDirectory() as directory:
        handler, runtime = _handler(Path(directory))
        adapter, _ = _adapter(handler)
        capture_id = _accept_capture(handler, runtime)
        query = FakeQuery(user_id=99, data=f"{_CAPTURE_PREFIX}{capture_id}:save_global")
        try:
            asyncio.run(adapter._handle_capture_callback(query, query.data))
            record = runtime.store.get(capture_id)
            assert record.state is CaptureState.RAW_PERSISTED  # never mutated
            assert query.answers[-1] == "No autorizado."
            assert query.edits[-1] == {"text": "No autorizado.", "reply_markup": None}
        finally:
            runtime.close()


def test_unauthorized_binding_requires_full_chat_and_user():
    """R-8 / fail closed: missing chat or user identity never confirms."""
    with tempfile.TemporaryDirectory() as directory:
        handler, runtime = _handler(Path(directory))
        adapter, _ = _adapter(handler)
        capture_id = _accept_capture(handler, runtime)
        try:
            # No message (inline query) -> no chat_id -> fail closed.
            query = FakeQuery(data=f"{_CAPTURE_PREFIX}{capture_id}:save_global")
            query.message = None
            asyncio.run(adapter._handle_capture_callback(query, query.data))
            assert query.answers[-1] == "No autorizado."
            assert runtime.store.get(capture_id).state is CaptureState.RAW_PERSISTED
        finally:
            runtime.close()


# -- idempotency / stale taps ------------------------------------------------


def test_stale_button_idempotent_after_confirm(monkeypatch):
    """2.5 / S-6.5: a second tap after confirm -> 'Ya resuelta.', no double-write."""
    with tempfile.TemporaryDirectory() as directory:
        handler, runtime = _handler(Path(directory))
        adapter, _ = _adapter(handler)
        capture_id = _accept_capture(handler, runtime)
        query = FakeQuery(data=f"{_CAPTURE_PREFIX}{capture_id}:save_global")

        confirms = []

        def recording_confirm(cid, action, selected_world=None):
            confirms.append((cid, action, selected_world))

        try:
            # First tap resolves normally (REAL confirm -> global bank).
            asyncio.run(adapter._handle_capture_callback(query, query.data))
            record = runtime.store.get(capture_id)
            assert record.global_  # SAVE_GLOBAL confirm applied
            assert record.state is not CaptureState.RAW_PERSISTED

            # Second tap (stale): capture is no longer confirmable -> the state
            # gate must fire BEFORE any confirm; a recorder would catch a
            # re-confirm.
            monkeypatch.setattr(handler.runtime, "confirm", recording_confirm)
            query2 = FakeQuery(data=f"{_CAPTURE_PREFIX}{capture_id}:save_global")
            asyncio.run(adapter._handle_capture_callback(query2, query2.data))
            assert query2.answers[-1] == "Ya resuelta."
            assert confirms == []  # no double-write
            assert query2.edits == []  # already stripped, nothing to edit
        finally:
            runtime.close()


def test_unknown_capture_id_answered_gracefully():
    """S-6.4: unknown/missing capture id -> 'Ya resuelta.', no crash."""
    with tempfile.TemporaryDirectory() as directory:
        handler, runtime = _handler(Path(directory))
        adapter, _ = _adapter(handler)
        missing_id = "00000000-0000-0000-0000-000000000000"
        query = FakeQuery(data=f"{_CAPTURE_PREFIX}{missing_id}:save_global")
        try:
            asyncio.run(adapter._handle_capture_callback(query, query.data))
            assert query.answers[-1] == "Ya resuelta."
            assert query.edits == []
        finally:
            runtime.close()


def test_invalid_callback_data_answered_gracefully():
    """Malformed capture data -> 'Acción inválida.', never touches the store."""
    with tempfile.TemporaryDirectory() as directory:
        handler, runtime = _handler(Path(directory))
        adapter, _ = _adapter(handler)
        capture_id = _accept_capture(handler, runtime)
        try:
            for bad in (f"{_CAPTURE_PREFIX}garbage", f"{_CAPTURE_PREFIX}",
                        f"{_CAPTURE_PREFIX}{capture_id}:bogus"):
                query = FakeQuery(data=bad)
                asyncio.run(adapter._handle_capture_callback(query, query.data))
                assert query.answers[-1] == "Acción inválida.", bad
                assert query.edits == []
            assert runtime.store.get(capture_id).state is CaptureState.RAW_PERSISTED
        finally:
            runtime.close()


# -- keyboard rendering -------------------------------------------------------


def test_keyboard_rendered_with_ptb_markup(monkeypatch):
    """2.6/2.7 / R-7: send_capture_prompt uses real PTB markup, data <= 64 bytes."""
    _install_telegram_shim(monkeypatch)
    with tempfile.TemporaryDirectory() as directory:
        handler, runtime = _handler(Path(directory))
        adapter, _ = _adapter(handler)
        capture_id = _accept_capture(handler, runtime)

        sent = {}

        async def fake_send(**kwargs):
            sent.update(kwargs)

        monkeypatch.setattr(adapter, "_send_message_with_thread_fallback", fake_send)
        try:
            asyncio.run(adapter.send_capture_prompt(
                chat_id="7", capture_id=capture_id))
            assert sent["chat_id"] == "7"
            assert f"Idea capturada (id=`{capture_id}`). Elegí una acción:" == sent["text"]
            markup = sent["reply_markup"]
            assert isinstance(markup, FakeInlineKeyboardMarkup)
            row = markup.inline_keyboard[0]
            assert [btn.text for btn in row] == [
                "Guardar en Taller de Ideas", "Cancelar"]
            for btn in row:
                assert len(btn.callback_data) <= 64
                assert btn.callback_data.startswith("capture:")
            assert "message_thread_id" not in sent

            asyncio.run(adapter.send_capture_prompt(
                chat_id="7", capture_id=capture_id, thread_id=42))
            assert sent["message_thread_id"] == 42
        finally:
            runtime.close()


# -- capability checks --------------------------------------------------------


def test_verify_bundled_adapter_surface_passes():
    """Capability check: the real bundled adapter still exposes every helper."""
    with tempfile.TemporaryDirectory() as directory:
        handler, runtime = _handler(Path(directory))
        _, mod = _adapter(handler)
        try:
            mod.verify_bundled_adapter_surface()  # must not raise
            assert callable(mod.capture_platform_deps_ready)
        finally:
            runtime.close()


# -- bundled behavior preservation (PR 4 / S-5.1) -----------------------------


def test_adapter_preserves_bundled_behavior(monkeypatch):
    """4.5 / S-5.1: media caching, album merge, and threads stay on the parent.

    The subclass exists ONLY for capture routing/keyboard (R-5: subclass,
    never a copy). The methods that implement bundled behavior — media
    caching + album merge (``_handle_media_message`` / ``_handle_text_message``)
    and the thread fallback send (``_send_message_with_thread_fallback``) —
    must be the parent's own function objects, inherited verbatim. And any
    non-capture callback must still defer to ``super()`` untouched, so the
    bundled callback handlers keep working.
    """
    with tempfile.TemporaryDirectory() as directory:
        handler, runtime = _handler(Path(directory))
        adapter, mod = _adapter(handler)
        try:
            # 1. Class-level: the bundled behavior is inherited, not re-implemented.
            for name in ("_handle_media_message", "_handle_text_message",
                         "_handle_location_message",
                         "_send_message_with_thread_fallback"):
                assert getattr(mod.CaptureTelegramAdapter, name) is getattr(
                    mod.TelegramAdapter, name), name

            # 2. Behavior-level: a non-capture callback reaches super() exactly
            #    once (mock the parent call), preserving the bundled handler.
            parent_calls = []

            async def fake_parent(self, update, context):
                parent_calls.append((update, context))

            monkeypatch.setattr(mod.TelegramAdapter, "_handle_callback_query",
                                fake_parent)
            query = FakeQuery(data="mp:preserved-payload")
            asyncio.run(adapter._handle_callback_query(
                SimpleNamespace(callback_query=query), context=None))
            assert len(parent_calls) == 1
            assert parent_calls[0][0].callback_query.data == "mp:preserved-payload"
        finally:
            runtime.close()