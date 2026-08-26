import asyncio
import tempfile
from pathlib import Path
from types import SimpleNamespace

from idea_capture.config import CaptureConfig, CaptureLimits
from idea_capture.hermes_handler import IdeaCaptureHandler
from idea_capture.models import CaptureState
from idea_capture.runtime import IdeaCaptureRuntime
from idea_capture.telegram import IngressPolicy


def _source(chat_id=7, user_id=8, *, chat_type="dm"):
    return SimpleNamespace(
        platform=SimpleNamespace(value="telegram"),
        chat_id=str(chat_id),
        user_id=str(user_id),
        chat_type=chat_type,
        thread_id=None,
        profile="default",
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
        get_command=lambda: text.split(maxsplit=1)[0][1:].lower()
        if text.startswith("/") else None,
    )


class FakeAdapter:
    def __init__(self):
        self.sent = []
        self.interaction_messages = []

    async def send(self, chat_id, content, **kwargs):
        self.sent.append((chat_id, content, kwargs))

    async def send_interaction_message(self, chat_id, content, buttons, **kwargs):
        self.interaction_messages.append((chat_id, content, buttons, kwargs))


class FakeInteraction:
    def __init__(self, data, source):
        self.data = data
        self.source = source
        self.answers = []
        self.edits = []
        self.sent = []

    async def answer(self, text=None):
        self.answers.append(text)

    async def edit(self, content, buttons=None):
        self.edits.append((content, buttons))

    async def send(self, content, buttons=None):
        self.sent.append((content, buttons))


def _handler(root: Path, *, enrich=None, media_reader=None):
    (root / "mundos" / "vibrantes").mkdir(parents=True)
    (root / "mundos" / "nec").mkdir()
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
    )
    config = root / "idea-capture.yaml"
    config.write_text(
        "authorized_bindings:\n"
        "  - platform: telegram\n"
        "    chat_id: 7\n"
        "    user_id: 8\n"
        "    profile: default\n"
        "active_world: vibrantes\n",
        encoding="utf-8",
    )
    return IdeaCaptureHandler(
        repo_root=root,
        config_path=config,
        mundos_root=root / "mundos",
        runtime=runtime,
        media_reader=media_reader or (lambda _: b"\x89PNG\r\n\x1a\nraw-image"),
    ), runtime


def test_text_is_raw_persisted_and_duplicate_is_idempotent():
    with tempfile.TemporaryDirectory() as directory:
        handler, runtime = _handler(Path(directory))
        adapter = FakeAdapter()
        try:
            event = _event(1, _source(), text="  raw idea  ")
            assert asyncio.run(handler.handle_message(event=event, adapter=adapter))
            assert asyncio.run(handler.handle_message(event=event, adapter=adapter))
            record = runtime.store.get(runtime.store.list_capture_ids()[0])
            assert record.raw_text == "  raw idea  "
            assert record.media_kind.value == "text"
            assert len(adapter.interaction_messages) == 1
            assert len(adapter.interaction_messages[0][2]) == 1
        finally:
            runtime.close()


def test_media_cache_metadata_and_caption_are_persisted_raw_first():
    with tempfile.TemporaryDirectory() as directory:
        handler, runtime = _handler(Path(directory))
        cache_path = ".hermes/cache/images/img.png"
        try:
            event = _event(
                2, _source(), text="caption", media_urls=[cache_path],
                media_types=["image/png"], message_type="photo", durations=[None],
            )
            asyncio.run(handler.handle_message(event=event, adapter=FakeAdapter()))
            record = runtime.store.get(runtime.store.list_capture_ids()[0])
            assert record.media_kind.value == "image"
            assert record.raw_text == "caption"
            assert record.raw_bytes.startswith(b"\x89PNG")
            assert record.mime == "image/png"
            assert record.media_path == cache_path

            voice_handler, voice_runtime = _handler(
                Path(directory) / "voice",
                media_reader=lambda _: b"OggS raw-voice",
            )
            try:
                voice_update = voice_handler._update_from_event(_event(
                    4, _source(), media_urls=[".hermes/cache/audio/voice.ogg"],
                    media_types=["audio/ogg"], message_type="voice", durations=[2.5],
                ))
                assert voice_update.media.duration_seconds == 2.5
                assert voice_update.media.path.endswith("voice.ogg")
            finally:
                voice_runtime.close()
        finally:
            runtime.close()


def test_capture_keyboard_has_fourth_global_button():
    with tempfile.TemporaryDirectory() as directory:
        handler, runtime = _handler(Path(directory))
        adapter = FakeAdapter()
        try:
            event = _event(6, _source(), text="keyboard idea")
            asyncio.run(handler.handle_message(event=event, adapter=adapter))
            buttons = adapter.interaction_messages[0][2][0]
            texts = [b["text"] for b in buttons]
            assert texts == ["Guardar", "Cambiar mundo", "Cancelar", "Guardar global"]
            assert any(b["callback_data"].endswith(":save_global") for b in buttons)
        finally:
            runtime.close()


def test_save_global_callback_writes_to_global_bank_without_world():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
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
            enrich=lambda raw: (raw, "concepto"),
            global_ideas_root=root / "ideas",
        )
        config = root / "idea-capture.yaml"
        config.write_text(
            "authorized_bindings:\n"
            "  - platform: telegram\n"
            "    chat_id: 7\n"
            "    user_id: 8\n"
            "    profile: default\n"
            "active_world: vibrantes\n",
            encoding="utf-8",
        )
        handler = IdeaCaptureHandler(
            repo_root=root,
            config_path=config,
            mundos_root=root / "mundos",
            runtime=runtime,
        )
        try:
            event = _event(5, _source(), text="bank idea")
            asyncio.run(handler.handle_message(event=event, adapter=FakeAdapter()))
            capture_id = runtime.store.list_capture_ids()[0]
            interaction = FakeInteraction(
                f"capture:{capture_id}:save_global", _source(),
            )
            assert asyncio.run(handler.handle_interaction(interaction=interaction))
            record = runtime.wait_state(capture_id, CaptureState.SAVED)
            assert record.global_ is True
            assert record.world is None
            assert (root / "ideas" / f"{record.slug}.md").exists()
            assert interaction.answers == ["Idea guardada en el banco global (procesando...)."]
            assert interaction.edits == [
                ("Idea guardada en el banco global (procesando...).", [])]
        finally:
            runtime.close()


def test_callback_requires_exact_identity_and_confirms_world_asynchronously():
    with tempfile.TemporaryDirectory() as directory:
        handler, runtime = _handler(Path(directory), enrich=lambda raw: raw)
        adapter = FakeAdapter()
        try:
            event = _event(3, _source(), text="save me")
            asyncio.run(handler.handle_message(event=event, adapter=adapter))
            capture_id = runtime.store.list_capture_ids()[0]
            interaction = FakeInteraction(
                f"capture:{capture_id}:world:nec", _source(),
            )
            assert asyncio.run(handler.handle_interaction(interaction=interaction))
            record = runtime.wait_state(capture_id, CaptureState.SAVED)
            assert record.world == "nec"
            assert interaction.answers == ["Idea asignada a nec (procesando...)."]
            assert interaction.edits == [("Idea asignada a nec (procesando...).", [])]

            unauthorized = FakeInteraction(
                f"capture:{capture_id}:cancel", _source(user_id=99),
            )
            asyncio.run(handler.handle_interaction(interaction=unauthorized))
            assert unauthorized.answers == ["No autorizado."]
            assert runtime.store.get(capture_id).state is CaptureState.SAVED
        finally:
            runtime.close()
