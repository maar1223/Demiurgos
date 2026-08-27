"""Asynchronous enrichment, canonical local write, and outbox draining."""

import re
from pathlib import Path

from .models import CaptureState, MediaKind
from .outbox import MemoryPublisher
from .store import CaptureStore


class IdeaProcessor:
    def __init__(self, store: CaptureStore, mundos_root: str | Path, enrich, publisher=None,
                 global_ideas_root: str | Path | None = None):
        self.store, self.mundos_root, self.enrich = store, Path(mundos_root), enrich
        self.global_ideas_root = Path(global_ideas_root) if global_ideas_root else None
        self.publisher = publisher or MemoryPublisher()

    def process(self, capture_id: str):
        record = self.store.get(capture_id)
        if record.state is CaptureState.SAVED:
            return record
        try:
            if record.state is CaptureState.CANCELLED:
                raise ValueError("capture is cancelled")
            if not record.global_ and record.world is None:
                raise ValueError("capture requires confirmed world")
            raw_input = record.raw_text if record.media_kind is MediaKind.TEXT else record.raw_bytes
            body, idea_type = self._split_enrich(
                self._enrich_with_media_kind(raw_input, record.media_kind,
                                             record.media_path, record.mime))
            if not isinstance(body, str) or not body.strip():
                # Media captures with a caption fall back to it when the
                # provider fails open with an empty body (vision off,
                # transcription unavailable): the raw body/caption is always
                # retained, never lost (R-5 / S-5.3 / S-5.5 / S-5.7).
                body = record.raw_text.strip()
            if not body:
                raise ValueError("enrichment produced empty idea")
            if not re.fullmatch(r"[A-Za-z0-9_-]+", record.slug):
                raise ValueError("unsafe slug")
            if record.global_:
                if self.global_ideas_root is None:
                    raise ValueError("global capture requires a global_ideas_root")
                # Copy image bytes to <global_ideas_root>/media/{slug}.{ext} and
                # persist the relative media_path. Text/voice captures return
                # None (no copy, no media_path field) — see _copy_media.
                idea_media_path = self._copy_media(record)
                body_text = body.strip()
                if idea_media_path:
                    # Self-contained embed; MarkdownImage already passes /api/
                    # paths through, so the idea renders regardless of context.
                    media_file = Path(idea_media_path).name
                    body_text = f"![idea image](/api/ideas/media/{media_file})\n\n{body_text}"
                media_field = f"media_path: {idea_media_path}\n" if idea_media_path else ""
                destination = self.global_ideas_root / f"{record.slug}.md"
                content = (f"---\nid: {record.capture_id}\nslug: {record.slug}\n"
                           f"timestamp: {record.created_at}\n"
                           f"source: telegram\ntype: {idea_type}\ntags: []\n"
                           "status: fresh\nused_in: []\n"
                           f"{media_field}---\n\n"
                           f"{body_text}\n")
            else:
                destination = self.mundos_root / record.world / "Ideas" / f"{record.slug}.md"
                content = (f"---\nid: {record.capture_id}\nslug: {record.slug}\n"
                           f"timestamp: {record.created_at}\n"
                           "source: telegram\ntype: idea_loose\ntags: []\nstatus: pending\n---\n\n"
                           f"{body.strip()}\n")
            destination.parent.mkdir(parents=True, exist_ok=True)
            temp = destination.with_suffix(".md.tmp")
            temp.write_text(content, encoding="utf-8")
            temp.replace(destination)
            return self.store.mark_saved(capture_id, f"nec/ideas/{record.slug}",
                                         {"slug": record.slug, "content": content})
        except (OSError, ValueError, RuntimeError) as error:
            self.store.mark_retryable(capture_id, str(error))
            raise

    def _enrich_with_media_kind(self, raw_input, media_kind, media_path, mime):
        """Call the enrich seam with the capture's media context, tolerating
        legacy providers.

        Media-aware providers dispatch on ``media_kind`` (and may use the
        persisted ``media_path`` / ``mime``); providers that predate the seam
        accept only the raw input. A ``TypeError`` naming one of the seam
        keywords means the provider does not accept it, so retry without that
        keyword — never mask other internal errors raised by the provider.
        """
        kwargs = {
            "media_kind": media_kind,
            "media_path": media_path,
            "mime": mime,
        }
        while kwargs:
            try:
                return self.enrich(raw_input, **kwargs)
            except TypeError as exc:
                rejected = [name for name in kwargs if name in str(exc)]
                if not rejected:
                    raise
                for name in rejected:
                    kwargs.pop(name)
        return self.enrich(raw_input)

    @staticmethod
    def _split_enrich(result):
        """Normalize the enrich seam to ``(body, type)``.

        New providers return ``(body, type)``; legacy string-returning providers
        (and the identity default) are tolerated and fail open to
        ``sin_clasificar``.
        """
        if isinstance(result, tuple) and len(result) == 2:
            return result[0], result[1]
        return result, "sin_clasificar"

    def _copy_media(self, record) -> str | None:
        """Persist image bytes to ``<global_ideas_root>/media/{slug}.{ext}`` and
        return the relative ``media/{slug}.{ext}`` path.

        Text/voice captures (and images without bytes) return ``None``: no
        copy is made and no ``media_path`` is recorded (S-4.3). For images the
        copy is fail-closed — any OSError propagates so the capture is marked
        retryable and the idea file is never written without its image (R-2).
        """
        if record.media_kind is not MediaKind.IMAGE or not record.raw_bytes:
            return None
        ext = self._ext_for_mime(record.mime)
        media_dir = self.global_ideas_root / "media"
        media_dir.mkdir(parents=True, exist_ok=True)
        target = media_dir / f"{record.slug}{ext}"
        target.write_bytes(record.raw_bytes)
        return f"media/{record.slug}{ext}"

    @staticmethod
    def _ext_for_mime(mime: str) -> str:
        """Map a MIME type to its file extension; unknown image MIMEs default to
        ``.jpg`` so the media endpoint's allowlist still serves them."""
        return {
            "image/jpeg": ".jpg",
            "image/png": ".png",
            "image/gif": ".gif",
            "image/webp": ".webp",
        }.get(mime, ".jpg")

    def drain_outbox(self):
        for row in self.store.pending_outbox():
            self.publisher.publish(row["topic"], row["payload"])
            self.store.publish_outbox(row["topic"])
