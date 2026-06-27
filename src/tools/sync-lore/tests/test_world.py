"""
tests/test_world.py — Unit tests for world discovery and validation.

Tests discover_world() priority chain and validate_world_structure()
without requiring real filesystem state.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import importlib

world_mod = importlib.import_module("sync-lore.utils.world")


class TestDiscoverWorld(unittest.TestCase):
    """World discovery with env var and directory scan."""

    def setUp(self):
        self._saved_env = os.environ.pop("DEMIURGOS_WORLD", None)
        self.tmpdir = Path(tempfile.mkdtemp(prefix="sync_lore_world_"))

    def tearDown(self):
        if self._saved_env is not None:
            os.environ["DEMIURGOS_WORLD"] = self._saved_env
        elif "DEMIURGOS_WORLD" in os.environ:
            del os.environ["DEMIURGOS_WORLD"]
        import shutil
        if self.tmpdir.exists():
            shutil.rmtree(self.tmpdir)

    def test_env_var_takes_priority(self):
        """DEMIURGOS_WORLD env var is the highest priority source."""
        os.environ["DEMIURGOS_WORLD"] = "vibrantes"
        result = world_mod.discover_world()
        self.assertEqual(result, "vibrantes")

    def test_env_var_unknown_world_still_works(self):
        """Even unknown worlds are returned (validate_world_structure warns, not blocks)."""
        os.environ["DEMIURGOS_WORLD"] = "unknown_world_xyz"
        result = world_mod.discover_world()
        self.assertEqual(result, "unknown_world_xyz")

    def test_no_world_returns_none(self):
        """When no env var and no mundos/ dir, returns None (no sys.exit)."""
        # Save and change cwd to the temp dir to avoid finding real mundos/
        old_cwd = os.getcwd()
        try:
            os.chdir(str(self.tmpdir))
            result = world_mod.discover_world()
            self.assertIsNone(result)
        finally:
            os.chdir(old_cwd)

    def test_mundos_dir_scanned(self):
        """When mundos/ has subdirs, first is returned."""
        old_cwd = os.getcwd()
        try:
            os.chdir(str(self.tmpdir))
            # Create mundos/ with two subdirs
            mundos = self.tmpdir / "mundos"
            (mundos / "vibrantes").mkdir(parents=True)
            (mundos / "otro_mundo").mkdir(parents=True)

            result = world_mod.discover_world()
            # Sorted alphabetically — "otro_mundo" comes before "vibrantes"
            self.assertEqual(result, "otro_mundo")
        finally:
            os.chdir(old_cwd)

    def test_mundos_dir_empty_returns_none(self):
        """Empty mundos/ directory returns None."""
        old_cwd = os.getcwd()
        try:
            os.chdir(str(self.tmpdir))
            (self.tmpdir / "mundos").mkdir()
            result = world_mod.discover_world()
            self.assertIsNone(result)
        finally:
            os.chdir(old_cwd)

    def test_does_not_exit(self):
        """discover_world() never calls sys.exit() — returns None gracefully."""
        old_cwd = os.getcwd()
        try:
            os.chdir(str(self.tmpdir))
            # No env var, no mundos/ dir — should return None without exiting
            result = world_mod.discover_world()
            self.assertIsNone(result)
        finally:
            os.chdir(old_cwd)


class TestValidateWorldStructure(unittest.TestCase):
    """Soft validation of world directory structure."""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp(prefix="sync_lore_val_"))

    def tearDown(self):
        import shutil
        if self.tmpdir.exists():
            shutil.rmtree(self.tmpdir)

    def test_valid_structure(self):
        """validate_world_structure() does not crash with valid structure."""
        old_cwd = os.getcwd()
        try:
            os.chdir(str(self.tmpdir))
            # Create full expected structure
            (self.tmpdir / "mundos" / "vibrantes" / "Personajes").mkdir(parents=True)
            (self.tmpdir / "mundos" / "vibrantes" / "Lore").mkdir(parents=True)

            missing = world_mod.validate_world_structure("vibrantes")
            self.assertEqual(missing, [])
        finally:
            os.chdir(old_cwd)

    def test_missing_dirs_reported(self):
        """Missing expected dirs are reported."""
        old_cwd = os.getcwd()
        try:
            os.chdir(str(self.tmpdir))
            (self.tmpdir / "mundos" / "vibrantes").mkdir(parents=True)
            # No Personajes/ or Lore/ subdirs

            missing = world_mod.validate_world_structure("vibrantes")
            self.assertIn("Personajes", missing)
            self.assertIn("Lore", missing)
        finally:
            os.chdir(old_cwd)

    def test_partial_structure(self):
        """Only missing dirs are reported."""
        old_cwd = os.getcwd()
        try:
            os.chdir(str(self.tmpdir))
            (self.tmpdir / "mundos" / "vibrantes" / "Personajes").mkdir(parents=True)
            # Lore/ is missing

            missing = world_mod.validate_world_structure("vibrantes")
            self.assertNotIn("Personajes", missing)
            self.assertIn("Lore", missing)
        finally:
            os.chdir(old_cwd)


if __name__ == "__main__":
    unittest.main()
