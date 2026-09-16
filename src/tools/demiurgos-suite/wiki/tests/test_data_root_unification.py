# -*- coding: utf-8 -*-
"""SC-DR-3.3: one configured data root drives the plugin, the handler and the API.

The plugin, the idea-capture handler and the wiki API each used to derive their
own root — the plugin from ``DEMIURGOS_ROOT``/``Path.cwd()``, the handler from
``__file__``, the API from its checkout. They now all resolve
``DEMIURGOS_DATA_ROOT`` (or the bootstrap pointer) through
:func:`data_root.resolve_data_root`, so one configured folder backs every
writer.

This is the ONLY automated coverage of the plugin's root derivation: it loads
the real plugin the way Hermes does and calls the real ``register(ctx)`` and
``_resolve_capture_mode``, asserting they read the configured root instead of
re-asserting the resolver.
"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

_WIKI = Path(__file__).resolve().parent.parent
if str(_WIKI) not in sys.path:
    sys.path.insert(0, str(_WIKI))

_REPO_ROOT = _WIKI.parents[3]
_TOOLS = _REPO_ROOT / "src" / "tools"
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

_PLUGIN_PATH = _REPO_ROOT / ".hermes" / "plugins" / "demiurgos-idea-capture" / "__init__.py"


class RecordingCtx:
    """Minimal PluginContext recording every registration call."""

    def __init__(self) -> None:
        self.hooks: list = []
        self.tools: list = []
        self.platforms: list = []

    def register_hook(self, hook_name, callback) -> None:
        self.hooks.append((hook_name, callback))

    def register_tool(self, **kwargs) -> None:
        self.tools.append(kwargs)

    def register_platform(self, **kwargs) -> None:
        self.platforms.append(kwargs)


def _load_plugin():
    """Load the plugin the way Hermes does: ``hermes_plugins.<slug>`` package."""
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


def _data_root_layout(root: Path, *, capture_mode: str) -> None:
    """A configured author-data root: the folders plus its idea-capture config."""
    for sub in ("config", "mundos", "ideas", "data"):
        (root / sub).mkdir(exist_ok=True)
    (root / "config" / "idea-capture.yaml").write_text(
        f"capture_mode: {capture_mode}\nauthorized_bindings: []\n", encoding="utf-8")


def test_register_derives_root_and_mode_from_the_configured_data_root(
        tmp_path: Path, monkeypatch) -> None:
    """register() + _resolve_capture_mode() read ``DEMIURGOS_DATA_ROOT``.

    The yaml says ``strict`` and no env override exists, so the resolved mode
    proves the plugin read the CONFIGURED root's ``config/`` — the checkout and
    the process cwd are never consulted after this migration.
    """
    _data_root_layout(tmp_path, capture_mode="strict")
    monkeypatch.setenv("DEMIURGOS_DATA_ROOT", str(tmp_path))
    monkeypatch.delenv("DEMIURGOS_IDEA_CAPTURE_MODE", raising=False)

    plugin = _load_plugin()
    ctx = RecordingCtx()
    plugin.register(ctx)

    assert plugin._CAPTURE_MODE == "strict"
    assert plugin._handler.repo_root == tmp_path.resolve()
    assert ("pre_gateway_dispatch", plugin.capture_intake_hook) in ctx.hooks


def test_plugin_handler_and_api_resolve_the_same_folder(tmp_path: Path,
                                                        monkeypatch) -> None:
    """SC-DR-3.3: one ``DEMIURGOS_DATA_ROOT`` -> one folder for every writer."""
    _data_root_layout(tmp_path, capture_mode="ai")
    monkeypatch.setenv("DEMIURGOS_DATA_ROOT", str(tmp_path))
    resolved = tmp_path.resolve()

    plugin = _load_plugin()
    plugin.register(RecordingCtx())
    assert plugin._handler.repo_root == resolved

    from idea_capture.hermes_handler import (
        _default_locale_state_path,
        _default_vision_cache_db_path,
    )
    from import_store import default_db_path
    import api_server

    # Handler: locale registry and the shared vision cache live under the root.
    assert _default_locale_state_path() == resolved / "data" / "local-state.json"
    assert _default_vision_cache_db_path() == resolved / "data" / "import-jobs.sqlite3"
    # API: the wiki import store backs its vision cache with the SAME database.
    assert default_db_path() == _default_vision_cache_db_path()
    # API: the app derives its author-data paths from the same root. Reset the
    # cached seam so this test's environment is the one it resolves.
    monkeypatch.setattr(api_server, "PROJECT_ROOT", None, raising=True)
    assert api_server._project_root() == resolved
