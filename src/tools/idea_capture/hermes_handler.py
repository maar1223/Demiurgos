"""Hermes-native idea capture handler.

This module consumes Hermes' normalized ``MessageEvent`` and media-cache paths.
It deliberately has no Telegram SDK, Bot API, token, or polling dependency.

Intake happens through ``IdeaCaptureHandler._update_from_event_with_voice_probe``
called by the project plugin's ``pre_gateway_dispatch`` hook. The legacy
``handle_message`` / ``handle_interaction`` methods (which called the fictional
``send_interaction_message`` / ``interaction.answer|send|edit`` APIs that do not
exist in Hermes v0.20) were retired; callback confirm/deny now lives in the
``CaptureTelegramAdapter`` subclass.
"""

from __future__ import annotations

import os
import sys
from dataclasses import replace
from pathlib import Path
from typing import Callable

from .config import CaptureConfig, load_active_world, load_policy
from .models import MediaInput, MediaKind, TelegramUpdate
from .runtime import IdeaCaptureRuntime


def _within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def read_hermes_media_cache(path: str) -> bytes:
    """Read only files from Hermes-managed media cache roots."""
    candidate = Path(path).expanduser().resolve(strict=True)
    home = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes")).expanduser().resolve()
    roots = [
        home / "cache",
        home / "image_cache",
        home / "audio_cache",
        home / "video_cache",
        home / "document_cache",
    ]
    if not any(_within(candidate, root.resolve()) for root in roots):
        raise ValueError("media path is outside Hermes cache")
    if not candidate.is_file():
        raise ValueError("media path is not a regular file")
    return candidate.read_bytes()


def _hermes_agent_root() -> Path:
    """Resolve the Hermes agent source root (parent of the ``plugins`` package).

    Mirrors ``capture_adapter.hermes_agent_root()``: an explicit
    ``HERMES_AGENT_ROOT`` override wins, then ``HERMES_HOME`` (default
    ``~/.hermes``) + ``hermes-agent``. Inside a running gateway the agent root
    is already importable, so this is only a fallback for standalone/test
    processes.
    """
    override = os.environ.get("HERMES_AGENT_ROOT", "").strip()
    if override:
        return Path(override).resolve()
    home = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes")).expanduser()
    return (home / "hermes-agent").resolve()


def _probe_voice_duration(path: str) -> float | None:
    """Best-effort voice duration via the bundled Hermes probe (fail closed).

    Reuses the TelegramAdapter's module-level ``_probe_voice_duration_seconds``
    (mutagen -> ffprobe, adapter.py:335) instead of duplicating that logic.
    Capability-checked: a Hermes upgrade that renames or breaks the helper
    yields ``None`` here, so the voice note is rejected by ``validate_media``
    (S-10.5) instead of crashing dispatch. Never raises.
    """
    try:
        from plugins.platforms.telegram.adapter import _probe_voice_duration_seconds
    except ImportError:
        root = _hermes_agent_root()
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))
        try:
            from plugins.platforms.telegram.adapter import _probe_voice_duration_seconds
        except Exception:
            return None
    try:
        duration = _probe_voice_duration_seconds(path)
    except Exception:
        return None
    return None if duration is None else float(duration)


