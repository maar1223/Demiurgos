# -*- coding: utf-8 -*-
"""Honest-delivery copy gate tests (WU-12, task 12.8).

Covers REQ-SF-4 / SC-SF-4.1 and the testable half of SC-SF-4.2: the status/copy
payload builder exposes no upload/sync/cloud field, and the forbidden
cloud-delivery vocabulary (es-ES AND en) is rejected from copy strings.

**Scope honesty — half of SC-SF-4.2 is deferred on purpose.** SC-SF-4.2 also
requires scanning the LIVE ``/api/backup/status`` response. That route is WU-14's
router and does not exist yet, so it cannot be asserted here and is NOT faked.
What IS proved now: the vocabulary constants, :func:`assert_honest_copy`,
:func:`find_dishonest_status_keys`, the local-write builder WU-14 will consume,
and the candidate persistence record. The deferred half is the router slice.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_WIKI = _HERE.parent
if str(_WIKI) not in sys.path:
    sys.path.insert(0, str(_WIKI))

from backup.sync_folder import (  # noqa: E402
    FORBIDDEN_DELIVERY_VOCABULARY,
    DishonestCopyError,
    assert_honest_copy,
    build_local_write_status,
    find_dishonest_status_keys,
    find_forbidden_vocabulary,
    local_write_copy,
    manual_candidate,
)

SPANISH_DELIVERY_CLAIMS = (
    "respaldado en la nube",
    "respaldado en Drive",
    "sincronizado con la nube",
    "subido a Drive",
)
ENGLISH_DELIVERY_CLAIMS = (
    "backed up to Drive",
    "synced to the cloud",
    "uploaded to",
)


def test_vocabulary_covers_spanish_and_english() -> None:
    for phrase in SPANISH_DELIVERY_CLAIMS + ENGLISH_DELIVERY_CLAIMS:
        assert phrase in FORBIDDEN_DELIVERY_VOCABULARY
        assert phrase in find_forbidden_vocabulary(phrase)


def test_local_write_copy_is_honest_in_both_languages() -> None:
    english = local_write_copy("/mnt/sync", written_at="2026-09-16T12:00:00Z")
    spanish = local_write_copy(
        "/mnt/sync", written_at="2026-09-16T12:00:00Z", language="es"
    )
    assert english == "Written to /mnt/sync — 2026-09-16T12:00:00Z UTC"
    assert spanish == "Escrito en /mnt/sync — 2026-09-16T12:00:00Z UTC"
    assert_honest_copy(english)
    assert_honest_copy(spanish)


@pytest.mark.parametrize(
    "claim", SPANISH_DELIVERY_CLAIMS + ENGLISH_DELIVERY_CLAIMS
)
def test_forbidden_copy_raises(claim: str) -> None:
    with pytest.raises(DishonestCopyError):
        assert_honest_copy(f"Backup status: {claim}")


def test_local_write_status_payload_is_closed() -> None:
    payload = build_local_write_status(
        destination="/mnt/sync",
        written_at="2026-09-16T12:00:00Z",
        status="ok",
        current_entries=42,
    )
    assert payload == {
        "destination": "/mnt/sync",
        "written_at": "2026-09-16T12:00:00Z",
        "status": "ok",
        "current_entries": 42,
    }
    assert find_dishonest_status_keys(payload) == ()


def test_candidate_and_status_payload_have_no_delivery_key() -> None:
    """The record WU-14 will serialise carries local-write fields only."""
    candidate = manual_candidate("/mnt/sync")
    payload = {
        **candidate.to_dict(),
        **build_local_write_status(
            destination=candidate.path,
            written_at="2026-09-16T12:00:00Z",
            status="ok",
            current_entries=1,
        ),
    }
    assert find_dishonest_status_keys(payload) == ()
    assert_honest_copy(local_write_copy(candidate.path))


def test_dishonest_status_keys_are_detected_recursively() -> None:
    payload = {
        "destination": "/mnt/sync",
        "nested": {"upload_state": "pending", "items": [{"cloud_provider": "x"}]},
        "sync_state": "done",
    }
    found = find_dishonest_status_keys(payload)
    assert set(found) == {"upload_state", "cloud_provider", "sync_state"}


def test_live_route_half_of_sc_sf_4_2_is_deferred() -> None:
    """Documents the deferral so a reader cannot mistake this for full coverage.

    The router that serves ``/api/backup/status`` is WU-14. Until it exists the
    only honest assertion is on the shared builder, which this suite proves
    closed. This test exists to make that boundary explicit rather than implied.
    """
    payload = build_local_write_status(
        destination="/mnt/sync",
        written_at="2026-09-16T12:00:00Z",
        status="ok",
        current_entries=1,
    )
    assert {"upload", "cloud", "sync_state"}.isdisjoint(
        {str(key).casefold() for key in payload}
    )
