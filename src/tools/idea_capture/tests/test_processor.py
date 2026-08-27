"""Tests for the IdeaProcessor media copy pipeline (R-2, R-4, S-4.3).

Covers: image bytes copied to <global_ideas_root>/media/{slug}.{ext},
media_path persisted as a first-class frontmatter field, the embed prepended
to the body, the fail-closed copy behavior, and the untouched text/voice paths.
"""

import tempfile
import unittest
import sys
import yaml
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from idea_capture.models import MediaInput, MediaKind, TelegramUpdate, WorldAction
from idea_capture.processor import IdeaProcessor
from idea_capture.service import CaptureService
from idea_capture.store import CaptureStore
from idea_capture.telegram import IngressPolicy, TelegramIngress

PNG_BYTES = b"\x89PNG\r\n\x1a\nfake-image-bytes"


class ProcessorMediaTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = CaptureStore(self.root / "capture.sqlite3")
        ingress = TelegramIngress(IngressPolicy(frozenset({7}), {}), lambda _: None)
        self.service = CaptureService(ingress, self.store, "vibrantes")
        self.ideas_root = self.root / "ideas"

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def _processor(self, enrich=None):
        enrich = enrich or (lambda raw, **kw: ("un mapa con tesoros", "concepto"))
        return IdeaProcessor(self.store, self.root / "mundos", enrich,
                             global_ideas_root=self.ideas_root)

    def _capture_image(self, update_id=11, data=PNG_BYTES, mime="image/png",
                       text="el mapa de la corte"):
        update = TelegramUpdate(update_id, 7, 8, False,
                                MediaInput(MediaKind.IMAGE, data, mime, text=text))
        receipt = self.service.accept(update)
        self.service.confirm(receipt.capture_id, WorldAction.SAVE_GLOBAL)
        return self.store.get(receipt.capture_id)

    def test_image_capture_copies_bytes_and_sets_media_path(self):
        record = self._capture_image()
        saved = self._processor().process(record.capture_id)

        self.assertEqual(saved.state.value, "SAVED")
        media_file = self.ideas_root / "media" / f"{record.slug}.png"
        self.assertTrue(media_file.exists())
        self.assertEqual(media_file.read_bytes(), PNG_BYTES)

        content = (self.ideas_root / f"{record.slug}.md").read_text(encoding="utf-8")
        # First-class frontmatter field (R-2 / R-4).
        self.assertIn(f"media_path: media/{record.slug}.png", content)
        # Embed prepended to the body, ABOVE the first heading (## Descripción).
        self.assertIn(f"![idea image](/api/ideas/media/{record.slug}.png)\n\n## Descripción",
                      content)
        self.assertIn("un mapa con tesoros", content)
        # Structured OKF: frontmatter block, blank line, structured body.
        self.assertIn("---\n", content)
        self.assertIn("\n---\n\n", content)
        self.assertIn("## Detalles", content)

    def test_extension_maps_from_mime(self):
        self.assertEqual(IdeaProcessor._ext_for_mime("image/jpeg"), ".jpg")
        self.assertEqual(IdeaProcessor._ext_for_mime("image/png"), ".png")
        self.assertEqual(IdeaProcessor._ext_for_mime("image/gif"), ".gif")
        self.assertEqual(IdeaProcessor._ext_for_mime("image/webp"), ".webp")
        self.assertEqual(IdeaProcessor._ext_for_mime("application/octet-stream"), ".jpg")

    def test_jpeg_image_lands_with_jpg_extension(self):
        record = self._capture_image(data=b"\xff\xd8\xff\xe0fake-jpeg", mime="image/jpeg")
        self._processor().process(record.capture_id)
        media_file = self.ideas_root / "media" / f"{record.slug}.jpg"
        self.assertTrue(media_file.exists())
        content = (self.ideas_root / f"{record.slug}.md").read_text(encoding="utf-8")
        self.assertIn(f"media_path: media/{record.slug}.jpg", content)

    def test_text_capture_has_no_media_path_and_no_media_dir(self):
        update = TelegramUpdate(1, 7, 8, False,
                                MediaInput(MediaKind.TEXT, text="una idea de texto"))
        receipt = self.service.accept(update)
        self.service.confirm(receipt.capture_id, WorldAction.SAVE_GLOBAL)
        saved = self._processor().process(receipt.capture_id)

        self.assertEqual(saved.state.value, "SAVED")
        self.assertFalse((self.ideas_root / "media").exists())
        content = (self.ideas_root / f"{saved.slug}.md").read_text(encoding="utf-8")
        self.assertNotIn("media_path", content)
        self.assertNotIn("![idea image]", content)

    def test_global_body_starts_with_structure_heading(self):
        """The global idea body is structured: ``## Descripción`` first (no
        embed on text), and a legacy provider's plain body gets the local
        fallback structure so every idea shares the same scheme."""
        update = TelegramUpdate(1, 7, 8, False,
                                MediaInput(MediaKind.TEXT, text="una idea de texto"))
        receipt = self.service.accept(update)
        self.service.confirm(receipt.capture_id, WorldAction.SAVE_GLOBAL)
        saved = self._processor().process(receipt.capture_id)

        content = (self.ideas_root / f"{saved.slug}.md").read_text(encoding="utf-8")
        body = content.split("---\n\n", 1)[1]
        self.assertTrue(body.startswith("## Descripción"), body[:60])
        self.assertIn("## Detalles", body)

    def test_structured_provider_body_passes_through_unchanged(self):
        """A provider that already returns a structured body keeps it as-is:
        the processor does NOT double-structure or re-wrap it."""
        structured = ("## Descripción\n\nuna trama genial\n\n"
                      "## Detalles\n\n- giro final\n- protagonista")
        update = TelegramUpdate(1, 7, 8, False,
                                MediaInput(MediaKind.TEXT, text="una trama genial"))
        receipt = self.service.accept(update)
        self.service.confirm(receipt.capture_id, WorldAction.SAVE_GLOBAL)
        processor = IdeaProcessor(
            self.store, self.root / "mundos",
            lambda raw, **kw: (structured, "trama", "La conspiración"),
            global_ideas_root=self.ideas_root)
        saved = processor.process(receipt.capture_id)

        content = (self.ideas_root / f"{saved.slug}.md").read_text(encoding="utf-8")
        self.assertIn(structured, content)
        self.assertEqual(content.count("## Descripción"), 1)

    def test_voice_capture_has_no_media_path_and_no_media_dir(self):
        """S-4.3: audio must not be copied to ideas/media/ nor get media_path."""
        update = TelegramUpdate(4, 7, 8, False,
                                MediaInput(MediaKind.VOICE, b"OggS\x01fake-voice",
                                           "audio/ogg", 2))
        receipt = self.service.accept(update)
        self.service.confirm(receipt.capture_id, WorldAction.SAVE_GLOBAL)
        saved = self._processor().process(receipt.capture_id)

        self.assertEqual(saved.state.value, "SAVED")
        self.assertFalse((self.ideas_root / "media").exists())
        content = (self.ideas_root / f"{saved.slug}.md").read_text(encoding="utf-8")
        self.assertNotIn("media_path", content)
        self.assertNotIn("![idea image]", content)

    def test_fail_closed_copy_failure_does_not_write_idea(self):
        """If the media copy fails, the idea file must NOT be written and the
        capture must be marked retryable (fail-closed, R-2)."""
        record = self._capture_image()
        # Block media/ creation: a file at <ideas_root>/media makes mkdir raise.
        self.ideas_root.mkdir(parents=True, exist_ok=True)
        (self.ideas_root / "media").write_bytes(b"not a directory")

        with self.assertRaises(OSError):
            self._processor().process(record.capture_id)

        self.assertFalse((self.ideas_root / f"{record.slug}.md").exists())
        current = self.store.get(record.capture_id)
        self.assertEqual(current.state.value, "RETRYABLE")
        self.assertEqual(current.attempt, 1)

    def test_world_image_capture_unchanged(self):
        """Non-global (world) image captures keep the legacy path: no media
        copy, no media_path, idea lands under mundos/<world>/Ideas/."""
        update = TelegramUpdate(5, 7, 8, False,
                                MediaInput(MediaKind.IMAGE, PNG_BYTES,
                                           "image/png", text="mapa del mundo"))
        receipt = self.service.accept(update)
        self.service.confirm(receipt.capture_id, WorldAction.SAVE)
        processor = IdeaProcessor(self.store, self.root / "mundos",
                                  lambda raw, **kw: ("mapa local", "idea_loose"))
        saved = processor.process(receipt.capture_id)

        self.assertEqual(saved.state.value, "SAVED")
        self.assertFalse((self.ideas_root / "media").exists())
        content = (self.root / "mundos" / "vibrantes" / "Ideas"
                   / f"{saved.slug}.md").read_text(encoding="utf-8")
        self.assertNotIn("media_path", content)
        self.assertNotIn("![idea image]", content)

    # ------------------------------------------------------------------
    # R-TITLE-01 — human-readable title from enrichment, frontmatter field
    # ------------------------------------------------------------------

    def test_title_from_enrichment_written_to_frontmatter(self):
        """A (body, type, title) enrich result persists ``title:`` in the
        global frontmatter (text captures flow through enrichment)."""
        update = TelegramUpdate(1, 7, 8, False,
                                MediaInput(MediaKind.TEXT, text="una idea de texto"))
        receipt = self.service.accept(update)
        self.service.confirm(receipt.capture_id, WorldAction.SAVE_GLOBAL)
        processor = IdeaProcessor(
            self.store, self.root / "mundos",
            lambda raw, **kw: ("una idea de texto", "trama", "Prototipo de diosa"),
            global_ideas_root=self.ideas_root)
        saved = processor.process(receipt.capture_id)

        self.assertEqual(saved.state.value, "SAVED")
        content = (self.ideas_root / f"{saved.slug}.md").read_text(encoding="utf-8")
        self.assertIn("title: Prototipo de diosa", content)

    def test_title_falls_back_to_body_first_words(self):
        """When enrichment yields an empty title, the body's first 5 words
        become the title (fail-open fallback, R-TITLE-01)."""
        body = "un mapa con tesoros escondidos bajo la catedral"
        update = TelegramUpdate(1, 7, 8, False,
                                MediaInput(MediaKind.TEXT, text=body))
        receipt = self.service.accept(update)
        self.service.confirm(receipt.capture_id, WorldAction.SAVE_GLOBAL)
        processor = IdeaProcessor(
            self.store, self.root / "mundos",
            lambda raw, **kw: (body, "concepto", ""),
            global_ideas_root=self.ideas_root)
        saved = processor.process(receipt.capture_id)

        content = (self.ideas_root / f"{saved.slug}.md").read_text(encoding="utf-8")
        self.assertIn("title: un mapa con tesoros escondidos", content)

    def test_title_is_sanitized_for_frontmatter_safety(self):
        """Colons/newlines in an enrichment title must not break the
        hand-rolled frontmatter (yaml.safe_load would fail otherwise)."""
        update = TelegramUpdate(1, 7, 8, False,
                                MediaInput(MediaKind.TEXT, text="el mapa secreto"))
        receipt = self.service.accept(update)
        self.service.confirm(receipt.capture_id, WorldAction.SAVE_GLOBAL)
        processor = IdeaProcessor(
            self.store, self.root / "mundos",
            lambda raw, **kw: ("el mapa secreto", "concepto", "mapa: del\nreino"),
            global_ideas_root=self.ideas_root)
        saved = processor.process(receipt.capture_id)

        content = (self.ideas_root / f"{saved.slug}.md").read_text(encoding="utf-8")
        self.assertIn("title: mapa del reino", content)
        self.assertNotIn("mapa: del", content)

    def test_title_sanitized_against_yaml_alias_and_block_scalar_sigils(self):
        """Markdown/YAML sigils (alias `*`, block scalar `>`, brackets, etc.)
        in an enrichment title must not break yaml.safe_load on re-read —
        otherwise the idea hides from the bank silently."""
        # A title starting with `*` is a YAML alias; `>` is a block scalar; both
        # make yaml.safe_load raise, hiding the idea. Sanitize them all.
        update = TelegramUpdate(1, 7, 8, False,
                                MediaInput(MediaKind.TEXT, text="el reino del norte"))
        receipt = self.service.accept(update)
        self.service.confirm(receipt.capture_id, WorldAction.SAVE_GLOBAL)
        processor = IdeaProcessor(
            self.store, self.root / "mundos",
            lambda raw, **kw: ("el reino del norte", "concepto",
                               "**El Reino** del Norte > cita"),
            global_ideas_root=self.ideas_root)
        saved = processor.process(receipt.capture_id)

        content = (self.ideas_root / f"{saved.slug}.md").read_text(encoding="utf-8")
        # The sigils are stripped so the frontmatter value is a plain scalar.
        self.assertIn("title: El Reino del Norte", content)
        self.assertNotIn("title: **", content)
        self.assertNotIn("title: >", content)
        self.assertNotIn("title: *", content)
        # yaml.safe_load over the frontmatter must not raise (alias/block-scalar
        # sigils removed), so the idea stays visible in the bank.
        fm = content.split("\n---\n", 1)[0]
        self.assertIsInstance(yaml.safe_load(fm), dict)

    def test_title_fallback_skips_quote_and_emphasis_lines(self):
        """A body starting with `> ` quote or `* ` emphasis lines must not
        feed those markdown sigils into the derived title."""
        update = TelegramUpdate(1, 7, 8, False,
                                MediaInput(MediaKind.TEXT,
                                           text="una idea sobre dragones"))
        receipt = self.service.accept(update)
        self.service.confirm(receipt.capture_id, WorldAction.SAVE_GLOBAL)
        processor = IdeaProcessor(
            self.store, self.root / "mundos",
            lambda raw, **kw: ("> un cita\n\n* un enfasis\n\nlos dragones del norte",
                               "concepto", ""),
            global_ideas_root=self.ideas_root)
        saved = processor.process(receipt.capture_id)

        content = (self.ideas_root / f"{saved.slug}.md").read_text(encoding="utf-8")
        # The derived title is the content line, not the markdown sigil lines.
        self.assertNotIn("title: un cita", content)
        self.assertNotIn("title: un enfasis", content)

    def test_title_fallback_skips_structure_headings(self):
        """A structured body with an empty enrichment title derives the title
        from the description content, never from '## Descripción'."""
        update = TelegramUpdate(1, 7, 8, False,
                                MediaInput(MediaKind.TEXT,
                                           text="un mapa con tesoros escondidos"))
        receipt = self.service.accept(update)
        self.service.confirm(receipt.capture_id, WorldAction.SAVE_GLOBAL)
        processor = IdeaProcessor(
            self.store, self.root / "mundos",
            lambda raw, **kw: ("## Descripción\n\nun mapa con tesoros escondidos\n\n"
                               "## Detalles\n\n- un mapa", "concepto", ""),
            global_ideas_root=self.ideas_root)
        saved = processor.process(receipt.capture_id)

        content = (self.ideas_root / f"{saved.slug}.md").read_text(encoding="utf-8")
        self.assertIn("title: un mapa con tesoros escondidos", content)
        self.assertNotIn("title: ##", content)

    def test_image_capture_title_from_descripcion(self):
        """IMAGE captures get a title from the vision description's first
        words, persisted in the frontmatter alongside media_path."""
        from idea_capture.enrich import MediaEnrichProvider

        record = self._capture_image(text="mapa del mundo")
        enrich = MediaEnrichProvider(
            vision_fn=lambda raw, ctx: {
                "descripcion": "un mapa con tesoros escondidos bajo la corte",
                "tags": ["concepto"],
            },
            vision_enabled=True,
        )
        processor = IdeaProcessor(self.store, self.root / "mundos", enrich,
                                  global_ideas_root=self.ideas_root)
        saved = processor.process(record.capture_id)

        self.assertEqual(saved.state.value, "SAVED")
        content = (self.ideas_root / f"{record.slug}.md").read_text(encoding="utf-8")
        self.assertIn("title: un mapa con tesoros escondidos", content)
        # Media embed + media_path logic unchanged; embed stays ABOVE the
        # structured ## Descripción heading.
        self.assertIn(f"media_path: media/{record.slug}.png", content)
        self.assertIn(
            f"![idea image](/api/ideas/media/{record.slug}.png)\n\n## Descripción",
            content)

    def test_voice_capture_title_from_transcript_enrichment(self):
        """AUDIO captures get a title from the Hermes classifier over the
        transcript, persisted in the frontmatter."""
        from idea_capture.enrich import MediaEnrichProvider

        update = TelegramUpdate(4, 7, 8, False,
                                MediaInput(MediaKind.VOICE, b"OggS\x01fake-voice",
                                           "audio/ogg", 2))
        receipt = self.service.accept(update)
        self.service.confirm(receipt.capture_id, WorldAction.SAVE_GLOBAL)
        enrich = MediaEnrichProvider(
            hermes=lambda raw: ("personaje", "El arquero ciego"),
            transcribe_fn=lambda path, language: "un arquero ciego protege la ciudad",
            language_resolver=lambda: "es",
        )
        processor = IdeaProcessor(self.store, self.root / "mundos", enrich,
                                  global_ideas_root=self.ideas_root)
        saved = processor.process(receipt.capture_id)

        self.assertEqual(saved.state.value, "SAVED")
        content = (self.ideas_root / f"{saved.slug}.md").read_text(encoding="utf-8")
        self.assertIn("title: El arquero ciego", content)

    # ------------------------------------------------------------------
    # R-8 — versioning alignment (ideas-edit-versioning PR 1, S-8.1)
    # ------------------------------------------------------------------

    def test_global_frontmatter_emits_version_1(self):
        """S-8.1 — the global-bank frontmatter template includes ``version: 1``
        for newly captured ideas, and the frontmatter stays parseable."""
        update = TelegramUpdate(1, 7, 8, False,
                                MediaInput(MediaKind.TEXT, text="una idea de texto"))
        receipt = self.service.accept(update)
        self.service.confirm(receipt.capture_id, WorldAction.SAVE_GLOBAL)
        saved = self._processor().process(receipt.capture_id)

        self.assertEqual(saved.state.value, "SAVED")
        content = (self.ideas_root / f"{saved.slug}.md").read_text(encoding="utf-8")
        self.assertIn("version: 1", content)
        frontmatter = content.split("\n---\n", 1)[0]
        self.assertIsInstance(yaml.safe_load(frontmatter), dict)


if __name__ == "__main__":
    unittest.main()