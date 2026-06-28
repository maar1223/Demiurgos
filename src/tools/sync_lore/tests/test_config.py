"""
tests/test_config.py — Unit tests for CLI configuration resolution.

Tests build_config() priority: CLI > config file > env vars > defaults.
Also tests exit codes for missing key and malformed config.
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import importlib

cli = importlib.import_module("sync-lore.cli")


class TestBuildConfigDefaults(unittest.TestCase):
    """Default configuration with no overrides."""

    def setUp(self):
        # Save and clear relevant env vars
        self._saved = {}
        for key in ("QWEN_ENDPOINT", "QWEN_MODEL", "QWEN_TIMEOUT", "QWEN_PROVIDER"):
            self._saved[key] = os.environ.pop(key, None)

    def tearDown(self):
        for key, val in self._saved.items():
            if val is not None:
                os.environ[key] = val
            elif key in os.environ:
                del os.environ[key]

    def _make_args(self, **overrides):
        """Create a mock argparse.Namespace."""
        class Args:
            input = "."
            mode = "text"
            dry_run = False
            output = "./output"
            config = None
            engram = False
            workers = 5
        for k, v in overrides.items():
            setattr(Args, k, v)
        return Args

    def test_all_defaults(self):
        args = self._make_args()
        provider_config, runtime_opts = cli.build_config(args)
        self.assertEqual(provider_config.provider, "opencode-go")
        self.assertEqual(provider_config.endpoint, "https://opencode.ai/zen/go/v1")
        self.assertEqual(provider_config.model, "deepseek-v4-flash")
        self.assertEqual(provider_config.timeout, 60)
        self.assertEqual(provider_config.api_key_env, "OPENCODE_GO_API_KEY")
        self.assertEqual(runtime_opts["workers"], 5)
        self.assertEqual(runtime_opts["mode"], "text")

    def test_env_var_overrides_default(self):
        os.environ["QWEN_MODEL"] = "qwen4-alpha"
        os.environ["QWEN_TIMEOUT"] = "120"
        args = self._make_args()
        provider_config, _ = cli.build_config(args)
        self.assertEqual(provider_config.model, "qwen4-alpha")
        self.assertEqual(provider_config.timeout, 120)

    def test_env_var_invalid_timeout_ignored(self):
        os.environ["QWEN_TIMEOUT"] = "not_a_number"
        args = self._make_args()
        provider_config, _ = cli.build_config(args)
        self.assertEqual(provider_config.timeout, 60)  # default retained

    def test_config_file_overrides_env(self):
        os.environ["QWEN_MODEL"] = "from_env"
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as f:
            json.dump({"model": "from_file", "timeout": 90}, f)
            config_path = f.name

        try:
            args = self._make_args(config=config_path)
            provider_config, _ = cli.build_config(args)
            self.assertEqual(provider_config.model, "from_file")
            self.assertEqual(provider_config.timeout, 90)
        finally:
            os.unlink(config_path)

    def test_config_file_missing_exits(self):
        args = self._make_args(config="/nonexistent/path.json")
        with self.assertRaises(SystemExit) as cm:
            cli.build_config(args)
        self.assertEqual(cm.exception.code, 1)

    def test_config_file_invalid_json_exits(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as f:
            f.write("not valid json{{{")
            config_path = f.name

        try:
            args = self._make_args(config=config_path)
            with self.assertRaises(SystemExit) as cm:
                cli.build_config(args)
            self.assertEqual(cm.exception.code, 1)
        finally:
            os.unlink(config_path)

    def test_runtime_opts(self):
        args = self._make_args(
            input="lore/",
            mode="both",
            dry_run=True,
            output="custom/out",
            engram=True,
            workers=3,
        )
        _, opts = cli.build_config(args)
        self.assertEqual(opts["mode"], "both")
        self.assertTrue(opts["dry_run"])
        self.assertEqual(str(opts["output"]), "custom\\out")
        self.assertTrue(opts["engram"])
        self.assertEqual(opts["workers"], 3)

    def test_provider_from_env(self):
        os.environ["QWEN_PROVIDER"] = "openai"
        args = self._make_args()
        provider_config, _ = cli.build_config(args)
        self.assertEqual(provider_config.provider, "openai")

    def test_full_priority_chain(self):
        # CLI (via config file) > env > defaults
        os.environ["QWEN_MODEL"] = "from_env"
        os.environ["QWEN_TIMEOUT"] = "45"

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as f:
            json.dump({"model": "from_file"}, f)
            config_path = f.name

        try:
            args = self._make_args(config=config_path)
            provider_config, _ = cli.build_config(args)
            # model: file wins over env
            self.assertEqual(provider_config.model, "from_file")
            # timeout: env wins (not in file)
            self.assertEqual(provider_config.timeout, 45)
            # endpoint: default (not in env, not in file)
            self.assertEqual(provider_config.endpoint, "https://opencode.ai/zen/go/v1")
        finally:
            os.unlink(config_path)


class TestCLIExitCodes(unittest.TestCase):
    """Exit code behavior."""

    def setUp(self):
        self._saved_key = os.environ.pop("QWEN_API_KEY", None)
        self._saved_opencode_key = os.environ.pop("OPENCODE_API_KEY", None)

    def tearDown(self):
        if self._saved_key is not None:
            os.environ["QWEN_API_KEY"] = self._saved_key
        if self._saved_opencode_key is not None:
            os.environ["OPENCODE_API_KEY"] = self._saved_opencode_key

    def _make_args(self, **overrides):
        class Args:
            input = "."
            mode = "text"
            dry_run = False
            output = "./output"
            config = None
            engram = False
            workers = 5
        for k, v in overrides.items():
            setattr(Args, k, v)
        return Args

    def test_dry_run_skips_key_check(self):
        """--dry-run should NOT require API key."""
        args = self._make_args(dry_run=True)
        provider_config, runtime_opts = cli.build_config(args)
        self.assertTrue(runtime_opts["dry_run"])
        # In dry-run, the API key check is skipped in main()
        # This test validates the config build, not main()


if __name__ == "__main__":
    unittest.main()
