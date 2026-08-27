"""Asynchronous enrichment, canonical local write, and outbox draining."""

import re
from pathlib import Path

from .enrich import _derive_bullets, _structure_body
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
            body, idea_type, title = self._split_enrich(
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
            # Every idea gets a human-readable title: the enrichment's title
            # when it produced one, else a heuristic from the body's first
            # words. The title is sanitized so it stays a safe single-line
            # frontmatter value (R-TITLE-01).
            if not isinstance(title, str) or not title.strip():
                title = self._title_from_body(body)
            title = self._sanitize_title(title)
            if not re.fullmatch(r"[A-Za-z0-9_-]+", record.slug):
                raise ValueError("unsafe slug")
            if record.global_:
                if self.global_ideas_root is None:
                    raise ValueError("global capture requires a global_ideas_root")
                # Copy image bytes to <global_ideas_root>/media/{slug}.{ext} and
                # persist the relative media_path. Text/voice captures return
                # None (no copy, no media_path field) — see _copy_media.
                idea_media_path = self._copy_media(record)
                # Canonical markdown structure for the bank body: new
                # enrichment providers structure in enrichment; legacy
                # providers get the local fallback so every idea in the bank
                # shares the same scheme (## Descripción / ## Detalles).
                body_text = self._ensure_structured(body)
                if idea_media_path:
                    # Self-contained embed; MarkdownImage already passes /api/
                    # paths through, so the idea renders regardless of context.
                    # The embed stays ABOVE the first heading (## Descripción).
                    media_file = Path(idea_media_path).name
                    body_text = f"![idea image](/api/ideas/media/{media_file})\n\n{body_text}"
                media_field = f"media_path: {idea_media_path}\n" if idea_media_path else ""
                destination = self.global_ideas_root / f"{record.slug}.md"
                content = (f"---\nid: {record.capture_id}\nslug: {record.slug}\n"
                           f"version: 1\n"
                           f"timestamp: {record.created_at}\n"
                           f"source: telegram\ntype: {idea_type}\ntitle: {title}\ntags: []\n"
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
        """Normalize the enrich seam to ``(body, type, title="")``.

        New providers return ``(body, type, title)``; providers returning a
        ``(body, type)`` tuple (and legacy string-returning providers) are
        tolerated and fail open to an empty title.
        """
        if isinstance(result, tuple):
            if len(result) >= 3:
                return result[0], result[1], result[2]
            if len(result) == 2:
                return result[0], result[1], ""
        return result, "sin_clasificar", ""

    @staticmethod
    def _title_from_body(body: str, max_words: int = 5) -> str:
        """Heuristic title from the body's first words (fail-open fallback).

        Markdown-aware: heading lines (``## Descripción``), image embeds,
        bullet items (``- ``), markdown-quote/emphasis lines (``> ``, ``* ``)
        and fenced-code markers are skipped so a structured body yields a
        title from the actual description content, never from structural
        markdown.
        """
        if not isinstance(body, str):
            return ""
        for line in body.strip().splitlines():
            stripped = line.strip()
            if (
                not stripped
                or stripped.startswith(("#", "![", "- ", "> ", "* ", "`"))
            ):
                continue
            words = [w for w in stripped.split() if w]
            if words:
                return " ".join(words[:max_words])
        return ""

    @staticmethod
    def _ensure_structured(body: str) -> str:
        """Guarantee the canonical markdown structure for the written body.

        New enrichment providers return the structured body already
        (``## Descripción`` + ``## Detalles``); legacy providers that return a
        plain text body are wrapped with the local ``_structure_body``
        fallback so every idea in the bank shares the same scheme. Never
        blocks capture — a body already structured (first line a ``##``
        heading) passes through untouched, and an empty body stays empty.
        """
        text = body.strip()
        if not text:
            return text
        if text.splitlines()[0].strip().startswith("## "):
            return text
        return _structure_body(text, bullets=_derive_bullets(text))

    @staticmethod
    def _sanitize_title(title: str, max_chars: int = 80) -> str:
        """Make a frontmatter-safe single-line title.

        The idea file's frontmatter is a hand-rolled ``key: value`` template,
        so the title must not carry characters that break YAML parsing
        (colons, hashes, newlines, quotes, aliases, block-scalar and flow
        sigils). ``ideas_bank`` re-reads the file leniently — an unsanitized
        title like ``mapa: del reino``, ``* El reino`` (alias) or ``> cita``
        (block scalar) would make ``yaml.safe_load`` fail and hide the idea
        from the bank.
        """
        if not isinstance(title, str):
            return ""
        cleaned = " ".join(title.split())
        # Strip YAML/markdown chars that break a plain scalar in a hand-rolled
        # frontmatter value: colons, hashes, quotes, and the sigils that mark
        # aliases (*), block scalars (>, |), flow collections ({}[]), anchors
        # (&), tags (!), and backticks.
        cleaned = (
            cleaned.replace(":", "")
            .replace("#", "")
            .replace("*", "")
            .replace(">", "")
            .replace("|", "")
            .replace("&", "")
            .replace("!", "")
            .replace("{", "")
            .replace("}", "")
            .replace("[", "")
            .replace("]", "")
            .replace("`", "")
            .strip("'\"- \t")
        )
        return cleaned[:max_chars].strip()

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
