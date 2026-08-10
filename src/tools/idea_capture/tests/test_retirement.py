"""PR4 retirement and rollback contract tests."""

import json
import tempfile
import unittest
from pathlib import Path

from idea_capture.migration import ParityWindow
from idea_capture.retirement import LegacyRetirement


class RetirementTests(unittest.TestCase):
    def _passed_parity(self):
        return ParityWindow(expected_updates=100, observed_updates=100,
                            eventual_successes=99, elapsed_days=14)

    def test_parity_failure_blocks_archive_and_trigger_retirement(self):
        with tempfile.TemporaryDirectory() as root:
            source = Path(root) / "sync-ideas.py"
            source.write_text("legacy", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "retirement blocked"):
                LegacyRetirement(source, Path(root) / "archive").retire(
                    ParityWindow(expected_updates=1, observed_updates=0))
            self.assertFalse((Path(root) / "archive").exists())
            self.assertTrue(source.exists())

    def test_passed_cutover_archives_source_and_limits_rollback_replay(self):
        with tempfile.TemporaryDirectory() as root:
            source = Path(root) / "sync-ideas.py"
            source.write_text("legacy", encoding="utf-8")
            result = LegacyRetirement(source, Path(root) / "archive").retire(
                self._passed_parity(), native_update_ids=("u1",),
                legacy_update_ids=("u1", "u2"), remove_source=True)
            manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
            self.assertFalse(source.exists())
            self.assertTrue(result.archive_path.exists())
            self.assertEqual(manifest["replay_update_ids"], ["u2"])
            self.assertEqual(manifest["disabled_legacy_triggers"], ["Pipedream", "Google Sheets"])
            self.assertRegex(manifest["retention_until"], r"^20")


if __name__ == "__main__":
    unittest.main()
