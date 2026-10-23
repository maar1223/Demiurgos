# -*- coding: utf-8 -*-
"""WU-3 — generic transversal consume seam (``_transversal_contract_for``).

Covers the WU-3 slice of ``sistema-foundational-skill`` (design decisions 1, 1b,
2, 3 and the Interfaces / Data-Flow / Fail-open tables):

- A routed **transversal** winner on the ``legacy`` channel injects its bounded
  method: the marker starts with ``[Foundational methodology:`` and carries the
  default ``project_contract_markdown`` projection (same ≤1000-token bound as
  the companion path).
- Versionless resolution goes through ``MethodologyLibrary.latest_published``
  (Decision 1b): the greatest non-deleted version for the ``skill_id``.
- Fail-open ``None`` for a non-transversal winner, ``None`` winner, a missing
  published record, an unavailable library, and any lookup exception.
- Channel symmetry (Decision 3): ``native`` / ``unhealthy`` suppress the seam;
  flag OFF (``legacy``) is active — exactly like the rest of the legacy
  projection.
- The marker leaks no digest, library file, data root, or absolute path.

The seam is a pure function of its inputs plus two module seams
(``_active_channel_state`` and ``_methodology_library``), so these tests stub
both directly instead of standing up a native-channel filesystem.
"""

from __future__ import annotations

import pytest

import api_server
from contract_projection import project_contract_markdown
from methodology_library import PublishedVersion
from methodology_trust import FOUNDATIONAL

WORLD = "W"

TRANSVERSAL_ID = "narrative-system-creation"
NON_TRANSVERSAL_ID = "narrative-draft"

_MARKER = "[Foundational methodology:"

# Same leak set the companion bridge asserts (test_api_server.py:3805-3809).
_FORBIDDEN = (
    "sha256:", "digest", "library.json", "data/methodology",
    "/mnt/", "tmp/", "CompiledMethodology",
)


def _published(
    skill_id: str,
    version: str = "1.0",
    *,
    name: str | None = None,
    description: str = "Metodología de prueba.",
    source: str = "# Body\n",
) -> PublishedVersion:
    return PublishedVersion(
        skill_id=skill_id,
        version=version,
        name=name if name is not None else skill_id,
        description=description,
        phases=("discovery",),
        language=None,
        source=source,
        digest="a" * 64,
        published_at="2026-01-01T00:00:00+00:00",
        trust_attributes=(FOUNDATIONAL,),
        adjuntos=(),
        trigger_approval=None,
    )


class _StubLibrary:
    """Minimal library seam exposing only ``latest_published`` (Decision 1b)."""

    def __init__(self, *, published=None, raises: bool = False):
        self._published = published
        self._raises = raises
        self.calls: list[str] = []

    def latest_published(self, skill_id):
        self.calls.append(skill_id)
        if self._raises:
            raise RuntimeError("boom")
        return self._published


def _wire(monkeypatch, *, state="legacy", library=None):
    """Stub the two module seams the seam reads (channel + library)."""
    monkeypatch.setattr(api_server, "_active_channel_state", lambda: state)
    monkeypatch.setattr(api_server, "_methodology_library", lambda: library)


# -- legacy + transversal winner injects bounded content ----------------------


def test_legacy_transversal_winner_injects_marker_and_projection(monkeypatch):
    record = _published(TRANSVERSAL_ID)
    library = _StubLibrary(published=record)
    _wire(monkeypatch, library=library)

    result = api_server._transversal_contract_for(TRANSVERSAL_ID, WORLD)

    assert result is not None
    assert result.startswith(_MARKER)
    # Parity with the default projection (Decision 2: default ≤1000-token bound).
    assert result == (
        f"[Foundational methodology: {record.name}]\n"
        f"{project_contract_markdown(record)}"
    )
    # The projected content — not name-only.
    assert record.description in result
    assert library.calls == [TRANSVERSAL_ID]


