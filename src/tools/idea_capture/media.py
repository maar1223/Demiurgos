"""Fail-closed validation for Telegram text, voice, and image payloads."""

from .models import MediaInput, MediaKind

MAX_IMAGE_BYTES = 20 * 1024 * 1024
MAX_AUDIO_BYTES = 50 * 1024 * 1024
MAX_AUDIO_SECONDS = 5 * 60


class MediaValidationError(ValueError):
    pass


def validate_media(media: MediaInput) -> None:
    if media.kind is MediaKind.TEXT:
        if not media.text.strip():
            raise MediaValidationError("text input is empty")
        return

    if media.kind is MediaKind.IMAGE:
        if len(media.data) > MAX_IMAGE_BYTES:
            raise MediaValidationError("image exceeds 20 MB limit")
        signatures = {"image/jpeg": b"\xff\xd8\xff", "image/jpg": b"\xff\xd8\xff",
                      "image/png": b"\x89PNG\r\n\x1a\n",
                      "image/webp": b"RIFF"}
        signature = signatures.get(media.mime)
        if not signature or not media.data.startswith(signature):
            raise MediaValidationError("image MIME or bytes are not allowed")
        return

    if media.kind is MediaKind.VOICE:
        if len(media.data) > MAX_AUDIO_BYTES:
            raise MediaValidationError("audio exceeds 50 MB limit")
        if media.duration_seconds is None or media.duration_seconds > MAX_AUDIO_SECONDS:
            raise MediaValidationError("audio exceeds 5 minute limit")
        signatures = {"audio/ogg": b"OggS", "audio/opus": b"OggS",
                      "audio/mpeg": b"ID3", "audio/mp3": b"ID3",
                      "audio/mp4": b"\x00\x00\x00"}
        signature = signatures.get(media.mime)
        if not signature or not media.data.startswith(signature):
            raise MediaValidationError("audio MIME or bytes are not allowed")
        return

    raise MediaValidationError("unsupported media kind")
