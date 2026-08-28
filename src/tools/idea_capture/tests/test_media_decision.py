"""SDD bot-capture-and-conversation Slice 2 (media decision) tests.

Covers the ai-mode media routing change (R-2.1/R-2.2/R-2.3/R-2.4):

- media events (voice/image) in ``ai`` mode NEVER auto-capture: the intake
  hook falls through (``None``) so the assistant decides idea-vs-conversation
  (S-2.1.x / S-2.2.x), and the real media bytes are stashed for the save
  branch (``_MEDIA_STASH``, T-2.3);
- ``capture_idea`` attaches the stashed bytes when the assistant decides
  "idea" -> parked + Guardar/Descartar keyboard (S-2.3.1);
- a "conversation" decision saves nothing and the stash entry dies via the
  5-minute TTL (S-2.3.3);
- ``strict`` mode auto-captures media exactly as before (S-2.1.3 / S-2.2.3);
- text turns in ``ai`` mode are unchanged (S-2.4.x);
- the description seam ``MediaEnrichProvider.describe()`` returns the raw
  transcript / vision ``descripcion`` via ``build_media_enrich_provider``
  components (T-2.2) and fails open.

Hook-contract finding (verified against the installed Hermes gateway): the
``pre_gateway_dispatch`` contract DOES support ``{"action": "rewrite",
"text": ...}`` (gateway/run.py:14756-14761 replaces ``event.text`` and
continues dispatch). The design proposed using it for media events, but the
gateway's own media pipeline (``_enrich_message_with_transcription`` for
voice, ``_enrich_message_with_vision`` / native image routing for images)
PREPENDS its own transcript/description onto ``event.text``, so rewriting
would double-transcribe / double-describe and duplicate the turn text. This
implementation therefore returns ``None`` (fall-through) for media in ai mode
and lets the gateway produce the description exactly once; the stash preserves
the bytes for the save branch. ``test_media_hook_never_rewrites`` locks the
fall-through contract in.
"""

import asyncio
import importlib.util
import json
import sys
import tempfile
import types
from pathlib import Path
from types import SimpleNamespace

import idea_capture.hermes_handler as hermes_handler
from idea_capture.config import CaptureConfig, CaptureLimits
from idea_capture.enrich import MediaEnrichProvider
from idea_capture.hermes_handler import IdeaCaptureHandler
from idea_capture.models import CaptureState, MediaKind
from idea_capture.runtime import IdeaCaptureRuntime
from idea_capture.telegram import IngressPolicy

_PLUGIN_PATH = (
    Path(__file__).resolve().parents[4]
    / ".hermes" / "plugins" / "demiurgos-idea-capture" / "__init__.py"
)

