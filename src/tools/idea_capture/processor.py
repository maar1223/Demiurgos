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
            body, idea_type = self._split_enrich(self.enrich(raw_input))
            if not isinstance(body, str) or not body.strip():
                raise ValueError("enrichment produced empty idea")
            if not re.fullmatch(r"[A-Za-z0-9_-]+", record.slug):
                raise ValueError("unsafe slug")
            if record.global_:
                if self.global_ideas_root is None:
                    raise ValueError("global capture requires a global_ideas_root")
                destination = self.global_ideas_root / f"{record.slug}.md"
                content = (f"---\nid: {record.capture_id}\nslug: {record.slug}\n"
                           f"timestamp: {record.created_at}\n"
                           f"source: telegram\ntype: {idea_type}\ntags: []\n"
                           "status: fresh\nused_in: []\n---\n\n"
                           f"{body.strip()}\n")
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

    def drain_outbox(self):
        for row in self.store.pending_outbox():
            self.publisher.publish(row["topic"], row["payload"])
            self.store.publish_outbox(row["topic"])
