"""PR 4 integration smoke: the plugin registers its full surface (R-9).

Task 4.4 — deployment enablement + integration smoke. Loads the project
plugin exactly like the Hermes loader does (``hermes_plugins.<slug>``
namespace package, relative ``.capture_adapter`` import) and calls
``register(ctx)`` against a RECORDING fake ``PluginContext``, then asserts
BOTH halves of the native v0.20 surface are wired:

- ``register_hook("pre_gateway_dispatch", ...)`` — the sync intake hook
  (PR 1), and
- ``register_platform(name="telegram", ...)`` — the CaptureTelegramAdapter
  override (PR 2), with the capability check and required env contract.

A real gateway process is not runnable in this harness (a live gateway owns
port 8642; see the PR 4 apply-progress runtime-boundary note), so this
recording-ctx smoke is the runtime-equivalent proof that the plugin will
register when the gateway loads it — the same ``register(ctx)`` call the
loader invokes (``hermes_cli/plugins.py:_load_plugin`` -> ``register_fn(ctx)``).

``DEMIURGOS_DATA_ROOT`` is pointed at a temp dir so registration never touches
repo data (``IdeaCaptureHandler`` default state path).
"""

import importlib.util
import sys
import tempfile
import types
from pathlib import Path
from types import SimpleNamespace

_PLUGIN_PATH = (
    Path(__file__).resolve().parents[4]
    / ".hermes" / "plugins" / "demiurgos-idea-capture" / "__init__.py"
)


class RecordingCtx:
    """Fake PluginContext recording every registration call (PR 4 smoke)."""

    def __init__(self):
        self.hooks = []
        self.platforms = []
        self.tools = []

    def register_hook(self, hook_name, callback):
        self.hooks.append((hook_name, callback))

    def register_platform(self, **kwargs):
        self.platforms.append(kwargs)

    def register_tool(self, **kwargs):
        self.tools.append(kwargs)


def _load_plugin():
    """Load the plugin the way Hermes does: ``hermes_plugins.<slug>`` package.

    Mirrors ``hermes_cli.plugins._load_directory_module``: the plugin dir
    becomes the package path so the relative import of ``.capture_adapter``
    (PR 2) resolves exactly like it does at gateway runtime.
    """
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


def test_plugin_registers_hook_and_platform(monkeypatch):
    """4.4 / R-9 / S-9.1: register() wires the hook AND the telegram override.

    Loads the plugin against the real Hermes module path and calls the exact
    ``register(ctx)`` the gateway loader invokes. Asserting with a recording
    ctx: ``pre_gateway_dispatch`` hook present (sync, not a coroutine) and
    ``telegram`` platform registered with factory + check_fn + required_env.
    """
    plugin = _load_plugin()
    with tempfile.TemporaryDirectory() as directory:
        monkeypatch.setenv("DEMIURGOS_DATA_ROOT", directory)
        monkeypatch.setenv("DEMIURGOS_IDEA_CAPTURE_MODE", "ai")
        ctx = RecordingCtx()
        plugin.register(ctx)

    # Intake hook (PR 1): registered under the v0.20 hook name, and the
    # callback is the plugin's sync wrapper (never a coroutine).
    assert ("pre_gateway_dispatch", plugin.capture_intake_hook) in ctx.hooks
    hook_cb = [cb for name, cb in ctx.hooks if name == "pre_gateway_dispatch"]
    assert len(hook_cb) == 1
    assert not __import__("asyncio").iscoroutinefunction(hook_cb[0])

    # AI-gated surface (PR idea-capture-ai-gate, R-3/R-4): the guidance hook
    # and the capture_idea tool are wired in ai mode (the default).
    assert plugin._CAPTURE_MODE == "ai"
    assert ("pre_llm_call", plugin.capture_guidance_hook) in ctx.hooks
    assert [t["name"] for t in ctx.tools] == ["capture_idea", "update_idea"]
    tool = ctx.tools[0]
    assert tool["toolset"] == "demiurgos"
    assert callable(tool["handler"])
    assert tool["schema"]["name"] == "capture_idea"
    assert set(tool["schema"]["parameters"]["properties"]) == {
        "text", "image_bytes", "audio_bytes", "mime", "confirm",
    }
    # idea-capture-confirm-queue (Opción A): confirm defaults to false and is
    # deprecated — capture_idea ALWAYS parks for user confirmation (no
    # auto-save), so the schema default must never signal auto-save.
    confirm_prop = tool["schema"]["parameters"]["properties"]["confirm"]
    assert confirm_prop["type"] == "boolean"
    assert confirm_prop["default"] is False

    # Platform override (PR 2): telegram registered with the full contract.
    assert len(ctx.platforms) == 1
    platform = ctx.platforms[0]
    assert platform["name"] == "telegram"
    assert platform["required_env"] == ["TELEGRAM_BOT_TOKEN"]
    assert callable(platform["adapter_factory"])
    assert callable(platform["check_fn"])

    # Import-level smoke of the bundled adapter subclass: the factory builds a
    # real CaptureTelegramAdapter(TelegramAdapter) instance (proves
    # capture_adapter.py imports against the real Hermes plugins path) and the
    # surface verify passed at registration (no RuntimeError raised above).
    adapter = platform["adapter_factory"](SimpleNamespace(name="telegram", extra={}))
    assert type(adapter).__name__ == "CaptureTelegramAdapter"
    assert adapter._capture_handler is plugin._handler