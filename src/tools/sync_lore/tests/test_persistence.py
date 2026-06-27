"""
tests/test_persistence.py — Unit tests for persistence layer.

Tests write_lore_index, try_engram_save, and print_report.
Mocks subprocess for Engram calls.
"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import importlib

schemas = importlib.import_module("sync-lore.schemas")
persistence = importlib.import_module("sync-lore.persistence")


class TestWriteLoreIndex(unittest.TestCase):
    """JSON file output."""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp(prefix="sync_lore_persist_"))

    def tearDown(self):
        import shutil
        if self.tmpdir.exists():
            shutil.rmtree(self.tmpdir)

    def test_writes_valid_json(self):
        """write_lore_index produces valid lore-index.json."""
        index = schemas.LoreIndex()
        index.meta = schemas.LoreIndexMeta(
            world="vibrantes",
            mode="text",
            chunks_processed=10,
            entities_extracted=5,
            contradictions_found=2,
            generated_at="2025-01-01T00:00:00+00:00",
        )

        output_path = persistence.write_lore_index(index, self.tmpdir)
        self.assertTrue(output_path.exists())

        with open(output_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        self.assertEqual(data["meta"]["world"], "vibrantes")
        self.assertEqual(data["meta"]["mode"], "text")
        self.assertEqual(data["meta"]["chunks_processed"], 10)
        self.assertEqual(data["meta"]["entities_extracted"], 5)

    def test_output_dir_created(self):
        """write_lore_index creates the output directory if needed."""
        subdir = self.tmpdir / "sub" / "nested"
        index = schemas.LoreIndex()
        output_path = persistence.write_lore_index(index, subdir)
        self.assertTrue(output_path.exists())

    def test_entities_serialized(self):
        """Entities are correctly serialized without image_bytes."""
        index = schemas.LoreIndex()
        index.meta = schemas.LoreIndexMeta()
        entity = schemas.LoreEntity(
            id="abc-123",
            name="Kaelen",
            type="personaje",
            world="vibrantes",
            description="A warrior.",
            relations=[{"target": "Ayagar", "type": "gobierna", "strength": 1.0}],
            quotes=["Kaelen raised his blade."],
            stal_tier="T1",
        )
        index.entities = [entity]

        output_path = persistence.write_lore_index(index, self.tmpdir)
        with open(output_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        self.assertEqual(len(data["entities"]), 1)
        self.assertEqual(data["entities"][0]["name"], "Kaelen")
        self.assertEqual(data["entities"][0]["type"], "personaje")
        self.assertTrue(data["entities"][0]["immutable"])
        self.assertEqual(len(data["entities"][0]["quotes"]), 1)


class TestTryEngramSave(unittest.TestCase):
    """Engram persistence via subprocess."""

    def setUp(self):
        self.index = schemas.LoreIndex()
        self.index.meta = schemas.LoreIndexMeta(
            world="vibrantes",
            mode="text",
            chunks_processed=5,
            entities_extracted=3,
            contradictions_found=0,
        )

    def test_command_has_expected_args(self):
        """try_engram_save builds the correct subprocess command."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            result = persistence.try_engram_save(self.index, "vibrantes")
            self.assertTrue(result)

            # Verify subprocess.run was called
            mock_run.assert_called_once()
            call_args = mock_run.call_args[0][0]

            # Check command structure
            self.assertEqual(call_args[0], "engram")
            self.assertEqual(call_args[1], "mem")
            self.assertEqual(call_args[2], "save")

            # Check key flags
            args_list = call_args
            self.assertIn("--project", args_list)
            self.assertIn("vibrantes", args_list)
            self.assertIn("--topic-key", args_list)
            self.assertIn("--capture-prompt", args_list)
            self.assertIn("false", args_list)

    def test_topic_key_format_with_world(self):
        """topic_key uses lore/{world}/index format."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            persistence.try_engram_save(self.index, "vibrantes")

            call_args = mock_run.call_args[0][0]
            topic_idx = call_args.index("--topic-key")
            topic_value = call_args[topic_idx + 1]
            self.assertEqual(topic_value, "lore/vibrantes/index")

    def test_topic_key_format_generic(self):
        """When world is None, topic_key uses lore/generic/index."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            persistence.try_engram_save(self.index, None)

            call_args = mock_run.call_args[0][0]
            topic_idx = call_args.index("--topic-key")
            topic_value = call_args[topic_idx + 1]
            self.assertEqual(topic_value, "lore/generic/index")

    def test_capture_prompt_false_present(self):
        """--capture-prompt false is included in the command."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            persistence.try_engram_save(self.index, "vibrantes")

            call_args = mock_run.call_args[0][0]
            cp_idx = call_args.index("--capture-prompt")
            cp_value = call_args[cp_idx + 1]
            self.assertEqual(cp_value, "false")

    def test_content_includes_stats(self):
        """Content string includes entity/term/contradiction counts."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            persistence.try_engram_save(self.index, "vibrantes")

            call_args = mock_run.call_args[0][0]
            content_idx = call_args.index("--content")
            content_value = call_args[content_idx + 1]
            self.assertIn("3 entities", content_value)
            self.assertIn("0 terms", content_value)
            self.assertIn("0 contradictions", content_value)

    def test_title_includes_world_name(self):
        """Title includes the world name."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            persistence.try_engram_save(self.index, "vibrantes")

            call_args = mock_run.call_args[0][0]
            title_idx = call_args.index("--title")
            title_value = call_args[title_idx + 1]
            self.assertIn("vibrantes", title_value)

    def test_returns_false_on_subprocess_error(self):
        """Returns False when subprocess.run raises an exception."""
        with patch("subprocess.run", side_effect=FileNotFoundError):
            result = persistence.try_engram_save(self.index, "vibrantes")
            self.assertFalse(result)

    def test_returns_false_on_nonzero_exit(self):
        """Returns False when subprocess returns nonzero."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1)
            result = persistence.try_engram_save(self.index, "vibrantes")
            self.assertFalse(result)

    def test_returns_false_on_timeout(self):
        """Returns False when subprocess times out."""
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="engram", timeout=15)):
            result = persistence.try_engram_save(self.index, "vibrantes")
            self.assertFalse(result)


