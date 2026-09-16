"""R-1 tests: DEMIURGOS_IDEA_CAPTURE_MODE resolution at registration.

The mode flag is the owner's escape hatch: ``ai`` (default) lets the
assistant decide per turn whether to capture or converse; ``strict`` restores
the pre-change unconditional capture. Resolution happens once at
``register()`` time and is cached immutably on the module.
"""

import importlib.util
import sys
import tempfile
import types
from pathlib import Path

_PLUGIN_PATH = (
    Path(__file__).resolve().parents[4]
    / ".hermes" / "plugins" / "demiurgos-idea-capture" / "__init__.py"
)


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


class RecordingCtx:
    """Fake PluginContext recording the registration surface (R-1..R-4)."""

    def __init__(self):
        self.hooks = []
        self.tools = []
        self.platforms = []

    def register_hook(self, hook_name, callback):
        self.hooks.append((hook_name, callback))

    def register_tool(self, **kwargs):
        self.tools.append(kwargs)

    def register_platform(self, **kwargs):
        self.platforms.append(kwargs)


def _register(monkeypatch, mode_env):
    plugin = _load_plugin()
    with tempfile.TemporaryDirectory() as directory:
        monkeypatch.setenv("DEMIURGOS_DATA_ROOT", directory)
        if mode_env is None:
            monkeypatch.delenv("DEMIURGOS_IDEA_CAPTURE_MODE", raising=False)
        else:
            monkeypatch.setenv("DEMIURGOS_IDEA_CAPTURE_MODE", mode_env)
        ctx = RecordingCtx()
        plugin.register(ctx)
    return plugin, ctx


def test_unset_mode_defaults_to_ai(monkeypatch):
    """S-1.1: unset env var -> the cached mode equals 'ai'."""
    plugin, ctx = _register(monkeypatch, mode_env=None)
    assert plugin._CAPTURE_MODE == "ai"
    # ai mode wires the assistant-facing surface (tool + guidance).
    assert ("pre_llm_call", plugin.capture_guidance_hook) in ctx.hooks
    assert [t["name"] for t in ctx.tools] == ["capture_idea", "update_idea"]


def test_strict_mode_resolved(monkeypatch):
    """S-1.2: DEMIURGOS_IDEA_CAPTURE_MODE=strict -> cached mode 'strict'."""
    plugin, ctx = _register(monkeypatch, mode_env="strict")
    assert plugin._CAPTURE_MODE == "strict"
    # strict mode does NOT expose the assistant-facing surface.
    assert ("pre_llm_call", plugin.capture_guidance_hook) not in ctx.hooks
    assert ctx.tools == []
    assert ("pre_gateway_dispatch", plugin.capture_intake_hook) in ctx.hooks


def test_garbage_mode_falls_back_to_ai_with_warning(monkeypatch, caplog):
    """S-1.3: garbage value -> 'ai' plus a logged warning."""
    plugin, _ = _register(monkeypatch, mode_env="garbage")
    assert plugin._CAPTURE_MODE == "ai"
    assert any(
        "DEMIURGOS_IDEA_CAPTURE_MODE" in record.message
        and "garbage" in record.message
        for record in caplog.records
    )


def test_mode_is_cached_immutably(monkeypatch):
    """R-1: the first resolution wins; later register() calls reuse it."""
    plugin, _ = _register(monkeypatch, mode_env="strict")
    assert plugin._CAPTURE_MODE == "strict"
    monkeypatch.setenv("DEMIURGOS_IDEA_CAPTURE_MODE", "ai")
    with tempfile.TemporaryDirectory() as directory:
        monkeypatch.setenv("DEMIURGOS_DATA_ROOT", directory)
        ctx = RecordingCtx()
        plugin.register(ctx)
    assert plugin._CAPTURE_MODE == "strict"  # unchanged, cached
    assert ctx.tools == []  # still no tool surface: mode did not flip