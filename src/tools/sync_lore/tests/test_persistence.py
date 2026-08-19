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
    """The legacy lore-index.json file output is RETIRED (world-importer IM6)."""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp(prefix="sync_lore_persist_"))

    def tearDown(self):
        import shutil
        if self.tmpdir.exists():
            shutil.rmtree(self.tmpdir)

    def test_write_is_retired_raises(self):
        """write_lore_index raises RetiredLegacyIndexError and never writes."""
        index = schemas.LoreIndex()
        index.meta = schemas.LoreIndexMeta(world="vibrantes")
        with self.assertRaises(persistence.RetiredLegacyIndexError):
            persistence.write_lore_index(index, self.tmpdir)
        self.assertFalse((self.tmpdir / "lore-index.json").exists())

    def test_no_file_written_in_nested_dir(self):
        """Retirement applies regardless of output directory; no file appears."""
        subdir = self.tmpdir / "sub" / "nested"
        index = schemas.LoreIndex()
        with self.assertRaises(persistence.RetiredLegacyIndexError):
            persistence.write_lore_index(index, subdir)
        self.assertFalse((self.tmpdir / "lore-index.json").exists())
        self.assertFalse((subdir / "lore-index.json").exists())

    def test_retirement_message_mentions_job_contract(self):
        """The retirement error guides callers to the job contract replacement."""
        index = schemas.LoreIndex()
        with self.assertRaises(persistence.RetiredLegacyIndexError) as ctx:
            persistence.write_lore_index(index, self.tmpdir)
        self.assertIn("retired", str(ctx.exception).lower())
        self.assertIn("job", str(ctx.exception).lower())


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