_IMAGE_BYTES = b"\x89PNG\r\n\x1a\nfake-image"
_VOICE_BYTES = b"OggS\x01fake-voice"


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
        global_ideas_root=root / "ideas",
        enrich=enrich,
    )
    handler = IdeaCaptureHandler(
        repo_root=root,
        config_path=root / "idea-capture.yaml",
        mundos_root=root / "mundos",
        runtime=runtime,
        media_reader=media_reader or (lambda _: b"\x89PNG\r\n\x1a\nfake-image"),
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


def _capture(plugin, args) -> dict:
    return json.loads(plugin._capture_idea_tool(args))


def _install_park_gateway(plugin, monkeypatch, adapter):
    """Point the park path at a fake adapter and record keyboard scheduling."""
    plugin._active_gateway = FakeGateway(adapter)
    scheduled = []
    monkeypatch.setattr(
        plugin, "_schedule_capture_prompt",
        lambda adapter, source, capture_id: scheduled.append(capture_id))
    return scheduled


# ---------------------------------------------------------------------------
# ai mode: voice with an "idea" decision -> parked + button, media attached
# ---------------------------------------------------------------------------


def test_ai_voice_idea_decision_parks_with_real_media(monkeypatch):
    """S-2.1.1 + S-2.3.1: voice -> fall-through + stash; capture_idea attaches.

    The hook stashes the voice path; the assistant decides "idea" and calls
    capture_idea(text=<transcript>); the tool attaches the REAL bytes from
    the stash, parks in AWAITING_CONFIRM and schedules the keyboard.
    """
    with tempfile.TemporaryDirectory() as directory:
        adapter = FakeAdapter()
        handler, runtime = _handler(
            Path(directory),
            media_reader=lambda p: _VOICE_BYTES if "audio" in str(p) else _IMAGE_BYTES,
        )
        plugin = _load_plugin()
        plugin._handler = handler
        plugin._CAPTURE_MODE = "ai"
        monkeypatch.setattr(hermes_handler, "_probe_voice_duration",
                            lambda path: 12.5)
        scheduled = _install_park_gateway(plugin, monkeypatch, adapter)
        try:
            voice = _event(1, _source(),
                           media_urls=[".hermes/cache/audio/note.ogg"],
                           media_types=["audio/ogg"], message_type="voice")
            result = _run_hook(plugin, event=voice,
                               gateway=FakeGateway(adapter), session_store=None)
            assert result is None  # assistant decides (never skip)
            assert runtime.store.count() == 0  # nothing captured by the hook
            assert plugin._MEDIA_STASH[("7", "8")]["type"] == "voice"

            _session(monkeypatch)
            receipt = _capture(plugin, {"text": "Remember to buy milk"})
            assert receipt["status"] == "RAW_PERSISTED"
            record = runtime.store.get(receipt["capture_id"])
            assert record.media_kind is MediaKind.VOICE
            assert record.raw_bytes == _VOICE_BYTES  # real media attached
            assert record.media_duration_seconds == 12.5
            assert record.state is CaptureState.AWAITING_CONFIRM  # parked
            assert scheduled == [receipt["capture_id"]]  # keyboard scheduled
            assert plugin._MEDIA_STASH == {}  # stash consumed on capture
        finally:
            runtime.close()


def test_ai_image_idea_decision_parks_with_real_media(monkeypatch):
    """S-2.2.1 + S-2.3.1: image -> fall-through + stash; capture_idea attaches."""
    with tempfile.TemporaryDirectory() as directory:
        adapter = FakeAdapter()
        handler, runtime = _handler(
            Path(directory),
            media_reader=lambda p: _VOICE_BYTES if "audio" in str(p) else _IMAGE_BYTES,
        )
        plugin = _load_plugin()
        plugin._handler = handler
        plugin._CAPTURE_MODE = "ai"
        scheduled = _install_park_gateway(plugin, monkeypatch, adapter)
        try:
            photo = _event(2, _source(), text="a sketch of a castle tower",
                           media_urls=[".hermes/cache/images/sketch.png"],
                           media_types=["image/png"], message_type="photo")
            result = _run_hook(plugin, event=photo,
                               gateway=FakeGateway(adapter), session_store=None)
            assert result is None
            assert plugin._MEDIA_STASH[("7", "8")]["type"] == "image"

            _session(monkeypatch)
            receipt = _capture(plugin, {"text": "a sketch of a castle tower"})
            assert receipt["status"] == "RAW_PERSISTED"
            record = runtime.store.get(receipt["capture_id"])
            assert record.media_kind is MediaKind.IMAGE
            assert record.raw_bytes == _IMAGE_BYTES  # real media attached
            assert record.raw_text == "a sketch of a castle tower"
            assert record.state is CaptureState.AWAITING_CONFIRM
            assert scheduled == [receipt["capture_id"]]
        finally:
            runtime.close()


# ---------------------------------------------------------------------------
# ai mode: media with a "conversation" decision -> NOT saved
# ---------------------------------------------------------------------------


def test_ai_voice_conversation_decision_not_saved_and_ttl_cleaned(monkeypatch):
    """S-2.1.2 + S-2.3.3: voice -> fall-through; assistant converses, no capture.

    Without a ``capture_idea`` call nothing is persisted, and the stash entry
    is removed once its TTL elapses (lazy sweep) — no media leak.
    """
    with tempfile.TemporaryDirectory() as directory:
        adapter = FakeAdapter()
        handler, runtime = _handler(Path(directory))
        plugin = _load_plugin()
        plugin._handler = handler
        plugin._CAPTURE_MODE = "ai"
        try:
            voice = _event(1, _source(),
                           media_urls=[".hermes/cache/audio/note.ogg"],
                           media_types=["audio/ogg"], message_type="voice")
            assert _run_hook(plugin, event=voice,
                             gateway=FakeGateway(adapter),
                             session_store=None) is None
            assert ("7", "8") in plugin._MEDIA_STASH
            assert runtime.store.count() == 0  # nothing saved

            # The assistant decided "conversation": no capture_idea call ever
            # runs. When the TTL elapses the lazy sweep drops the entry.
            plugin._MEDIA_STASH[("7", "8")]["stored_at"] = 0.0  # force expiry
            plugin._MEDIA_STASH_TTL = 300.0
            plugin._stash_sweep()
            assert plugin._MEDIA_STASH == {}
        finally:
            runtime.close()


def test_ai_image_conversation_decision_not_saved(monkeypatch):
    """S-2.2.2: image -> fall-through; assistant converses, never saved."""
    with tempfile.TemporaryDirectory() as directory:
        adapter = FakeAdapter()
        handler, runtime = _handler(Path(directory))
        plugin = _load_plugin()
        plugin._handler = handler
        plugin._CAPTURE_MODE = "ai"
        try:
            photo = _event(2, _source(),
                           media_urls=[".hermes/cache/images/error.png"],
                           media_types=["image/png"], message_type="photo")
            assert _run_hook(plugin, event=photo,
                             gateway=FakeGateway(adapter),
                             session_store=None) is None
            assert ("7", "8") in plugin._MEDIA_STASH
            assert runtime.store.count() == 0  # no capture, no save
            # TTL cleanup also applies to images.
            plugin._MEDIA_STASH[("7", "8")]["stored_at"] = 0.0
            plugin._stash_sweep()
            assert plugin._MEDIA_STASH == {}
        finally:
            runtime.close()


# ---------------------------------------------------------------------------
# strict mode + text flow: no regression (S-2.4.x, S-2.1.3, S-2.2.3)
# ---------------------------------------------------------------------------


def test_strict_mode_media_auto_captured_unchanged(monkeypatch):
    """S-2.1.3 / S-2.2.3: strict mode auto-captures voice/image (pre-change)."""
    with tempfile.TemporaryDirectory() as directory:
        adapter = FakeAdapter()
        handler, runtime = _handler(
            Path(directory),
            media_reader=lambda p: _VOICE_BYTES if "audio" in str(p) else _IMAGE_BYTES,
        )
        plugin = _load_plugin()
        plugin._handler = handler
        plugin._CAPTURE_MODE = "strict"
        monkeypatch.setattr(hermes_handler, "_probe_voice_duration",
                            lambda path: 30.0)
        try:
            voice = _event(1, _source(),
                           media_urls=[".hermes/cache/audio/note.ogg"],
                           media_types=["audio/ogg"], message_type="voice")
            assert _run_hook(plugin, event=voice,
                             gateway=FakeGateway(adapter),
                             session_store=None) == {
                "action": "skip", "reason": "idea-capture"}
            photo = _event(2, _source(), text="caption",
                           media_urls=[".hermes/cache/images/img.png"],
                           media_types=["image/png"], message_type="photo")
            assert _run_hook(plugin, event=photo,
                             gateway=FakeGateway(adapter),
                             session_store=None) == {
                "action": "skip", "reason": "idea-capture"}
            assert runtime.store.count() == 2
            # strict mode never stashes for the save branch.
            assert plugin._MEDIA_STASH == {}
        finally:
            runtime.close()


def test_ai_text_turn_unchanged_no_stash(monkeypatch):
    """S-2.4.1: text-only in ai mode -> None fall-through, no stash entry."""
    with tempfile.TemporaryDirectory() as directory:
        adapter = FakeAdapter()
        handler, runtime = _handler(Path(directory))
        plugin = _load_plugin()
        plugin._handler = handler
        plugin._CAPTURE_MODE = "ai"
        try:
            text = _event(1, _source(), text="I have an idea for a feature")
            assert _run_hook(plugin, event=text,
                             gateway=FakeGateway(adapter),
                             session_store=None) is None
            assert plugin._MEDIA_STASH == {}
            assert runtime.store.count() == 0
        finally:
            runtime.close()


# ---------------------------------------------------------------------------
# stash lifecycle: bytes preserved, popped on capture, TTL sweep (T-2.3)
# ---------------------------------------------------------------------------


def test_stash_preserves_real_bytes_and_pops_on_capture(monkeypatch):
    """S-2.3.1: the stash keeps the real bytes (read via media_reader at save).

    A later unrelated text capture in the same session sees NO stash (popped
    on first capture) and stays text-only — the media attaches exactly once.
    """
    with tempfile.TemporaryDirectory() as directory:
        adapter = FakeAdapter()
        handler, runtime = _handler(
            Path(directory),
            media_reader=lambda p: _VOICE_BYTES if "audio" in str(p) else _IMAGE_BYTES,
        )
        plugin = _load_plugin()
        plugin._handler = handler
        plugin._CAPTURE_MODE = "ai"
        monkeypatch.setattr(hermes_handler, "_probe_voice_duration",
                            lambda path: 20.0)
        _install_park_gateway(plugin, monkeypatch, adapter)
        try:
            voice = _event(1, _source(),
                           media_urls=[".hermes/cache/audio/note.ogg"],
                           media_types=["audio/ogg"], message_type="voice")
            assert _run_hook(plugin, event=voice,
                             gateway=FakeGateway(adapter),
                             session_store=None) is None
            stashed = plugin._MEDIA_STASH[("7", "8")]
            assert stashed["path"] == ".hermes/cache/audio/note.ogg"
            assert stashed["mime"] == "audio/ogg"
            # The real bytes are preserved and reach the parked capture.
            _session(monkeypatch)
            receipt = _capture(plugin, {"text": "transcript"})
            record = runtime.store.get(receipt["capture_id"])
            assert record.raw_bytes == _VOICE_BYTES
            assert plugin._MEDIA_STASH == {}  # popped exactly once
            # A second capture in the same session attaches nothing.
            second = _capture(plugin, {"text": "another text idea"})
            second_record = runtime.store.get(second["capture_id"])
            assert second_record.media_kind is MediaKind.TEXT
        finally:
            runtime.close()


def test_stash_attach_degrades_to_text_when_media_missing(monkeypatch):
    """S-2.3.1 degrade: unreadable stash bytes -> text-only capture, never breaks."""
    with tempfile.TemporaryDirectory() as directory:
        adapter = FakeAdapter()
        handler, runtime = _handler(
            Path(directory),
            media_reader=lambda p: (_ for _ in ()).throw(OSError("cache evicted")),
        )
        plugin = _load_plugin()
        plugin._handler = handler
        plugin._CAPTURE_MODE = "ai"
        _install_park_gateway(plugin, monkeypatch, adapter)
        try:
            photo = _event(2, _source(), text="caption",
                           media_urls=[".hermes/cache/images/gone.png"],
                           media_types=["image/png"], message_type="photo")
            assert _run_hook(plugin, event=photo,
                             gateway=FakeGateway(adapter),
                             session_store=None) is None
            _session(monkeypatch)
            receipt = _capture(plugin, {"text": "caption"})
            assert receipt["status"] == "RAW_PERSISTED"
            record = runtime.store.get(receipt["capture_id"])
            assert record.media_kind is MediaKind.TEXT  # degraded, not broken
            assert record.raw_text == "caption"
        finally:
            runtime.close()


def test_stash_ttl_sweep_drops_expired_entries():
    """T-2.3: entries older than the TTL are dropped by the lazy sweep."""
    plugin = _load_plugin()
    plugin._MEDIA_STASH.clear()
    plugin._MEDIA_STASH_TTL = 300.0
    plugin._MEDIA_STASH[("1", "2")] = {
        "path": "p", "type": "voice", "mime": "audio/ogg",
        "description": "", "stored_at": 0.0,  # ancient
    }
    plugin._MEDIA_STASH[("3", "4")] = {
        "path": "p", "type": "image", "mime": "image/png",
        "description": "", "stored_at": plugin._MEDIA_STASH_TTL + 1.0,
    }
    plugin._stash_sweep()
    assert plugin._MEDIA_STASH == {}


# ---------------------------------------------------------------------------
# description seam (T-2.2): build_media_enrich_provider.describe()
# ---------------------------------------------------------------------------


def test_describe_voice_returns_raw_transcript():
    """T-2.2: VOICE describe -> the raw Whisper transcript, unclassified."""
    provider = MediaEnrichProvider(
        transcribe_fn=lambda path, lang: "Remember to buy milk",
        language_resolver=lambda: "es",
    )
    description = provider.describe(b"", media_kind="voice",
                                    media_path="/tmp/note.ogg", mime="audio/ogg")
    assert description == "Remember to buy milk"


def test_describe_image_returns_vision_descripcion():
    """T-2.2: IMAGE describe -> the vision payload's descripcion, unstructured."""
    provider = MediaEnrichProvider(
        vision_fn=lambda raw, ctx: {
            "descripcion": "A sketch of a castle tower",
            "tags": ["arquitectura"],
        },
        vision_enabled=True,
    )
    description = provider.describe(_IMAGE_BYTES, media_kind="image")
    assert description == "A sketch of a castle tower"


def test_describe_fails_open_to_empty():
    """T-2.2 degrade: vision off / missing transcriber / failures -> ''."""
    provider = MediaEnrichProvider(vision_enabled=False)
    assert provider.describe(_IMAGE_BYTES, media_kind="image") == ""
    assert provider.describe(b"", media_kind="voice", media_path="/nope.ogg") == ""
    failing = MediaEnrichProvider(
        vision_fn=lambda raw, ctx: (_ for _ in ()).throw(RuntimeError("boom")),
        vision_enabled=True,
    )
    assert failing.describe(_IMAGE_BYTES, media_kind="image") == ""
    broken_audio = MediaEnrichProvider(
        transcribe_fn=lambda path, lang: (_ for _ in ()).throw(RuntimeError("boom")),
        language_resolver=lambda: "es",
    )
    assert broken_audio.describe(b"", media_kind="voice",
                                 media_path="/tmp/x.ogg") == ""


# ---------------------------------------------------------------------------
# hook contract: media in ai mode NEVER rewrites (documented finding)
# ---------------------------------------------------------------------------


def test_media_hook_never_rewrites(monkeypatch):
    """Contract lock: ai-mode media returns None, not a rewrite dict.

    The ``pre_gateway_dispatch`` contract supports ``{"action": "rewrite",
    "text": ...}`` (verified: gateway/run.py:14756-14761), but the gateway's
    own media pipeline prepends its transcript/description for media events,
    so a rewrite would duplicate the turn text and the STT/vision work. The
    hook therefore falls through and lets the gateway produce the description
    exactly once — the design's rewrite mechanism was confirmed and rejected
    on evidence (documented in the module docstring and apply-progress).
    """
    with tempfile.TemporaryDirectory() as directory:
        adapter = FakeAdapter()
        handler, runtime = _handler(Path(directory))
        plugin = _load_plugin()
        plugin._handler = handler
        plugin._CAPTURE_MODE = "ai"
        try:
            voice = _event(1, _source(),
                           media_urls=[".hermes/cache/audio/note.ogg"],
                           media_types=["audio/ogg"], message_type="voice")
            result = _run_hook(plugin, event=voice,
                               gateway=FakeGateway(adapter), session_store=None)
            assert result is None  # fall-through: the assistant sees the turn
            assert not (isinstance(result, dict)
                        and result.get("action") == "rewrite")
        finally:
            runtime.close()