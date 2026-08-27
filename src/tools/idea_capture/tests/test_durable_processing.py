import tempfile
import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from idea_capture.enrich import MediaEnrichProvider
from idea_capture.models import MediaInput, MediaKind, TelegramUpdate, WorldAction
from idea_capture.outbox import MemoryPublisher
from idea_capture.processor import IdeaProcessor
from idea_capture.service import CaptureService
from idea_capture.store import CaptureStore
from idea_capture.telegram import IngressPolicy, TelegramIngress
from idea_capture.worker import CaptureWorker


class DurableProcessingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = CaptureStore(self.root / "capture.sqlite3")
        ingress = TelegramIngress(IngressPolicy(frozenset({7}), {}), lambda _: None)
        self.service = CaptureService(ingress, self.store, "vibrantes")

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def update(self, update_id=1, text="A durable idea"):
        return TelegramUpdate(update_id, 7, 8, False,
                              MediaInput(MediaKind.TEXT, text=text))

    def test_replay_reuses_durable_capture(self):
        first = self.service.accept(self.update())
        second = self.service.accept(self.update())
        self.assertEqual(first.capture_id, second.capture_id)
        self.assertEqual(self.store.count(), 1)

    def test_raw_is_available_when_processing_fails(self):
        receipt = self.service.accept(self.update())
        self.service.confirm(receipt.capture_id, WorldAction.SAVE)
        processor = IdeaProcessor(self.store, self.root / "mundos", lambda _: (_ for _ in ()).throw(IOError("down")))
        with self.assertRaises(IOError):
            processor.process(receipt.capture_id)
        record = self.store.get(receipt.capture_id)
        self.assertEqual(record.state.value, "RETRYABLE")
        self.assertEqual(record.raw_text, "A durable idea")
        self.assertEqual(record.attempt, 1)

    def test_invalid_world_and_schema_fail_closed(self):
        receipt = self.service.accept(self.update())
        with self.assertRaises(ValueError):
            self.service.confirm(receipt.capture_id, WorldAction.CHANGE_WORLD, "../unsafe")

    def test_voice_receipt_is_immediate_and_processing_is_separate(self):
        update = TelegramUpdate(4, 7, 8, False,
                                MediaInput(MediaKind.VOICE, b"OggS raw", "audio/ogg", 2))
        receipt = self.service.accept(update)
        self.assertEqual(receipt.status, "RAW_PERSISTED")
        self.assertEqual(self.store.get(receipt.capture_id).state.value, "RAW_PERSISTED")

    def test_retries_are_bounded_and_become_error(self):
        receipt = self.service.accept(self.update())
        self.service.confirm(receipt.capture_id, WorldAction.SAVE)
        processor = IdeaProcessor(self.store, self.root / "mundos", lambda _: (_ for _ in ()).throw(IOError("down")))
        for _ in range(5):
            with self.assertRaises(IOError):
                processor.process(receipt.capture_id)
        self.assertEqual(self.store.get(receipt.capture_id).state.value, "ERROR")

    def test_delete_for_world_scopes_rows(self):
        first = self.service.accept(self.update())
        second = self.service.accept(self.update(update_id=2))
        self.store.set_world(first.capture_id, "Avalor")
        self.store.set_world(second.capture_id, "Kaelia")
        removed = self.store.delete_for_world("Avalor")
        self.assertEqual(removed, 1)
        self.assertEqual(self.store.count(), 1)
        self.assertEqual(self.store.get(second.capture_id).world, "Kaelia")
        self.assertEqual(self.store.delete_for_world("Kaelia"), 1)
        self.assertEqual(self.store.count(), 0)
        self.assertEqual(self.store.delete_for_world("Avalor"), 0)

    def test_outbox_publish_is_idempotent(self):
        receipt = self.service.accept(self.update())
        self.service.confirm(receipt.capture_id, WorldAction.SAVE)
        publisher = MemoryPublisher()
        IdeaProcessor(self.store, self.root / "mundos", lambda raw: raw, publisher).process(receipt.capture_id)
        IdeaProcessor(self.store, self.root / "mundos", lambda raw: raw, publisher).drain_outbox()
        IdeaProcessor(self.store, self.root / "mundos", lambda raw: raw, publisher).drain_outbox()
        self.assertEqual(len(publisher.messages), 1)

    def test_worker_submit_saves_idea_and_outbox_remains_correct(self):
        """Regression: CaptureWorker.submit() must be thread-safe with the
        durable store (per-thread connections), reach SAVED, and keep the
        outbox exactly one message that drains exactly once."""
        receipt = self.service.accept(self.update())
        self.service.confirm(receipt.capture_id, WorldAction.SAVE)
        publisher = MemoryPublisher()
        processor = IdeaProcessor(self.store, self.root / "mundos", lambda raw: raw, publisher)
        worker = CaptureWorker(processor)
        try:
            saved = worker.submit(receipt.capture_id).result(timeout=5)
        finally:
            worker.close()

        self.assertEqual(saved.state.value, "SAVED")
        current = self.store.get(receipt.capture_id)
        self.assertEqual(current.state.value, "SAVED")
        self.assertEqual(current.attempt, 0)
        self.assertIsNone(current.error)
        self.assertTrue(
            (self.root / "mundos" / "vibrantes" / "Ideas" / f"{saved.slug}.md").exists())
        self.assertEqual(len(self.store.pending_outbox()), 1)

        # Replay on a fresh worker is a durable no-op (same state, no new outbox row).
        replay_worker = CaptureWorker(processor)
        try:
            replayed = replay_worker.submit(receipt.capture_id).result(timeout=5)
        finally:
            replay_worker.close()
        self.assertEqual(replayed.state.value, "SAVED")

        processor.drain_outbox()
        self.assertEqual(len(publisher.messages), 1)
        self.assertEqual(len(self.store.pending_outbox()), 0)

    def test_related_linker_failure_after_saved_is_non_blocking_and_retryable(self):
        receipt = self.service.accept(self.update())
        self.service.confirm(receipt.capture_id, WorldAction.SAVE)
        processor = IdeaProcessor(self.store, self.root / "mundos", lambda raw: raw)
        saved = processor.process(receipt.capture_id)
        worker = CaptureWorker(processor)
        try:
            result = worker.submit_suggestions(
                receipt.capture_id,
                lambda _: (_ for _ in ()).throw(RuntimeError("linker unavailable")),
            ).result(timeout=2)
        finally:
            worker.close()

        self.assertEqual(saved.state.value, "SAVED")
        self.assertEqual(result, {"status": "suggestions_unavailable"})
        self.assertTrue((self.root / "mundos" / "vibrantes" / "Ideas" / f"{saved.slug}.md").exists())
        current = self.store.get(receipt.capture_id)
        self.assertEqual(current.state.value, "SAVED")
        self.assertEqual(current.attempt, 0)
        self.assertIsNone(current.error)
        self.assertEqual(len(self.store.pending_outbox()), 1)

    # -- expanded enrich seam (PR idea-capture-ai-gate Phase 3, task 3.3) ----

    def test_enrich_seam_passes_media_context_for_voice(self):
        """The expanded seam passes media_kind/media_path/mime to the provider."""
        audio = self.root / "voice.ogg"
        audio.write_bytes(b"OggS\x01fake-voice")
        update = TelegramUpdate(9, 7, 8, False,
                                MediaInput(MediaKind.VOICE, b"OggS\x01fake-voice",
                                           "audio/ogg", 2, path=str(audio)))
        seen = {}

        def media_enrich(raw, *, media_kind=None, media_path=None, mime=None):
            seen["kind"] = media_kind
            seen["path"] = media_path
            seen["mime"] = mime
            return "un recuerdo hablado", "concepto"

        receipt = self.service.accept(update)
        self.service.confirm(receipt.capture_id, WorldAction.SAVE_GLOBAL)
        processor = IdeaProcessor(self.store, self.root / "mundos", media_enrich,
                                  global_ideas_root=self.root / "ideas")
        saved = processor.process(receipt.capture_id)
        self.assertEqual(saved.state.value, "SAVED")
        self.assertIs(seen["kind"], MediaKind.VOICE)
        self.assertEqual(seen["path"], str(audio))
        self.assertEqual(seen["mime"], "audio/ogg")

    def test_legacy_single_arg_enrich_still_works(self):
        """Providers predating the seam accept only raw; the retry must not mask
        internal provider TypeErrors."""
        receipt = self.service.accept(self.update())
        self.service.confirm(receipt.capture_id, WorldAction.SAVE)
        processor = IdeaProcessor(self.store, self.root / "mundos", lambda raw: raw)
        saved = processor.process(receipt.capture_id)
        self.assertEqual(saved.state.value, "SAVED")

    def test_media_caption_retained_when_enrich_fails_open(self):
        """S-5.3: image + vision off -> the caption body is retained (SAVED)."""
        update = TelegramUpdate(10, 7, 8, False,
                                MediaInput(MediaKind.IMAGE, b"\x89PNG\r\n\x1a\nx",
                                           "image/png", text="el mapa de la corte"))
        receipt = self.service.accept(update)
        self.service.confirm(receipt.capture_id, WorldAction.SAVE_GLOBAL)
        provider = MediaEnrichProvider(vision_enabled=False)  # fails open: empty body
        processor = IdeaProcessor(self.store, self.root / "mundos", provider,
                                  global_ideas_root=self.root / "ideas")
        saved = processor.process(receipt.capture_id)
        self.assertEqual(saved.state.value, "SAVED")
        content = (self.root / "ideas" / f"{saved.slug}.md").read_text(encoding="utf-8")
        self.assertIn("el mapa de la corte", content)
        self.assertIn("type: sin_clasificar", content)


if __name__ == "__main__":
    unittest.main()
