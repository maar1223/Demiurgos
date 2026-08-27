"""R-4 tests: the pre_llm_call guidance hook (ai mode).

The hook appends a one-shot rule to the turn context ONLY for sessions from
the authorized capture binding, so the assistant knows when to call
``capture_idea``. It runs after the gateway media pipeline, so voice
transcripts / vision descriptions are already part of the turn text.
"""

import importlib.util
import sys
import tempfile
import types
from pathlib import Path

from idea_capture.config import CaptureConfig, CaptureLimits
from idea_capture.hermes_handler import IdeaCaptureHandler
from idea_capture.runtime import IdeaCaptureRuntime
from idea_capture.telegram import IngressPolicy

_PLUGIN_PATH = (
    Path(__file__).resolve().parents[4]
    / ".hermes" / "plugins" / "demiurgos-idea-capture" / "__init__.py"
)


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


def _setup_hook(monkeypatch, *, mode="ai", chat_id="7", user_id="8"):
    plugin = _load_plugin()
    plugin._CAPTURE_MODE = mode
    monkeypatch.setenv("HERMES_SESSION_PLATFORM", "telegram")
    monkeypatch.setenv("HERMES_SESSION_CHAT_ID", chat_id)
    monkeypatch.setenv("HERMES_SESSION_USER_ID", user_id)
    monkeypatch.setenv("HERMES_SESSION_PROFILE", "default")
    return plugin


def _fire(plugin, **kwargs):
    payload = {
        "session_id": "ses-1",
        "turn_id": "turn-1",
        "user_message": "",
        "platform": "telegram",
        "sender_id": "8",
    }
    payload.update(kwargs)
    return plugin.capture_guidance_hook(**payload)


def test_ai_mode_authorized_injects_guidance(monkeypatch):
    """S-4.1: ai + authorized binding -> guidance rule appended to context."""
    with tempfile.TemporaryDirectory() as directory:
        handler, runtime = _handler(Path(directory))
        plugin = _setup_hook(monkeypatch)
        plugin._handler = handler
        try:
            result = _fire(plugin)
            assert result is not None
            assert "capture_idea" in result["context"]
            assert "ordinary conversation" in result["context"]
            # Dynamic Demiurgos language instruction (not hardcoded).
            assert "configured language" in result["context"]
        finally:
            runtime.close()


def test_non_authorized_session_gets_no_guidance(monkeypatch):
    """S-4.2: a non-authorized chat -> no guidance injected."""
    with tempfile.TemporaryDirectory() as directory:
        handler, runtime = _handler(Path(directory))
        plugin = _setup_hook(monkeypatch, chat_id="999")
        plugin._handler = handler
        try:
            assert _fire(plugin) is None
        finally:
            runtime.close()


def test_strict_mode_gets_no_guidance(monkeypatch):
    """S-4.3: strict mode -> no guidance even for the authorized binding."""
    with tempfile.TemporaryDirectory() as directory:
        handler, runtime = _handler(Path(directory))
        plugin = _setup_hook(monkeypatch, mode="strict")
        plugin._handler = handler
        try:
            assert _fire(plugin) is None
        finally:
            runtime.close()


def test_voice_turn_guidance_injected_with_transcript_in_text(monkeypatch):
    """S-4.4: a voice turn -> the turn text already carries the STT transcript.

    The hook never transcribes; the gateway media pipeline has already
    injected the transcript into the turn text before ``pre_llm_call`` fires,
    so the guidance rule is appended as-is to the enriched turn.
    """
    with tempfile.TemporaryDirectory() as directory:
        handler, runtime = _handler(Path(directory))
        plugin = _setup_hook(monkeypatch)
        plugin._handler = handler
        try:
            transcript = "el bosque susurra nombres olvidados"
            result = _fire(plugin, user_message=f"[voice] {transcript}")
            assert result is not None
            assert "capture_idea" in result["context"]
            assert "configured language" in result["context"]
        finally:
            runtime.close()


def test_guidance_is_two_way_capture_or_converse(monkeypatch):
    """Opción A: guidance is 2-way — idea -> capture_idea (always parks),
    ordinary conversation -> no tool. No confirm=true/confirm=false branches
    remain: the assistant never auto-saves, it only parks for confirmation.
    """
    with tempfile.TemporaryDirectory() as directory:
        handler, runtime = _handler(Path(directory))
        plugin = _setup_hook(monkeypatch)
        plugin._handler = handler
        try:
            result = _fire(plugin)
            context = result["context"]
            assert "capture_idea" in context
            assert "confirm=true" not in context
            assert "confirm=false" not in context
            assert "ordinary conversation" in context
            assert "without calling the tool" in context
            assert "parked" in context  # always-park semantics are explicit
        finally:
            runtime.close()


def test_update_idea_guidance_injected_for_authorized(monkeypatch):
    """R-7: the guidance context tells the model to call update_idea only after
    explicit user approval (authorized binding, ai mode)."""
    with tempfile.TemporaryDirectory() as directory:
        handler, runtime = _handler(Path(directory))
        plugin = _setup_hook(monkeypatch)
        plugin._handler = handler
        try:
            result = _fire(plugin)
            assert result is not None
            assert "update_idea" in result["context"]
            assert "explicit" in result["context"]
            assert "approval" in result["context"]
            assert "ideas_read" in result["context"]
        finally:
            runtime.close()