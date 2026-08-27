"""Project plugin registration for native Demiurgos idea capture.

PR 1 (foundation): replaces the fictional ``register_gateway_handler`` /
``register_gateway_interaction_handler`` calls with a real Hermes v0.20
integration — a synchronous ``pre_gateway_dispatch`` intake hook that
intercepts the designated capture chat so messages never reach the assistant.

PR 2 adds the ``CaptureTelegramAdapter`` subclass registered via
``ctx.register_platform("telegram", ...)`` for the inline Guardar/Descartar
keyboard and callback routing; ``_schedule_capture_prompt`` now calls
``adapter.send_capture_prompt`` (falling back to plain ``send`` when the
platform override is not in effect).

PR 3 adds the voice-duration probe: the intake hook routes events through
``IdeaCaptureHandler._update_from_event_with_voice_probe`` so voice notes
(no ``media_durations`` field on the v0.20 ``MessageEvent``) get their
duration from the bundled adapter's ``_probe_voice_duration_seconds`` and
pass ``validate_media`` (<=300s); over-limit or unprobeable voice fails
closed with ``skip-rejected``.

PR idea-capture-ai-gate (Phase 1 + 2) adds the AI-gated mode flag
(``_CAPTURE_MODE`` from ``DEMIURGOS_IDEA_CAPTURE_MODE``, ``ai`` default,
``strict`` escape hatch) and, in ``ai`` mode:

- the intake hook returns ``None`` (fall-through) for the authorized binding
  so the assistant sees the turn (R-2 / R-6), and
- the ``capture_idea`` tool (R-3) plus a ``pre_llm_call`` guidance hook
  (R-4) are registered so the assistant decides per turn whether to capture
  or converse.

PR idea-capture-ai-gate (Phase 3) wires the media-aware enrich provider
(R-5): in ``ai`` mode ``register()`` builds ``build_media_enrich_provider()``
(``src/tools/idea_capture/hermes_handler.py``) and injects it as the runtime
``enrich`` callable, so TEXT classifies via the Hermes gateway, IMAGE enriches
with vision (flag-gated, default ON) and VOICE with Whisper transcription —
every branch fails open to ``sin_clasificar`` and capture is never blocked.

``strict`` mode preserves the pre-change unconditional ``skip`` behavior and
keeps the runtime's text-only ``_default_enrich`` fallback.

PR idea-capture-ai-gate (Phase 4) adds the optional ``capture_mode`` field to
``config/idea-capture.yaml``: mode now resolves with env > yaml > default
``ai`` precedence, delegated to ``idea_capture.config.resolve_capture_mode`` so
the plugin and the config layer share one validation.

PR idea-capture-confirm-queue (WU2) adds the park path: ``capture_idea`` gains a
``confirm`` parameter (default ``true``); ``confirm=false`` parks the capture in
``AWAITING_CONFIRM`` (via ``CaptureStore.set_awaiting_confirm``) and schedules
the Guardar/Descartar keyboard through ``_active_gateway`` — a module-level
reference stashed by ``capture_intake_hook`` on its first invocation, since the
tool handler itself never receives the gateway — instead of auto-SAVE_GLOBAL.
``confirm`` is excluded from the ``_synthetic_update_id`` dedup hash so the same
material never persists twice across the save/park paths (S-4.3).
``_CAPTURE_GUIDANCE`` becomes a 3-way rule: clear idea -> save (confirm=true),
uncertain -> park (confirm=false), ordinary conversation -> no tool (S-5.1).

PR idea-capture-confirm-queue (WU3) adds the one-shot wake-up notice (R-6):
``_boot_ts`` (boot timestamp captured at module load), the ``_wake_notice_sent``
flag, and a delayed ``_wake_notice`` task armed by the FIRST authorized
capture-chat hook invocation. After ~5s it counts N = offline-drained captures
ingested this boot (``event_ts < boot_ts AND created_at >= boot_ts`` via
``CaptureStore.boot_captures``) and M = subset parked in ``AWAITING_CONFIRM``;
when M > 0 it sends one summary message plus one Guardar/Descartar keyboard per
parked capture through the stashed gateway's adapter, and never re-fires within
the same boot (S-6.1 / S-6.2 / S-6.3).
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import os
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

log = logging.getLogger(__name__)

_handler = None

# PR idea-capture-confirm-queue (WU2, R-4): the tool handler never receives the
# gateway, so ``capture_intake_hook`` stashes it here on its FIRST invocation
# (the hook fires on every inbound message; first wins, stable for the process
# lifetime). The park branch resolves the live adapter through it to schedule
# the Guardar/Descartar keyboard.
_active_gateway = None

# PR idea-capture-confirm-queue (WU3, R-6): the wake-up notice targets the
# capture chat whose hook invocation armed it, so the binding-allowed source is
# stashed alongside the gateway. None until the notice is armed.
_active_source = None

# PR idea-capture-confirm-queue (WU3, R-6): boot timestamp for the one-shot
# wake notice. Captured at module load — the plugin module is imported by the
# Hermes plugin loader at gateway boot, so this is the gateway's boot instant.
# N counts captures whose ``event_ts`` (Telegram message.date) predates this
# instant but whose ``created_at`` (ingestion) does not.
_boot_ts = time.time()

# PR idea-capture-confirm-queue (WU3, R-6): one-shot per boot. Set BEFORE the
# notice task is scheduled so a concurrent hook invocation cannot re-arm the
# notice within the same boot (S-6.2).
_wake_notice_sent = False

# Delay before the wake notice fires, letting the Telegram drain settle (R-6).
# Kept on the module so tests can collapse it to ~0.
_WAKE_NOTICE_DELAY = 5.0

# PR idea-capture-ai-gate (R-1): capture mode resolved once at registration and
# cached for the process lifetime. ``None`` until ``register()`` runs; the
# intake hook treats an unresolved mode as the legacy ``strict`` path so
# pre-registration behavior is unchanged.
_CAPTURE_MODE: str | None = None

# One-shot guidance rule injected via pre_llm_call for the authorized binding
# (R-4). Kept on the module so tests can assert on the exact text. Three-way
# decision (S-5.1): clear idea -> save directly; uncertain -> park for later
# review; ordinary conversation -> respond normally without the tool.
_CAPTURE_GUIDANCE = (
    "If the user's turn contains a clear idea, world, lore, or character "
    "seed → call `capture_idea` with confirm=true to save it directly. If "
    "the material might be an idea but you are not sure, call `capture_idea` "
    "with confirm=false to park it for later review. If it is ordinary "
    "conversation → respond normally without calling the tool."
)

# Update-idea guidance appended to the same pre_llm_call context (R-7). The
# tool must ONLY be invoked after the user explicitly approves the final
# version of the idea (e.g. "listo, actualizá"), never speculatively.
_UPDATE_IDEA_GUIDANCE = (
    "When the user wants to improve or edit an existing idea: "
    "1) Use `ideas_read(slug)` to read the current version. "
    "2) Collaborate in conversation — propose improvements, discuss changes. "
    "3) ONLY call `update_idea` after the user explicitly approves the final "
    "version (e.g. 'listo, actualizá', 'go ahead', 'save it'). "
    "Never call `update_idea` without explicit user approval."
)


def _demiurgos_language() -> str:
    """Resolve Demiurgos' configured UI language (``DEMIURGOS_LANGUAGE``).

    Reads the project ``.env`` (or env) via ``demiurgos_language.resolve_ui_language``
    so the bot responds in whatever language Demiurgos is set to, never a
    hardcoded one. Falls back to ``es`` on error or when unavailable.
    """
    repo_root = os.environ.get("DEMIURGOS_ROOT") or str(Path.cwd())
    try:
        sys.path.insert(0, str(Path(repo_root) / "src" / "tools" / "demiurgos-suite" / "wiki"))
        from demiurgos_language import resolve_ui_language  # noqa: PLC0415

        return resolve_ui_language()
    except Exception:  # noqa: BLE001 — fail safe to Spanish (Demiurgos' default)
        return "es"


def _build_guidance_context() -> str:
    """Compose the capture guidance + Demiurgos language instruction."""
    lang = _demiurgos_language()
    lang_instr = (
        f"Always respond in Demiurgos' configured language ({lang})."
        if lang
        else "Always respond in Demiurgos' configured language."
    )
    return f"{_CAPTURE_GUIDANCE} {_UPDATE_IDEA_GUIDANCE} {lang_instr}"

_CAPTURE_IDEA_SCHEMA = {
    "name": "capture_idea",
    "description": (
        "Capture an idea, worldbuilding seed, lore fragment, or character "
        "concept into the Demiurgos Taller de Ideas. Call this when the user "
        "shares creative material worth persisting; provide it as text, "
        "image_bytes, or audio_bytes. Returns a capture receipt "
        "(capture_id, status)."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "text": {
                "type": "string",
                "description": "The idea/seed text to capture.",
            },
            "image_bytes": {
                "type": "string",
                "description": "Base64-encoded image payload (with mime).",
            },
            "audio_bytes": {
                "type": "string",
                "description": "Base64-encoded audio payload (with mime).",
            },
            "mime": {
                "type": "string",
                "description": (
                    "Payload MIME type, e.g. image/png, image/jpeg, audio/ogg."
                ),
            },
            "confirm": {
                "type": "boolean",
                "description": (
                    "true guarda directo; false lo deja en Ideas por confirmar"
                ),
                "default": True,
            },
        },
        "required": [],
    },
}


_UPDATE_IDEA_SCHEMA = {
    "name": "update_idea",
    "description": (
        "Update an existing idea, creating a new version. ONLY call after "
        "explicit user approval of the final version (e.g. 'listo, "
        "actualizá'). Returns {slug, version, previous_version, archived_at}."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "slug": {
                "type": "string",
                "description": "The idea slug to update.",
            },
            "body": {
                "type": "string",
                "description": "New markdown body (optional partial).",
            },
            "title": {
                "type": "string",
                "description": "New title (optional partial).",
            },
            "tags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "New tags (optional partial).",
            },
            "type": {
                "type": "string",
                "description": "New idea type (optional partial).",
            },
        },
        "required": ["slug"],
    },
}


def register(ctx) -> None:
    global _handler
    root = Path(os.environ.get("DEMIURGOS_ROOT", Path.cwd())).resolve()
    tools = root / "src" / "tools"
    if str(tools) not in sys.path:
        sys.path.insert(0, str(tools))
    # The wiki package (IdeasBank for update_idea) lives under
    # src/tools/demiurgos-suite/wiki — put the suite dir on the path so the
    # lazy ``from wiki.ideas_bank import ...`` in the tool handler resolves.
    suite = tools / "demiurgos-suite"
    if str(suite) not in sys.path:
        sys.path.insert(0, str(suite))
    # PR idea-capture-ai-gate Phase 4: mode resolution delegates to the config
    # module (env > yaml > ai), so ``src/tools`` must be on the path first.
    _resolve_capture_mode()

    from idea_capture.hermes_handler import IdeaCaptureHandler
    from .capture_adapter import (
        CaptureTelegramAdapter,
        capture_platform_deps_ready,
        verify_bundled_adapter_surface,
    )

    enrich = None
    if _CAPTURE_MODE == "ai":
        # PR idea-capture-ai-gate Phase 3 (R-5): the media-aware enrich
        # provider labels TEXT via the Hermes gateway classifier, enriches
        # IMAGE with vision (flag-gated) and VOICE with Whisper transcription.
        # Every branch fails open to sin_clasificar; capture is never blocked.
        # In strict mode ``enrich=None`` keeps the runtime's ``_default_enrich``
        # text-only fallback (pre-change behavior).
        from idea_capture.hermes_handler import build_media_enrich_provider
        enrich = build_media_enrich_provider()

    _handler = IdeaCaptureHandler(repo_root=root, enrich=enrich)

    # Native intake: intercept the designated capture chat before Hermes auth
    # or assistant dispatch. The hook is synchronous and returns a skip dict so
    # captured messages are consumed and never reach the assistant (strict
    # mode); in ai mode the authorized binding falls through (R-2).
    ctx.register_hook("pre_gateway_dispatch", capture_intake_hook)

    if _CAPTURE_MODE == "ai":
        # PR idea-capture-ai-gate Phase 2 (R-3/R-4): the assistant decides per
        # turn. The guidance hook runs after the gateway media pipeline so
        # transcripts/descriptions are already in the turn text; the tool
        # exposes capture to the model for the authorized session only.
        ctx.register_hook("pre_llm_call", capture_guidance_hook)
        ctx.register_tool(
            name="capture_idea",
            toolset="demiurgos",
            schema=_CAPTURE_IDEA_SCHEMA,
            handler=_capture_idea_tool,
            description=_CAPTURE_IDEA_SCHEMA["description"],
            emoji="💡",
            is_async=False,
        )
        # R-7: expose the versioned edit tool. Same auth gate as capture_idea;
        # the guidance hook tells the model to only call it after explicit
        # user approval.
        ctx.register_tool(
            name="update_idea",
            toolset="demiurgos",
            schema=_UPDATE_IDEA_SCHEMA,
            handler=_update_idea_tool,
            description=_UPDATE_IDEA_SCHEMA["description"],
            emoji="✏️",
            is_async=False,
        )

    # PR 2: override the bundled telegram adapter with the capture subclass so
    # Guardar/Descartar callbacks route and the prompt carries a real keyboard.
    # Fail loud if the bundled adapter's private helpers drifted (Hermes
    # upgrade), then register last-writer-wins (platform_registry replaces
    # same-name entries).
    verify_bundled_adapter_surface()

    def _adapter_factory(cfg):
        return CaptureTelegramAdapter(cfg, capture_handler=_handler)

    ctx.register_platform(
        name="telegram",
        label="Telegram (Demiurgos capture)",
        adapter_factory=_adapter_factory,
        check_fn=capture_platform_deps_ready,
        required_env=["TELEGRAM_BOT_TOKEN"],
    )


def _event_has_media(event) -> bool:
    """True when the inbound event carries media (photo/voice), not pure text.

    Mirrors the ``media_urls`` check in ``IdeaCaptureHandler._update_from_event``:
    an event with ``media_urls`` is a photo/voice turn whose bytes we must
    preserve by capturing directly (ai mode), rather than letting the assistant
    see only its injected description.
    """
    if event is None:
        return False
    paths = getattr(event, "media_urls", None)
    if paths:
        return True
    # Voice notes may expose media via the cache path even when media_urls is
    # empty; treat an explicit media type/kind as media too.
    mtype = getattr(getattr(event, "message_type", None), "value", "") or ""
    if mtype in {"photo", "image", "voice", "audio", "video", "document"}:
        return True
    kinds = getattr(event, "media_types", None)
    if kinds:
        return True
    return False


def capture_intake_hook(*, event, gateway, session_store, **kwargs) -> dict | None:
    """Synchronous intake for the designated capture chat.

    Hermes' ``invoke_hook`` calls this callback synchronously (``cb(**kwargs)``);
    it MUST return a dict, never a coroutine — an un-awaited coroutine here
    would silently disable the skip contract. ``**kwargs`` absorbs the
    ``telemetry_schema_version="hermes.observer.v1"`` marker that
    ``PluginManager`` appends to every plugin-hook callback (Hermes docs);
    without it the extra keyword raises a TypeError and the hook never returns
    ``skip``, leaking the message to the normal assistant flow. Returns:

    - ``{"action": "skip", "reason": "idea-capture"}`` for a captured message,
    - ``{"action": "skip", "reason": "idea-capture-duplicate"}`` for a replay,
    - ``{"action": "skip", "reason": "idea-capture-rejected"}`` when a capture
      attempt fails (fail closed: never leak the message to the assistant,
      never crash dispatch),
    - ``None`` for fall-through to the normal assistant flow (non-capture
      chat, unauthorized sender, non-telegram platform, non-capturable
      media, or — in ``ai`` mode — the authorized binding itself).
    """
    global _active_gateway, _wake_notice_sent, _active_source
    # R-4 / S-4.2: the capture_idea tool handler never receives the gateway, so
    # stash it on the FIRST hook invocation — the hook fires on every inbound
    # message and the first one wins (stable reference for the process).
    if _active_gateway is None and gateway is not None:
        _active_gateway = gateway
    handler = _handler
    source = getattr(event, "source", None)
    if handler is None or source is None:
        return None
    platform = str(getattr(getattr(source, "platform", None), "value", ""))
    if platform != "telegram":
        return None  # S-6.1: non-capture platform -> assistant handles
    if not handler._binding_allowed(source):
        return None  # S-6.2: unauthorized sender -> assistant handles

    # PR idea-capture-confirm-queue (WU3, R-6): arm the one-shot wake notice on
    # the FIRST authorized capture-chat invocation. The flag is set BEFORE the
    # task is scheduled so a concurrent hook invocation cannot re-arm it within
    # the same boot (S-6.2); the binding-allowed source is stashed so the notice
    # targets the capture chat (its adapter carries the Guardar/Descartar
    # keyboards). The ~5s delay lets the Telegram drain settle before counting.
    if not _wake_notice_sent:
        _wake_notice_sent = True
        _active_source = source
        _schedule_wake_notice(_active_gateway or gateway, handler)

    if _CAPTURE_MODE == "ai":
        # R-2 / S-2.1 / S-2.3 (adjusted): in ai mode, TEXT-only turns fall
        # through so the assistant decides (capture via capture_idea vs.
        # converse) — its injection and the tool are fully text-driven. But
        # media turns (photo/voice) are captured directly here, with their
        # real bytes: the assistant only ever sees the media as an injected
        # description, so routing those through the tool would drop the image/
        # audio payload and leave the idea text-only (no media_path, no
        # visible image). Capturing media directly preserves the bytes so the
        # image lands in ideas/media/ and renders.
        if not _event_has_media(event):
            return None

    try:
        update = handler._update_from_event_with_voice_probe(event, gateway)
    except ValueError:
        # S-6.3 / S-10.3 / S-10.4: unsupported media type, no capturable
        # text/media, or missing Telegram identity -> normal assistant flow,
        # never capture.
        return None
    except Exception as exc:  # noqa: BLE001 — fail closed, never crash dispatch
        log.exception("idea-capture event conversion failed: %s", exc)
        return {"action": "skip", "reason": "idea-capture-rejected"}
    try:
        receipt = handler.runtime.service.accept(update)
    except Exception as exc:  # noqa: BLE001 — fail closed, never leak
        log.warning("idea-capture intake rejected update: %s", exc)
        return {"action": "skip", "reason": "idea-capture-rejected"}
    if receipt.status == "DUPLICATE":
        return {"action": "skip", "reason": "idea-capture-duplicate"}  # R-4 / S-4.1

    adapter = gateway._adapter_for_source(event.source)
    if adapter is not None:
        _schedule_capture_prompt(adapter, source, receipt.capture_id)
    return {"action": "skip", "reason": "idea-capture"}


def _schedule_capture_prompt(adapter, source, capture_id: str) -> None:
    """Schedule the outbound capture prompt without blocking dispatch.

    PR 2: the prompt rides ``CaptureTelegramAdapter.send_capture_prompt`` so
    the Guardar/Descartar keyboard is attached. Falls back to the PR 1
    plain-text ``send`` when the active adapter predates the subclass (e.g.
    the platform override is not yet in effect).
    """
    kwargs = {"chat_id": str(source.chat_id), "capture_id": capture_id}
    if getattr(source, "thread_id", None):
        kwargs["thread_id"] = source.thread_id
    send_prompt = getattr(adapter, "send_capture_prompt", None)
    try:
        if callable(send_prompt):
            asyncio.create_task(send_prompt(**kwargs))
        else:
            text = f"Idea capturada (id=`{capture_id}`). Elegí una acción:"
            metadata = {"thread_id": kwargs["thread_id"]} if "thread_id" in kwargs else None
            asyncio.create_task(adapter.send(str(source.chat_id), text, metadata=metadata))
    except RuntimeError as exc:  # no running loop: prompt cannot be scheduled
        log.warning("idea-capture prompt scheduling failed for %s: %s", capture_id, exc)


# -- PR idea-capture-ai-gate: mode flag (R-1) -------------------------------


def _resolve_capture_mode() -> str:
    """Resolve the capture mode once; cache immutably (R-1, task 4.1).

    Precedence: ``DEMIURGOS_IDEA_CAPTURE_MODE`` env var > ``capture_mode`` in
    ``config/idea-capture.yaml`` > default ``ai``. Validation (``ai``/``strict``,
    invalid -> warn + ``ai``) lives in
    ``idea_capture.config.resolve_capture_mode`` and is reused here so the
    plugin and the config layer agree on precedence. If that module is
    unavailable (e.g. standalone load with ``src/tools`` off the path), it
    falls back to the PR 1 env-only resolution so the escape hatch never
    silently flips. The first resolution wins for the process lifetime; later
    ``register()`` calls reuse the cached mode.
    """
    global _CAPTURE_MODE
    if _CAPTURE_MODE is not None:
        return _CAPTURE_MODE
    try:
        from idea_capture.config import resolve_capture_mode as _resolve_mode
        root = Path(os.environ.get("DEMIURGOS_ROOT", Path.cwd())).resolve()
        _CAPTURE_MODE = _resolve_mode(root / "config" / "idea-capture.yaml")
    except Exception as exc:  # noqa: BLE001 — fail closed to env-only, then ai
        log.warning("idea-capture config mode resolution failed; "
                    "falling back to env: %s", exc)
        raw = os.environ.get("DEMIURGOS_IDEA_CAPTURE_MODE", "").strip().lower()
        if raw == "strict":
            _CAPTURE_MODE = "strict"
        elif raw in {"", "ai"}:
            _CAPTURE_MODE = "ai"
        else:
            log.warning(
                "unknown DEMIURGOS_IDEA_CAPTURE_MODE=%r; treating as 'ai'", raw,
            )
            _CAPTURE_MODE = "ai"
    log.info("idea-capture mode: %s", _CAPTURE_MODE)
    return _CAPTURE_MODE


# -- PR idea-capture-ai-gate: session identity for tool + guidance ----------


def _session_env(name: str) -> str:
    """Read a ``HERMES_SESSION_*`` variable from the gateway session context.

    Prefers the gateway's task-local ContextVar (set per inbound message) and
    falls back to ``os.environ`` for CLI/test processes where the gateway
    module is unavailable or the variable was never bound.
    """
    try:
        from gateway.session_context import get_session_env
        return get_session_env(name, "")
    except Exception:
        return os.environ.get(name, "")


def _platform_member(name: str):
    """Resolve a platform name to the gateway ``Platform`` enum when available.

    Inside the gateway process the real enum is importable and the park path's
    ``gateway._adapter_for_source`` lookup keys ``gateway.adapters`` by
    ``Platform`` members, so the synthetic session source must carry the real
    member to resolve the live adapter (R-4 / S-4.2 keyboard). Outside the
    gateway (CLI, tests) the plain ``SimpleNamespace(value=...)`` shape keeps
    ``_binding_key`` / ``_build_tool_update`` working unchanged.
    """
    try:
        from gateway.config import Platform  # noqa: PLC0415
        return Platform(name)
    except Exception:  # noqa: BLE001 — gateway unavailable (CLI/tests)
        return SimpleNamespace(value=name)


def _session_source() -> SimpleNamespace | None:
    """Rebuild a source-like identity from the gateway session context.

    Mirrors the ``MessageEvent.source`` shape the intake hook authorizes
    against, so the tool and guidance hook can reuse
    ``IdeaCaptureHandler._binding_allowed`` unchanged. Returns ``None`` when
    the current session has no messaging identity (CLI, cron, tests without
    session vars) — callers treat that as unauthorized (fail closed).
    """
    platform = _session_env("HERMES_SESSION_PLATFORM")
    chat_id = _session_env("HERMES_SESSION_CHAT_ID")
    user_id = _session_env("HERMES_SESSION_USER_ID")
    profile = _session_env("HERMES_SESSION_PROFILE") or "default"
    if not (platform and chat_id and user_id):
        return None
    return SimpleNamespace(
        platform=_platform_member(platform),
        chat_id=chat_id,
        user_id=user_id,
        profile=profile,
    )


def _session_binding_allowed(handler) -> bool:
    source = _session_source()
    return source is not None and handler._binding_allowed(source)


# -- PR idea-capture-ai-gate: capture_idea tool (R-3) ------------------------


def _coerce_payload(value) -> bytes:
    """Accept bytes directly or base64 text (the JSON tool contract)."""
    if isinstance(value, bytes):
        return value
    if isinstance(value, bytearray):
        return bytes(value)
    if isinstance(value, str):
        try:
            return base64.b64decode(value, validate=True)
        except Exception:
            return value.encode("utf-8")
    raise TypeError(f"unsupported payload type: {type(value).__name__}")


def _synthetic_update_id(args: dict) -> int:
    """Deterministic platform update id derived from the tool payload.

    Identical payloads map to the same update id, so a repeated
    ``capture_idea`` call for the same material is deduplicated by the
    existing ingress/store machinery (S-3.2) instead of persisting twice.
    """
    normalized: dict[str, str] = {}
    for key, value in sorted(args.items()):
        if key == "confirm":
            # S-4.3: dedup keys on capture CONTENT, never on the confirm intent.
            # The guidance picks one path per turn (save or park), so the same
            # material with confirm=true vs confirm=false must map to the same
            # update id — otherwise the same text could persist twice.
            continue
        if value in (None, ""):
            continue
        if isinstance(value, (bytes, bytearray)):
            normalized[key] = base64.b64encode(bytes(value)).decode("ascii")
        else:
            normalized[key] = str(value)
    digest = hashlib.sha256(json.dumps(normalized, sort_keys=True).encode("utf-8")).hexdigest()
    # Mask to 63 bits: SQLite INTEGER is signed 64-bit (2^63-1 max).
    return int(digest[:16], 16) & 0x7FFFFFFFFFFFFFFF


def _probe_voice_duration_from_bytes(data: bytes, mime: str) -> float | None:
    """Best-effort voice duration for a raw audio payload (S-3.5).

    The bundled probe reads from a file path, so the payload is staged in a
    temp file with a MIME-derived extension and ``_probe_voice_duration`` is
    reused unchanged. Never raises; ``None`` leaves the update without a
    duration, which ``validate_media`` rejects (fail closed).
    """
    try:
        from idea_capture.hermes_handler import _probe_voice_duration
    except Exception:
        return None
    ext = ".ogg"
    if mime in {"audio/mpeg", "audio/mp3"}:
        ext = ".mp3"
    elif mime == "audio/mp4":
        ext = ".m4a"
    elif mime == "audio/wav":
        ext = ".wav"
    try:
        with tempfile.NamedTemporaryFile(suffix=ext) as probe_file:
            probe_file.write(data)
            probe_file.flush()
            duration = _probe_voice_duration(probe_file.name)
    except Exception:  # noqa: BLE001 — fail closed, never crash the tool
        return None
    return None if duration is None else float(duration)


def _build_tool_update(args: dict) -> "TelegramUpdate":
    """Build a synthetic ``TelegramUpdate`` from ``capture_idea`` args.

    The chat/user identity comes from the gateway session context so the
    update's binding key matches the authorized binding exactly.
    """
    source = _session_source()
    if source is None:
        raise ValueError("capture_idea requires an authorized Telegram session")
    from idea_capture.models import MediaInput, MediaKind, TelegramUpdate, WorldAction

    text = str(args.get("text") or "").strip()
    image_bytes = args.get("image_bytes")
    audio_bytes = args.get("audio_bytes")
    mime = str(args.get("mime") or "").strip()

    media: MediaInput
    if image_bytes is not None:
        data = _coerce_payload(image_bytes)
        media = MediaInput(MediaKind.IMAGE, data=data, mime=mime or "image/jpeg", text=text)
    elif audio_bytes is not None:
        data = _coerce_payload(audio_bytes)
        mime = mime or "audio/ogg"
        duration = _probe_voice_duration_from_bytes(data, mime)
        media = MediaInput(MediaKind.VOICE, data=data, mime=mime,
                           duration_seconds=duration, text=text)
    else:
        media = MediaInput(MediaKind.TEXT, text=text)

    return TelegramUpdate(
        update_id=_synthetic_update_id(args),
        chat_id=int(source.chat_id),
        sender_id=int(source.user_id),
        is_group=False,
        media=media,
        platform=source.platform.value,
        profile=source.profile,
    )


def _capture_idea_tool(args: dict, **kwargs) -> str:
    """Tool handler for ``capture_idea`` (R-3, ai mode only).

    Returns a JSON string per the Hermes tool contract: the capture receipt
    (``capture_id``, ``status``) on success, or an ``error`` payload. Calls
    from sessions that are not the authorized capture binding are rejected
    before ``service.accept`` (S-3.3).

    PR idea-capture-confirm-queue (WU2, R-4): ``confirm`` defaults to ``true``
    (auto-SAVE_GLOBAL, pre-change behavior). ``confirm=false`` parks the
    capture in ``AWAITING_CONFIRM`` and schedules the Guardar/Descartar
    keyboard via the stashed gateway instead of auto-saving (S-4.2).
    """
    handler = _handler
    if handler is None:
        return json.dumps({"error": "idea-capture handler is not initialized"})
    if _CAPTURE_MODE != "ai":
        return json.dumps({"error": "capture_idea is only available in ai mode"})
    from idea_capture.models import WorldAction  # local: confirm decision below
    if not _session_binding_allowed(handler):
        return json.dumps({"error": "unauthorized session"})  # S-3.3
    try:
        update = _build_tool_update(args)
        receipt = handler.runtime.service.accept(update)
    except Exception as exc:  # noqa: BLE001 — bounded error to the model
        log.warning("capture_idea tool rejected update: %s", exc)
        return json.dumps({"error": f"capture rejected: {exc}"})
    if receipt.status == "DUPLICATE":
        # Dedup fires on content (confirm excluded from the update hash), so a
        # save/park attempt for already-captured material never mutates the row.
        return json.dumps({"capture_id": receipt.capture_id, "status": receipt.status})
    if not bool(args.get("confirm", True)):
        # Park path (R-4 / S-4.2): keep the capture for later review instead of
        # auto-saving — transition to AWAITING_CONFIRM and schedule the
        # Guardar/Descartar keyboard via the gateway stashed by the intake hook
        # (the tool handler itself never receives the gateway).
        try:
            handler.runtime.store.set_awaiting_confirm(receipt.capture_id)
        except Exception as exc:  # noqa: BLE001 — park failure must not crash the turn
            log.warning("capture_idea park failed for %s: %s", receipt.capture_id, exc)
            return json.dumps({"error": f"capture parked failed: {exc}"})
        _schedule_park_prompt(receipt.capture_id)
        return json.dumps({"capture_id": receipt.capture_id, "status": receipt.status})
    # Confirmed path (S-4.1): the tool bypasses the inline Guardar/Descartar
    # keyboard, so the SAVE_GLOBAL decision (and the worker that writes the idea
    # file) must happen here; without it the capture stays RAW_PERSISTED forever
    # and never lands in the Taller de Ideas.
    try:
        handler.runtime.confirm(receipt.capture_id, WorldAction.SAVE_GLOBAL)
    except Exception as exc:  # noqa: BLE001 — confirm failure must not crash the turn
        log.warning("capture_idea confirm failed for %s: %s", receipt.capture_id, exc)
    return json.dumps({"capture_id": receipt.capture_id, "status": receipt.status})


def _schedule_park_prompt(capture_id: str) -> None:
    """Schedule the Guardar/Descartar keyboard for a parked capture (R-4).

    The tool handler never receives the gateway, so the park branch resolves
    the live adapter through ``_active_gateway`` (stashed by the intake hook on
    its first invocation). ``_schedule_capture_prompt`` falls back to plain-text
    ``send`` when the active adapter predates the keyboard subclass, and when no
    gateway/adapter is available the capture stays parked and surfaces via the
    web review panel / wake-up notice instead — never crashing the turn.
    """
    gateway = _active_gateway
    source = _session_source()
    if gateway is None or source is None:
        log.warning("idea-capture park: no active gateway/session for %s; "
                    "capture parked without keyboard", capture_id)
        return
    try:
        adapter = gateway._adapter_for_source(source)
    except Exception as exc:  # noqa: BLE001 — prompt failure never crashes the turn
        log.warning("idea-capture park: adapter resolution failed for %s: %s",
                    capture_id, exc)
        return
    if adapter is None:
        log.warning("idea-capture park: no live adapter for %s; "
                    "capture parked without keyboard", capture_id)
        return
    _schedule_capture_prompt(adapter, source, capture_id)


# -- PR idea-capture-confirm-queue WU3: one-shot wake-up notice (R-6) ---------


def _schedule_wake_notice(gateway, handler) -> None:
    """Arm the delayed one-shot boot notice on the running loop (R-6).

    The caller has already set ``_wake_notice_sent``, so this helper only
    schedules; without a running loop (CLI/tests invoking the hook outside the
    gateway) the notice is skipped without breaking the hook. The loop is
    resolved BEFORE the coroutine is created so no orphaned coroutine leaks.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError as exc:  # no running loop: notice cannot be scheduled
        log.warning("idea-capture wake notice: no running loop; skipping: %s", exc)
        return
    loop.create_task(_wake_notice(gateway, handler.runtime.store))


