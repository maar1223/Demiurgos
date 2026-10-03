import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from idea_capture.media import MediaValidationError
from idea_capture.models import MediaInput, MediaKind, TelegramUpdate, WorldAction
from idea_capture.telegram import IngressPolicy, TelegramIngress, UnauthorizedUpdate


class IngressTests(unittest.TestCase):
    def setUp(self):
        self.audit = []
        self.ingress = TelegramIngress(IngressPolicy(frozenset({7}), {99: frozenset({8})}), self.audit.append)

    def update(self, media, chat=7, sender=8, group=False, update_id=1):
        return TelegramUpdate(update_id, chat, sender, group, media)

    def test_unauthorized_is_audit_only_and_does_not_persist_content(self):
        with self.assertRaises(UnauthorizedUpdate):
            self.ingress.accept(self.update(MediaInput(MediaKind.TEXT, text="secret"), chat=55), "vibrantes")
        self.assertEqual(self.audit[0]["event"], "unauthorized_update")
        self.assertNotIn("secret", str(self.audit))

    def test_group_requires_chat_and_sender_policy(self):
        receipt = self.ingress.accept(self.update(MediaInput(MediaKind.TEXT, text="idea"), chat=99, group=True), "vibrantes")
        self.assertEqual(receipt.status, "AWAITING_WORLD")
        with self.assertRaises(UnauthorizedUpdate):
            self.ingress.accept(self.update(MediaInput(MediaKind.TEXT, text="idea"), chat=99, sender=77, group=True, update_id=2), "vibrantes")

    def test_media_is_sniffed_and_limited(self):
        image = MediaInput(MediaKind.IMAGE, b"\x89PNG\r\n\x1a\nbytes", "image/png")
        self.assertEqual(self.ingress.accept(self.update(image), "vibrantes").status, "AWAITING_WORLD")
        with self.assertRaises(MediaValidationError):
            self.ingress.accept(self.update(MediaInput(MediaKind.IMAGE, b"bad", "image/png"), update_id=2), "vibrantes")
        with self.assertRaises(MediaValidationError):
            self.ingress.accept(self.update(MediaInput(MediaKind.VOICE, b"OggS", "audio/ogg", 301), update_id=3), "vibrantes")

    def test_duplicate_update_is_acknowledged_without_second_accept(self):
        media = MediaInput(MediaKind.TEXT, text="idea")
        self.ingress.accept(self.update(media), "vibrantes")
        self.assertEqual(self.ingress.accept(self.update(media), "vibrantes").status, "DUPLICATE")

    def test_world_controls_require_explicit_confirmation(self):
        self.assertEqual(TelegramIngress.world_buttons(), ("Save", "Change world", "Cancel"))
        self.assertEqual(self.ingress.confirm_world(WorldAction.SAVE, "vibrantes"), "vibrantes")
        self.assertEqual(self.ingress.confirm_world(WorldAction.CANCEL, "vibrantes"), None)
        self.assertEqual(self.ingress.confirm_world(WorldAction.CHANGE_WORLD, "vibrantes", "nec"), "nec")

    def test_launcher_has_no_provider_gate_and_never_starts_a_second_owner(self):
        # S2b (S2-2): Hermes is optional, so the launcher has no provider
        # health gate at all. Idempotency now rests on the API ownership gate:
        # an existing Demiurgos API listener is adopted, and a foreign port
        # squatter is refused (spec "Port already in use").
        launcher = Path(__file__).resolve().parents[4] / "start-demiurgos.ps1"
        source = launcher.read_text(encoding="utf-8")
        self.assertNotIn("Test-HermesHealthy", source)
        self.assertIn("Test-ApiOwnership", source)
        self.assertIn("uvicorn api_server:app", source)
        self.assertIn("Already running api", source)


if __name__ == "__main__":
    unittest.main()
