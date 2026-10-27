# -*- coding: utf-8 -*-
"""Neutral-Spanish guard for the native idea-capture surface.

The app identity prompt is already guarded by
``src/tools/demiurgos-suite/wiki/tests/test_neutral_spanish.py``, but the
Telegram capture surface was not: the plugin's own user-facing strings
("Idea capturada ... Elegí una acción:", "Elegí el mundo", "si preferís
comandos") and the ``pre_llm_call`` guidance injected into the assistant turn
carried voseo, so the bot answered in Rioplatense Spanish
(REGLAS_LENGUAJE.md requires neutral Spanish, zero voseo).

The scan is driven by the CANONICAL blocklist
(``frontend/src/i18n/forbidden.json``) — the same source the frontend
catalogue guard and the backend identity-prompt guard consume — so a new voseo
form is caught without editing this test. A small ``_EXTRA_FORMS`` set adds the
forms that reached production but are missing from the blocklist.

This module also pins the guidance instruction that keeps the model on neutral
Spanish.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
import types
from pathlib import Path

_REPO = Path(__file__).resolve().parents[4]
_PLUGIN_DIR = _REPO / ".hermes" / "plugins" / "demiurgos-idea-capture"
_PLUGIN_PATH = _PLUGIN_DIR / "__init__.py"
_RUNTIME_PATH = _REPO / "src" / "tools" / "idea_capture" / "runtime.py"
_FORBIDDEN_PATH = _REPO / "frontend" / "src" / "i18n" / "forbidden.json"

# Forms observed in the live capture chat that the canonical blocklist lacks.
_EXTRA_FORMS = {"preferís"}


def _voseo_pattern() -> re.Pattern[str]:
    """Build the scan from the canonical blocklist (+ the extra live forms)."""
    forbidden = json.loads(_FORBIDDEN_PATH.read_text(encoding="utf-8"))
    forms = {str(form).lower() for form in forbidden["verbs"]}
    # Single-word expressions only: the multi-word ones would false-positive on
    # ordinary prose.
    forms |= {
        str(form).lower()
        for form in forbidden.get("expressions", [])
        if " " not in str(form)
    }
    for stem in forbidden["imperativeStems"]:
        for suffix in forbidden["imperativeSuffixes"]:
            forms.add(f"{stem}{suffix}".lower())
    forms |= _EXTRA_FORMS
    alternation = "|".join(
        sorted((re.escape(form) for form in forms), key=len, reverse=True)
    )
    return re.compile(rf"\b({alternation})\b", re.IGNORECASE)


_VOSEO = _voseo_pattern()


def _load_plugin():
    """Import the project plugin module exactly as Hermes does."""
    module_name = "hermes_plugins.demiurgos_idea_capture"
    if module_name in sys.modules:
        return sys.modules[module_name]
    if "hermes_plugins" not in sys.modules:
        ns_pkg = types.ModuleType("hermes_plugins")
        ns_pkg.__path__ = []
        ns_pkg.__package__ = "hermes_plugins"
        sys.modules["hermes_plugins"] = ns_pkg
    spec = importlib.util.spec_from_file_location(
        module_name, _PLUGIN_PATH, submodule_search_locations=[str(_PLUGIN_DIR)]
    )
    module = importlib.util.module_from_spec(spec)
    module.__package__ = module_name
    module.__path__ = [str(_PLUGIN_DIR)]
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def test_capture_surface_has_zero_voseo_forms() -> None:
    hits: dict[str, list[str]] = {}
    for path in (
        _PLUGIN_PATH,
        _PLUGIN_DIR / "capture_adapter.py",
        _RUNTIME_PATH,
    ):
        text = path.read_text(encoding="utf-8")
        found = sorted({match.group(0).lower() for match in _VOSEO.finditer(text)})
        if found:
            hits[str(path.relative_to(_REPO))] = found
    assert hits == {}, f"voseo reached the capture surface again: {hits}"


def test_guard_covers_the_canonical_blocklist() -> None:
    forbidden = json.loads(_FORBIDDEN_PATH.read_text(encoding="utf-8"))
    missing = [form for form in forbidden["verbs"] if not _VOSEO.search(form)]
    for stem in forbidden["imperativeStems"]:
        for suffix in forbidden["imperativeSuffixes"]:
            form = f"{stem}{suffix}"
            if not _VOSEO.search(form):
                missing.append(form)
    assert missing == [], f"guard misses canonical voseo forms: {sorted(set(missing))}"


def test_guard_catches_the_reported_removed_forms() -> None:
    for form in ("Elegí", "contame", "preferís", "Usá"):
        assert _VOSEO.search(f"texto con {form} dentro"), form


def test_guidance_context_pins_neutral_spanish(monkeypatch) -> None:
    plugin = _load_plugin()
    monkeypatch.setattr(plugin, "_demiurgos_language", lambda: "es")

    context = plugin._build_guidance_context()

    lowered = context.lower()
    assert "neutral spanish" in lowered, (
        "guidance must name the neutral Spanish register"
    )
    assert "no voseo" in lowered, "guidance must forbid voseo explicitly"