async def _wake_notice(gateway, store) -> None:
    """One-shot boot notice: report offline-drained captures needing review.

    Fires ~5s after the first authorized hook invocation so the Telegram drain
    has settled. N = captures with ``event_ts < boot_ts AND created_at >=
    boot_ts`` (sent while the bot was down, ingested this boot); M = subset
    parked in ``AWAITING_CONFIRM`` (S-6.3: media auto-captured as
    ``RAW_PERSISTED`` counts in N but not M). When M > 0, sends ONE summary
    message plus one Guardar/Descartar keyboard per parked capture; when M == 0
    it stays silent. Never raises: any failure (query, adapter resolution,
    send) logs and returns without breaking the boot.
    """
    try:
        await asyncio.sleep(_WAKE_NOTICE_DELAY)
    except asyncio.CancelledError:
        return
    if gateway is None or _boot_ts is None:
        return
    try:
        offline = store.boot_captures(_boot_ts)
    except Exception as exc:  # noqa: BLE001 — notice failure never breaks boot
        log.warning("idea-capture wake notice: boot query failed: %s", exc)
        return
    from idea_capture.models import CaptureState  # local: plugin import discipline
    parked = [record for record in offline
              if record.state is CaptureState.AWAITING_CONFIRM]
    if not parked:
        log.info("idea-capture wake notice: %d offline captures, 0 parked "
                 "this boot; staying silent", len(offline))
        return
    source = _active_source
    if source is None:
        log.warning("idea-capture wake notice: no stashed capture source; "
                    "skipping notice")
        return
    try:
        adapter = gateway._adapter_for_source(source)
    except Exception as exc:  # noqa: BLE001 — prompt failure never breaks boot
        log.warning("idea-capture wake notice: adapter resolution failed: %s", exc)
        return
    if adapter is None:
        log.warning("idea-capture wake notice: no live adapter; skipping notice")
        return
    summary = (f"Llegaron {len(offline)} mensajes; tengo {len(parked)} "
               f"por confirmar. ¿Las reviso?")
    metadata = {"thread_id": source.thread_id} if getattr(source, "thread_id", None) else None
    try:
        await adapter.send(str(source.chat_id), summary, metadata=metadata)
    except Exception as exc:  # noqa: BLE001 — summary failure never breaks boot
        log.warning("idea-capture wake notice: summary send failed: %s", exc)
        return
    for record in parked:
        _schedule_capture_prompt(adapter, source, record.capture_id)

