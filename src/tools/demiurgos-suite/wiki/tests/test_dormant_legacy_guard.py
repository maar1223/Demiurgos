# -*- coding: utf-8 -*-
"""WU-3.4 — Dormant-legacy presence invariant guard (D3 / REQ-LMP-1..3).

The legacy methodology channel (``skill_router`` + ``contract_projection``) is
kept PRESENT but DORMANT in Etapa 3: exercised only by the flag-OFF path, never
deleted and never rewired here. This guard blocks an early deletion — the
removal is a separate later change that owns the import rewire after a
>=1-release grace window (D3).

Covered scenarios (spec REQ-LMP-1/2/3):

- ``Modules present after the change`` (REQ-LMP-1): both legacy modules exist
  and import, and ``convergence_injection.py`` still imports ``_estimate_tokens``
  from ``contract_projection`` (the cross-module edge a naive deletion breaks).
- ``Guard fails if a module is removed`` (REQ-LMP-2): simulating a removed
  module makes the guard raise, blocking the early deletion.
- ``Flag-OFF behavior is byte-identical`` (REQ-LMP-3): the flag-OFF legacy
  projection stays a fully working determinism control — the existing suite is
  NOT inverted to a "deleted" expectation.
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

from contract_projection import _estimate_tokens, project_contract_markdown
from methodology_library import PublishedVersion
from methodology_trust import FOUNDATIONAL

_HERE = Path(__file__).resolve().parent
_WIKI = _HERE.parent  # wiki/ -> the module directory under test

#: The dormant legacy channel modules (D3 — preserved, never deleted here).
_LEGACY_MODULE_FILES = ("skill_router.py", "contract_projection.py")
_LEGACY_MODULE_NAMES = ("skill_router", "contract_projection")

#: The cross-module edge a deletion would break (``convergence_injection.py:16``).
_ESTIMATE_TOKENS_IMPORT = "from contract_projection import _estimate_tokens"


def _convergence_imports_estimate_tokens(text: str) -> bool:
    """Whether ``convergence_injection`` source keeps the legacy import."""
    return _ESTIMATE_TOKENS_IMPORT in text


def _legacy_presence_violations(wiki_root: Path = _WIKI) -> list[str]:
    """Return the dormant-legacy presence/import violations (empty == intact)."""
    violations: list[str] = []
    for name in _LEGACY_MODULE_FILES:
        if not (wiki_root / name).exists():
            violations.append(f"dormant legacy module missing: {name}")
    if violations:
        # A missing module is the deletion signal — do not attempt imports.
        return violations
    for name in _LEGACY_MODULE_NAMES:
        try:
            importlib.import_module(name)
        except Exception as exc:  # pragma: no cover - only on a broken tree
            violations.append(f"dormant legacy module not importable: {name}: {exc}")
    convergence_source = (wiki_root / "convergence_injection.py").read_text(
        encoding="utf-8"
    )
    if not _convergence_imports_estimate_tokens(convergence_source):
        violations.append(
            "convergence_injection.py must keep importing _estimate_tokens "
            "from contract_projection (rewire blocked)"
        )
    return violations


def _assert_dormant_legacy_intact(wiki_root: Path = _WIKI) -> None:
    """The blocking guard: raise when any dormant-legacy invariant is violated."""
    violations = _legacy_presence_violations(wiki_root)
    assert not violations, "; ".join(violations)


def _hide_module(monkeypatch: pytest.MonkeyPatch, target: Path) -> None:
    """Simulate a removed module by making ``Path.exists`` report it absent."""
    real_exists = Path.exists

    def fake_exists(self: Path) -> bool:
        if self == target:
            return False
        return real_exists(self)

    monkeypatch.setattr(Path, "exists", fake_exists)


def _published_guia() -> PublishedVersion:
    return PublishedVersion(
        skill_id="guia",
        version="1.0.0",
        name="guia",
        description="guia trigger",
        phases=("discovery",),
        language=None,
        source="# Body\n",
        digest="0" * 64,
        published_at="2026-01-01T00:00:00+00:00",
        trust_attributes=(FOUNDATIONAL,),
        adjuntos=(),
        trigger_approval=None,
    )


# -- Presence invariant (REQ-LMP-1) -------------------------------------------


def test_dormant_legacy_modules_present_and_importable():
    """Scenario 'Modules present after the change': both legacy modules exist,
    import, and the ``_estimate_tokens`` cross-module import is intact."""
    _assert_dormant_legacy_intact()
    for name in _LEGACY_MODULE_FILES:
        assert (_WIKI / name).is_file(), name
    for name in _LEGACY_MODULE_NAMES:
        assert importlib.import_module(name) is not None


def test_legacy_cross_module_import_is_live():
    """The imported symbol is bound and behaves as the legacy estimator."""
    assert callable(_estimate_tokens)
    assert _estimate_tokens("") == 0
    assert _estimate_tokens("hello world") >= 1


# -- Guard fails on an early deletion (REQ-LMP-2) -----------------------------


def test_guard_fails_when_skill_router_removed(monkeypatch):
    """Scenario 'Guard fails if a module is removed': a missing ``skill_router``
    is detected and blocks the early deletion."""
    _hide_module(monkeypatch, _WIKI / "skill_router.py")
    with pytest.raises(AssertionError, match="skill_router"):
        _assert_dormant_legacy_intact()


def test_guard_fails_when_contract_projection_removed(monkeypatch):
    """Scenario 'Guard fails if a module is removed': a missing
    ``contract_projection`` is detected and blocks the early deletion."""
    _hide_module(monkeypatch, _WIKI / "contract_projection.py")
    with pytest.raises(AssertionError, match="contract_projection"):
        _assert_dormant_legacy_intact()


def test_guard_fails_when_estimate_tokens_import_rewired(monkeypatch):
    """A rewired cross-module import (the removal change's real risk) is
    detected against the live source, blocking the early rewire."""
    convergence = _WIKI / "convergence_injection.py"
    real_read = Path.read_text

    def fake_read(self: Path, *args, **kwargs):
        text = real_read(self, *args, **kwargs)
        if self == convergence:
            return text.replace(
                _ESTIMATE_TOKENS_IMPORT,
                "from contract_projection import project_contract_markdown",
            )
        return text

    monkeypatch.setattr(Path, "read_text", fake_read)
    with pytest.raises(AssertionError, match="rewire blocked"):
        _assert_dormant_legacy_intact()


# -- Flag-OFF byte-identical control (REQ-LMP-3) ------------------------------


def test_flag_off_legacy_projection_is_byte_identical_control():
    """Scenario 'Flag-OFF behavior is byte-identical': the legacy projection
    still serves content and is a deterministic pure function — dormant, not
    deleted (no "deleted" expectation is asserted anywhere)."""
    published = _published_guia()
    first = project_contract_markdown(published).encode("utf-8")
    second = project_contract_markdown(published).encode("utf-8")
    assert first == second
    assert first  # non-empty: the legacy channel remains the served source
    # The presence invariant holds while flag OFF stays the default (D1).
    assert _legacy_presence_violations() == []
