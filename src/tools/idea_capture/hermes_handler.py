"""Hermes-native idea capture handler.

This module consumes Hermes' normalized ``MessageEvent`` and media-cache paths.
It deliberately has no Telegram SDK, Bot API, token, or polling dependency.
"""

from __future__ import annotations

import os
import re
from dataclasses import replace
from pathlib import Path
from typing import Callable

from .config import CaptureConfig, load_active_world, load_policy
from .media import MediaValidationError, validate_media
from .models import MediaInput, MediaKind, TelegramUpdate, WorldAction
from .runtime import (
    IdeaCaptureRuntime,
    build_capture_keyboard,
    build_world_keyboard,
    handle_confirmation_command,
    parse_capture_callback,
)
from .telegram import UnauthorizedUpdate


_SAFE_WORLD = re.compile(r"^[A-Za-z0-9_-]+$")


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
        )
        effective_policy = runtime.config.policy if runtime is not None else native_policy
        self.enabled = bool(effective_policy.authorized_bindings and _SAFE_WORLD.fullmatch(world or ""))

    @property
    def policy(self):
        return self.runtime.config.policy

    async def handle_message(self, *, event, adapter=None, **_) -> bool:
        """Consume one already Hermes-authorized message when capture policy allows."""
        source = getattr(event, "source", None)
        if source is None or str(getattr(source.platform, "value", source.platform)) != "telegram":
            return False

        text = getattr(event, "text", "") or ""
        if text.startswith("/"):
            command = event.get_command()
            if command not in {"save", "world", "cancel"}:
                return False
            if not self._binding_allowed(source):
                return True
            reply = handle_confirmation_command(self.runtime, text)
            if adapter is not None:
                await adapter.send(source.chat_id, reply)
            return True

        if not self.enabled:
            return False
        update = self._update_from_event(event)
        try:
            receipt = self.runtime.service.accept(update)
        except UnauthorizedUpdate:
            return True
        except (MediaValidationError, ValueError):
            return True
        if receipt.status == "DUPLICATE":
            return True

        if adapter is not None:
                await adapter.send_interaction_message(
                    source.chat_id,
                    f"Idea capturada (id=`{receipt.capture_id}`). Elegí una acción:",
                    build_capture_keyboard(receipt.capture_id)["inline_keyboard"],
                metadata={"thread_id": source.thread_id} if source.thread_id else None,
            )
        return True

    async def handle_interaction(self, *, interaction, **_) -> bool:
        """Handle Save / Change world / Cancel callbacks and always acknowledge."""
        parsed = parse_capture_callback(getattr(interaction, "data", None))
        if parsed is None:
            await interaction.answer("Acción inválida.")
            return True
        capture_id, action, world = parsed
        source = interaction.source
        if not self._binding_allowed(source):
            await interaction.answer("No autorizado.")
            return True

        try:
            record = self.runtime.store.get(capture_id)
        except KeyError:
            await interaction.answer("Captura no encontrada.")
            return True
        if record.source != self._binding_key(source):
            await interaction.answer("No autorizado.")
            return True

        if action is WorldAction.CHANGE_WORLD and world is None:
            keyboard = build_world_keyboard(self.runtime, capture_id)
            if not keyboard["inline_keyboard"]:
                await interaction.answer("No hay mundos disponibles.")
                return True
            await interaction.send(
                "Elegí el mundo para esta idea:",
                keyboard["inline_keyboard"],
            )
            await interaction.answer("Elegí un mundo.")
            return True

        try:
            if action is WorldAction.CHANGE_WORLD:
                if world not in self.runtime.available_worlds():
                    await interaction.answer("Mundo no disponible.")
                    return True
                self.runtime.confirm(capture_id, action, world)
                answer = f"Idea asignada a {world} (procesando...)."
            elif action is WorldAction.SAVE:
                self.runtime.confirm(capture_id, action)
                answer = f"Idea guardada en {self.runtime.active_world} (procesando...)."
            else:
                self.runtime.confirm(capture_id, action)
                answer = "Idea cancelada."
        except (KeyError, ValueError):
            answer = "No se pudo aplicar esa acción."
        await interaction.answer(answer)
        try:
            await interaction.edit(answer, buttons=[])
        except Exception:
            pass
        return True

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
