import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from idea_capture.migration import HistoricalMigrator, ParityWindow


class MigrationTests(unittest.TestCase):
    def test_conflicting_duplicate_family_is_quarantined_with_rollback_and_provenance(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            legacy = root / "mundos" / "vibrantes" / "Ideas"
            legacy.mkdir(parents=True)
            first = legacy / "first.md"
            second = legacy / "second.md"
            first.write_text('---\nid: "same"\nslug: "same-idea"\n---\nfirst\n', encoding="utf-8")
            second.write_text('---\nid: "same"\nslug: "same-idea"\n---\nsecond\n', encoding="utf-8")

            result = HistoricalMigrator([root / "mundos"], root).migrate(dry_run=False)

            self.assertEqual(result.migrated, 0)
            self.assertEqual(result.quarantined, 2)
            self.assertFalse((root / "mundos" / "vibrantes" / "Ideas" / "same-idea.md").exists())
            self.assertEqual(len(list(result.quarantine_path.glob("*.json"))), 2)
            self.assertEqual(len(list(result.rollback_path.rglob("*.source"))), 2)
            audit = json.loads(result.audit_path.read_text(encoding="utf-8"))
            self.assertEqual({entry["status"] for entry in audit["entries"]}, {"quarantined"})
            self.assertEqual(len(audit["entries"][0]["records"]), 2)

    def test_dry_run_is_non_destructive_and_clusters_identical_records(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            legacy = root / "mundos" / "vibrantes" / "Ideas"
            legacy.mkdir(parents=True)
            for name in ("first.md", "second.md"):
                (legacy / name).write_text('---\nid: "same"\nslug: "same-idea"\n---\nidentical\n', encoding="utf-8")

            result = HistoricalMigrator([root / "mundos"], root).migrate()

            self.assertTrue(result.dry_run)
            self.assertEqual(result.migrated, 1)
            self.assertEqual(result.duplicates, 1)
            self.assertFalse((root / "mundos" / "vibrantes" / "Ideas" / "same-idea.md").exists())

    def test_parity_failure_blocks_retirement(self):
        window = ParityWindow(expected_updates=100, observed_updates=100,
                              eventual_successes=98, elapsed_days=14)
        self.assertFalse(window.evaluate()["passed"])
        with self.assertRaises(RuntimeError):
            window.assert_cutover_allowed()

    def test_parity_thresholds_allow_cutover_only_after_full_window(self):
        window = ParityWindow(expected_updates=100, observed_updates=100,
                              eventual_successes=99, elapsed_days=14)
        self.assertTrue(window.evaluate()["passed"])
        window.assert_cutover_allowed()


if __name__ == "__main__":
    unittest.main()