class IdeaCaptureHandler:
    """Authorized Hermes handler for one deterministic native capture owner."""

    def __init__(
        self,
        *,
        repo_root: str | Path,
        config_path: str | Path | None = None,
        state_path: str | Path | None = None,
        mundos_root: str | Path | None = None,
        active_world: str = "",
        media_reader: Callable[[str], bytes] = read_hermes_media_cache,
        runtime: IdeaCaptureRuntime | None = None,
    ) -> None:
        self.repo_root = Path(repo_root).resolve()
        self.config_path = Path(config_path or self.repo_root / "config" / "idea-capture.yaml")
        self.mundos_root = Path(mundos_root or self.repo_root / "mundos")
        self.media_reader = media_reader
        loaded = load_policy(self.config_path)
        # Native ingress never falls back to the old chat-only policy.  The
        # compatibility poller may continue using that policy until retirement.
        native_policy = replace(loaded.policy, require_binding=True)
        native_config = CaptureConfig(native_policy, loaded.limits)
        world = active_world.strip() or load_active_world(
            self.config_path,
            os.environ.get("DEMIURGOS_WORLD", ""),
        )
        self.runtime = runtime or IdeaCaptureRuntime(
            config=native_config,
            state_path=state_path or self.repo_root / "data" / "idea-capture.sqlite3",
            mundos_root=self.mundos_root,
            active_world=world,
            global_ideas_root=self.repo_root / "ideas",
        )
        effective_policy = runtime.config.policy if runtime is not None else native_policy
        # Capture always lands in the global Taller de Ideas, so no world is
        # required to enable the handler: authorized bindings are enough.
        self.enabled = bool(effective_policy.authorized_bindings)

    @property
    def policy(self):
        return self.runtime.config.policy

    def _binding_key(self, source) -> str:
        platform = str(getattr(getattr(source, "platform", None), "value", ""))
        return ":".join((
            platform,
            str(getattr(source, "chat_id", "")),
            str(getattr(source, "user_id", "")),
            str(getattr(source, "profile", None) or "default"),
        ))

    def _binding_allowed(self, source) -> bool:
        return self._binding_key(source) in self.policy.authorized_bindings

    def _update_from_event(self, event) -> TelegramUpdate:
        source = event.source
        try:
            update_id = int(event.platform_update_id)
            chat_id = int(source.chat_id)
            sender_id = int(source.user_id)
        except (TypeError, ValueError):
            raise ValueError("Hermes event has no valid Telegram identity")

        text = getattr(event, "text", "") or ""
        paths = list(getattr(event, "media_urls", None) or [])
        if not paths:
            if not text:
                raise ValueError("Hermes event has no capturable text or media")
            media = MediaInput(MediaKind.TEXT, text=text)
        else:
            types = list(getattr(event, "media_types", None) or [])
            path = str(paths[0])
            mime = str(types[0]) if types else ""
            data = self.media_reader(path)
            message_type = getattr(getattr(event, "message_type", None), "value", "")
            if mime.startswith("image/") or message_type in {"photo", "image"}:
                media = MediaInput(
                    MediaKind.IMAGE, data=data, mime=mime or "image/jpeg",
                    text=text, path=path,
                )
            elif mime.startswith("audio/") or message_type in {"voice", "audio"}:
                durations = getattr(event, "media_durations", None) or []
                duration = durations[0] if durations else None
                media = MediaInput(
                    MediaKind.VOICE, data=data, mime=mime or "audio/ogg",
                    duration_seconds=duration, text=text, path=path,
                )
            else:
                raise ValueError("Hermes media type is not capturable")
        return TelegramUpdate(
            update_id, chat_id, sender_id,
            str(getattr(source, "chat_type", "")) in {"group", "forum"},
            media,
            platform=str(getattr(getattr(source, "platform", None), "value", "telegram")),
            profile=str(getattr(source, "profile", None) or "default"),
        )

    def _update_from_event_with_voice_probe(self, event, gateway=None) -> TelegramUpdate:
        """Like ``_update_from_event``, but probes VOICE duration from the cache.

        Hermes v0.20's ``MessageEvent`` has no ``media_durations`` field, so a
        voice note arrives with ``duration_seconds=None`` and ``validate_media``
        would reject it (media.py requires a duration <= 300s). The bundled
        TelegramAdapter exposes ``_probe_voice_duration_seconds`` (mutagen ->
        ffprobe); we reuse it on the cached path and rebuild the ``MediaInput``
        with the probed duration so voice notes pass validation (R-2 / S-2.3).

        ``gateway`` is part of the intake-hook contract (the design's hook
        passes it); the probe needs no gateway state today.

        Fail closed (S-10.5): when the probe is unavailable or raises, the
        update keeps ``duration_seconds=None`` and ``validate_media`` rejects
        the capture — the hook maps that to ``skip-rejected``, never a leak.
        """
        update = self._update_from_event(event)
        if (
            update.media.kind is not MediaKind.VOICE
            or update.media.duration_seconds is not None
        ):
            return update
        try:
            duration = _probe_voice_duration(update.media.path)
        except Exception:  # noqa: BLE001 — fail closed, never crash dispatch
            duration = None
        if duration is None:
            return update
        return replace(
            update,
            media=replace(update.media, duration_seconds=float(duration)),
        )
