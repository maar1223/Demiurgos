"""Converts raw Telegram Bot API updates into platform-neutral TelegramUpdate.

Media bytes are resolved through an injectable ``resolve_file`` callable so the
adapter is fully testable without network calls. With no resolver configured,
any media update is rejected (fail closed). The adapter never talks to the
network itself; a real resolver (Bot API ``getFile`` + download) is provided by
the runtime transport.
"""

from __future__ import annotations

from typing import Callable

from .media import MediaValidationError, validate_media
from .models import MediaInput, MediaKind, TelegramUpdate

FileResolver = Callable[[str], bytes]


class InvalidUpdate(ValueError):
    """The Telegram payload cannot be converted to a capture update."""


def _no_file_resolver(file_id: str) -> bytes:
    raise InvalidUpdate(f"file resolver not configured (file_id={file_id!r})")


def update_from_telegram(
    payload: dict,
    resolve_file: FileResolver = _no_file_resolver,
) -> TelegramUpdate:
    """Convert one Bot API update dict; raises InvalidUpdate when malformed."""
    if not isinstance(payload, dict):
        raise InvalidUpdate("update is not an object")
    update_id = payload.get("update_id")
    message = payload.get("message")
    if not isinstance(update_id, int) or not isinstance(message, dict):
        raise InvalidUpdate("update has no valid message")
    chat = message.get("chat") or {}
    sender = message.get("from") or {}
    chat_id = chat.get("id")
    sender_id = sender.get("id")
    if not isinstance(chat_id, int) or not isinstance(sender_id, int):
        raise InvalidUpdate("chat/from id missing or not an integer")
    is_group = chat.get("type") in ("group", "supergroup")
    media = _media_from_message(message, resolve_file)
    return TelegramUpdate(update_id=update_id, chat_id=chat_id, sender_id=sender_id,
                          is_group=is_group, media=media)


def _media_from_message(message: dict, resolve_file: FileResolver) -> MediaInput:
    text = (message.get("text") or "").strip()
    if text:
        return MediaInput(MediaKind.TEXT, text=text)

    voice = message.get("voice") or message.get("audio")
    if isinstance(voice, dict):
        file_id = voice.get("file_id")
        if not isinstance(file_id, str):
            raise InvalidUpdate("voice/audio message has no file_id")
        mime = voice.get("mime_type") or ("audio/ogg" if "voice" in message else "")
        duration = voice.get("duration")
        if not isinstance(duration, (int, float)):
            raise InvalidUpdate("voice/audio message has no duration")
        media = MediaInput(MediaKind.VOICE, resolve_file(file_id), mime, float(duration))
        _validated(media)
        return media

    photo = message.get("photo")
    if isinstance(photo, list) and photo:
        largest = photo[-1]
        file_id = largest.get("file_id") if isinstance(largest, dict) else None
        if not isinstance(file_id, str):
            raise InvalidUpdate("photo message has no file_id")
        media = MediaInput(MediaKind.IMAGE, resolve_file(file_id), "image/jpeg")
        _validated(media)
        return media

    document = message.get("document") or {}
    mime = document.get("mime_type") or ""
    if mime.startswith("image/"):
        file_id = document.get("file_id")
        if not isinstance(file_id, str):
            raise InvalidUpdate("image document has no file_id")
        media = MediaInput(MediaKind.IMAGE, resolve_file(file_id), mime)
        _validated(media)
        return media

    raise InvalidUpdate("message carries no capturable text or media")


def _validated(media: MediaInput) -> None:
    """validate_media raises MediaValidationError; surface it as InvalidUpdate."""
    try:
        validate_media(media)
    except MediaValidationError as exc:
        raise InvalidUpdate(str(exc)) from exc