class TestPrintReport(unittest.TestCase):
    """print_report output verification."""

    def test_report_includes_world(self):
        """Report includes the world name."""
        index = schemas.LoreIndex()
        index.meta = schemas.LoreIndexMeta(
            world="vibrantes",
            mode="text",
            chunks_processed=5,
            entities_extracted=10,
            contradictions_found=0,
        )

        import io
        captured = io.StringIO()
        old_stderr = sys.stderr
        sys.stderr = captured
        try:
            persistence.print_report(
                index=index,
                output_path=Path("/tmp/test.json"),
                engram_ok=True,
                files_processed=3,
                files_omitted=1,
                chunks_failed=0,
                images_processed=0,
            )
            output = captured.getvalue()
            self.assertIn("vibrantes", output)
        finally:
            sys.stderr = old_stderr

    def test_report_generic_world(self):
        """Report shows 'generic' when world is None."""
        index = schemas.LoreIndex()
        index.meta = schemas.LoreIndexMeta(
            world=None,
            mode="text",
            chunks_processed=1,
            entities_extracted=0,
            contradictions_found=0,
        )

        import io
        captured = io.StringIO()
        old_stderr = sys.stderr
        sys.stderr = captured
        try:
            persistence.print_report(
                index=index,
                output_path=Path("/tmp/test.json"),
                engram_ok=False,
            )
            output = captured.getvalue()
            self.assertIn("generic", output)
        finally:
            sys.stderr = old_stderr


if __name__ == "__main__":
    unittest.main()