def test_oversized_description_respects_default_token_bound(monkeypatch):
    """The projection stays within ``max_tokens=1000`` (≈4000 chars)."""
    huge = "Sistema " * 4000  # ~28000 chars, far over budget
    record = _published(TRANSVERSAL_ID, description=huge)
    _wire(monkeypatch, library=_StubLibrary(published=record))

    result = api_server._transversal_contract_for(TRANSVERSAL_ID, WORLD)

    assert result is not None
    assert result.startswith(_MARKER)
    body = result.split("\n", 1)[1]
    assert len(body) <= 1000 * 4  # _CHARS_PER_TOKEN == 4
    # The fixed name/version header survives the shrink.
    assert f"## Methodology: {record.name}" in body


def test_name_is_clipped_to_120_chars(monkeypatch):
    record = _published(TRANSVERSAL_ID, name="N" * 500)
    _wire(monkeypatch, library=_StubLibrary(published=record))

    result = api_server._transversal_contract_for(TRANSVERSAL_ID, WORLD)

    assert result is not None
    assert result.startswith(f"[Foundational methodology: {'N' * 120}]\n")


# -- fail-open None paths -----------------------------------------------------


def test_none_for_non_transversal_winner(monkeypatch):
    library = _StubLibrary(published=_published(NON_TRANSVERSAL_ID))
    _wire(monkeypatch, library=library)

    assert api_server._transversal_contract_for(NON_TRANSVERSAL_ID, WORLD) is None
    assert library.calls == []  # never even resolved


def test_none_for_none_winner(monkeypatch):
    library = _StubLibrary(published=_published(TRANSVERSAL_ID))
    _wire(monkeypatch, library=library)

    assert api_server._transversal_contract_for(None, WORLD) is None
    assert library.calls == []


def test_none_when_published_missing(monkeypatch):
    library = _StubLibrary(published=None)
    _wire(monkeypatch, library=library)

    assert api_server._transversal_contract_for(TRANSVERSAL_ID, WORLD) is None
    assert library.calls == [TRANSVERSAL_ID]


def test_none_when_library_unavailable(monkeypatch):
    _wire(monkeypatch, library=None)

    assert api_server._transversal_contract_for(TRANSVERSAL_ID, WORLD) is None


def test_none_when_lookup_raises(monkeypatch):
    library = _StubLibrary(published=_published(TRANSVERSAL_ID), raises=True)
    _wire(monkeypatch, library=library)

    assert api_server._transversal_contract_for(TRANSVERSAL_ID, WORLD) is None


# -- channel symmetry (Decision 3) --------------------------------------------


@pytest.mark.parametrize("state", ["native", "unhealthy"])
def test_denied_channels_suppress_the_seam(monkeypatch, state):
    library = _StubLibrary(published=_published(TRANSVERSAL_ID))
    _wire(monkeypatch, state=state, library=library)

    assert api_server._transversal_contract_for(TRANSVERSAL_ID, WORLD) is None
    assert library.calls == []  # suppressed before any resolution


def test_legacy_channel_is_active(monkeypatch):
    library = _StubLibrary(published=_published(TRANSVERSAL_ID))
    _wire(monkeypatch, state="legacy", library=library)

    assert api_server._transversal_contract_for(TRANSVERSAL_ID, WORLD) is not None


# -- marker is bounded: no digest, no path ------------------------------------


def test_marker_leaks_no_digest_or_path(monkeypatch):
    # A deliberately broad digest source must never reach the marker.
    record = _published(TRANSVERSAL_ID, source="# Body\ndigest: " + "a" * 64 + "\n")
    _wire(monkeypatch, library=_StubLibrary(published=record))

    result = api_server._transversal_contract_for(TRANSVERSAL_ID, WORLD)

    assert result is not None
    assert result.startswith(_MARKER)
    for forbidden in _FORBIDDEN:
        assert forbidden not in result