def _update_idea_tool(args: dict, **kwargs) -> str:
    """Tool handler for ``update_idea`` (R-7, ai mode only).

    Returns a JSON string per the Hermes tool contract: the update result
    ``{slug, version, previous_version, archived_at}`` on success, or an
    ``error`` payload. Sessions that are not the authorized capture binding
    are rejected before any write (S-7.1). The tool delegates to
    ``IdeasBank.update_versioned()``; the ``version`` is derived from the
    core, never passed by the caller, and the tool neither moves media nor
    deletes.
    """
    handler = _handler
    if handler is None:
        return json.dumps({"error": "idea-capture handler is not initialized"})
    if _CAPTURE_MODE != "ai":
        return json.dumps({"error": "update_idea is only available in ai mode"})
    if not _session_binding_allowed(handler):
        return json.dumps({"error": "unauthorized session"})  # S-7.1
    slug = args.get("slug")
    if not slug:
        return json.dumps({"error": "slug is required"})
    from wiki.ideas_bank import IdeaNotFound, IdeasBank, InvalidIdea
    try:
        partial: dict = {}
        for key in ("body", "title", "tags", "type"):
            value = args.get(key)
            if value not in (None, "", [], ()):
                partial[key] = value
        bank = IdeasBank()
        updated = bank.update_versioned(slug, partial)
    except (IdeaNotFound, InvalidIdea) as exc:
        log.warning("update_idea tool rejected update: %s", exc)
        return json.dumps({"error": str(exc)})
    except Exception as exc:  # noqa: BLE001 — bounded error to the model
        log.warning("update_idea tool rejected update: %s", exc)
        return json.dumps({"error": f"update rejected: {exc}"})
    previous_version = updated.version - 1
    return json.dumps({
        "slug": slug,
        "version": updated.version,
        "previous_version": previous_version,
        "archived_at": str(bank._archive_path(slug, previous_version)),
    })


# -- PR idea-capture-ai-gate: pre_llm_call guidance (R-4) --------------------


def capture_guidance_hook(**kwargs) -> dict | None:
    """``pre_llm_call``: teach the assistant when to call ``capture_idea``.

    Registered only in ``ai`` mode (R-4). Runs after the gateway media
    pipeline, so voice transcripts / vision descriptions are already part of
    the turn text when the model reads the rule (S-4.4). Only sessions from
    the authorized capture binding receive the guidance (S-4.2); in ``strict``
    mode the model never decides, so nothing is injected (S-4.3). Returns the
    ``{"context": ...}`` dict the ``pre_llm_call`` contract injects into the
    user message.
    """
    handler = _handler
    if handler is None or _CAPTURE_MODE != "ai":
        return None
    if not _session_binding_allowed(handler):
        return None
    return {"context": _build_guidance_context()}
