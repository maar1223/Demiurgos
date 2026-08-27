"""R-7 tests: the update_idea Hermes tool (ai mode).

The tool is registered only in ``ai`` mode and lets the assistant persist a
collaborative edit to an existing idea by delegating to
``IdeasBank.update_versioned()``. It must reject sessions that are not the
authorized capture binding before any write happens (S-7.1), and the version
number is derived from the core, never passed by the caller.
"""

import importlib.util
import json
import sys
import tempfile
import types
from pathlib import Path
from unittest.mock import MagicMock

from idea_capture.config import CaptureConfig, CaptureLimits
from idea_capture.hermes_handler import IdeaCaptureHandler
from idea_capture.runtime import IdeaCaptureRuntime
from idea_capture.telegram import IngressPolicy

_PLUGIN_PATH = (
    Path(__file__).resolve().parents[4]
    / ".hermes" / "plugins" / "demiurgos-idea-capture" / "__init__.py"
)

# Put the wiki package (IdeasBank) on the path — the plugin only adds
# ``src/tools/demiurgos-suite`` inside register(), which tests bypass.
_SUITE = Path(__file__).resolve().parents[2] / "demiurgos-suite"
if str(_SUITE) not in sys.path:
    sys.path.insert(0, str(_SUITE))


def _load_plugin():
    plugin_dir = _PLUGIN_PATH.parent
    module_name = "hermes_plugins.demiurgos_idea_capture"
    if "hermes_plugins" not in sys.modules:
        ns_pkg = types.ModuleType("hermes_plugins")
        ns_pkg.__path__ = []
        ns_pkg.__package__ = "hermes_plugins"
        sys.modules["hermes_plugins"] = ns_pkg
    spec = importlib.util.spec_from_file_location(
        module_name, _PLUGIN_PATH, submodule_search_locations=[str(plugin_dir)])
    module = importlib.util.module_from_spec(spec)
    module.__package__ = module_name
    module.__path__ = [str(plugin_dir)]
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _handler(root: Path):
    (root / "mundos" / "vibrantes").mkdir(parents=True)
    policy = IngressPolicy(
        frozenset(), {},
        authorized_bindings=frozenset({"telegram:7:8:default"}),
        require_binding=True,
    )
    runtime = IdeaCaptureRuntime(
        config=CaptureConfig(policy, CaptureLimits()),
        state_path=root / "capture.sqlite3",
        mundos_root=root / "mundos",
        active_world="vibrantes",
        global_ideas_root=root / "ideas",
    )
    handler = IdeaCaptureHandler(
        repo_root=root,
        config_path=root / "idea-capture.yaml",
        mundos_root=root / "mundos",
        runtime=runtime,
    )
    return handler, runtime


def _setup_tool(monkeypatch, *, mode="ai", chat_id="7", user_id="8",
                profile="default"):
    """Load a fresh plugin, bind the authorized handler, and stamp session env."""
    plugin = _load_plugin()
    plugin._CAPTURE_MODE = mode
    monkeypatch.setenv("HERMES_SESSION_PLATFORM", "telegram")
    monkeypatch.setenv("HERMES_SESSION_CHAT_ID", chat_id)
    monkeypatch.setenv("HERMES_SESSION_USER_ID", user_id)
    monkeypatch.setenv("HERMES_SESSION_PROFILE", profile)
    return plugin


def _call(plugin, args) -> dict:
    return json.loads(plugin._update_idea_tool(args))


def _patch_bank(monkeypatch, version=2, slug="arquero-ciego"):
    """Patch IdeasBank so update_idea delegates without touching real files."""
    import wiki.ideas_bank as ideas_bank

    bank_mock = MagicMock()
    updated = MagicMock()
    updated.version = version
    bank_mock.update_versioned.return_value = updated
    bank_mock._archive_path.return_value = Path(
        f"ideas/versions/{slug}-v{version - 1}.md"
    )
    monkeypatch.setattr(ideas_bank, "IdeasBank", lambda: bank_mock)
    return bank_mock


def test_update_idea_delegates_and_returns_new_version(monkeypatch):
    """S-7.1: authorized session -> update_versioned called, version returned."""
    with tempfile.TemporaryDirectory() as directory:
        handler, runtime = _handler(Path(directory))
        plugin = _setup_tool(monkeypatch)
        plugin._handler = handler
        bank_mock = _patch_bank(monkeypatch, version=2)
        try:
            result = _call(plugin, {"slug": "arquero-ciego", "body": "Nuevo cuerpo"})
            assert result == {
                "slug": "arquero-ciego",
                "version": 2,
                "previous_version": 1,
                "archived_at": "ideas/versions/arquero-ciego-v1.md",
            }
            bank_mock.update_versioned.assert_called_once_with(
                "arquero-ciego", {"body": "Nuevo cuerpo"}
            )
        finally:
            runtime.close()


def test_update_idea_omits_empty_fields(monkeypatch):
    """Empty/omitted fields are not forwarded to update_versioned()."""
    with tempfile.TemporaryDirectory() as directory:
        handler, runtime = _handler(Path(directory))
        plugin = _setup_tool(monkeypatch)
        plugin._handler = handler
        bank_mock = _patch_bank(monkeypatch, version=2)
        try:
            _call(plugin, {"slug": "arquero-ciego", "title": "Nuevo título",
                           "tags": [], "type": ""})
            bank_mock.update_versioned.assert_called_once_with(
                "arquero-ciego", {"title": "Nuevo título"}
            )
        finally:
            runtime.close()


def test_update_idea_rejects_unauthorized_session(monkeypatch):
    """S-7.1: non-authorized chat -> error, update_versioned NOT called."""
    with tempfile.TemporaryDirectory() as directory:
        handler, runtime = _handler(Path(directory))
        plugin = _setup_tool(monkeypatch, chat_id="999")
        plugin._handler = handler
        bank_mock = _patch_bank(monkeypatch)
        try:
            result = _call(plugin, {"slug": "arquero-ciego", "body": "x"})
            assert result == {"error": "unauthorized session"}
            bank_mock.update_versioned.assert_not_called()
        finally:
            runtime.close()


def test_update_idea_requires_slug(monkeypatch):
    """Missing slug -> error before any delegation."""
    with tempfile.TemporaryDirectory() as directory:
        handler, runtime = _handler(Path(directory))
        plugin = _setup_tool(monkeypatch)
        plugin._handler = handler
        bank_mock = _patch_bank(monkeypatch)
        try:
            result = _call(plugin, {"body": "x"})
            assert result == {"error": "slug is required"}
            bank_mock.update_versioned.assert_not_called()
        finally:
            runtime.close()


def test_update_idea_rejects_non_ai_mode(monkeypatch):
    """Guard: the tool surface exists only in ai mode (R-7 registration gate)."""
    with tempfile.TemporaryDirectory() as directory:
        handler, runtime = _handler(Path(directory))
        plugin = _setup_tool(monkeypatch, mode="strict")
        plugin._handler = handler
        bank_mock = _patch_bank(monkeypatch)
        try:
            result = _call(plugin, {"slug": "arquero-ciego", "body": "x"})
            assert result == {"error": "update_idea is only available in ai mode"}
            bank_mock.update_versioned.assert_not_called()
        finally:
            runtime.close()
