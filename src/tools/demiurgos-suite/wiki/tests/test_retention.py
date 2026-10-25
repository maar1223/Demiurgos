# -*- coding: utf-8 -*-
"""GFS retention tests (WU-10) — hermetic selection plus failure isolation.

REQ-BE-7 with SC-BE-7.1 (only superseded daily/weekly/monthly snapshots are
selected) and SC-BE-7.2 (``current/`` and every in-policy snapshot survive).

``select_prunable`` is proven with a FIXED injected clock over a synthetic id set
spanning more than six months, so no test reads the wall clock and the policy
windows are exact. ``prune_snapshots`` is proven against the real
``FolderTransport`` for a delete failure and against a recording fake for the
listing-not-manifest rule and the non-writable skip. Standard mode: tests ship
with the code, no RED-first mandate.
"""

from __future__ import annotations

import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import pytest

_HERE = Path(__file__).resolve().parent
_WIKI = _HERE.parent
if str(_WIKI) not in sys.path:
    sys.path.insert(0, str(_WIKI))

from backup.manifest import RetentionRecord  # noqa: E402
from backup.retention import (  # noqa: E402
    MAX_CURRENT_DAY_SNAPSHOTS,
    RETENTION_META_NAME,
    STATUS_OK,
    STATUS_OK_WITH_WARNINGS,
    prune_snapshots,
    select_prunable,
)
from backup.transport.base import PruneResult, SnapshotInfo  # noqa: E402
from backup.transport.folder import FolderTransport  # noqa: E402

#: The injected fixed clock: Wednesday 2026-09-16, 12:00 UTC (ISO week 38).
_NOW = datetime(2026, 9, 16, 12, 0, 0, tzinfo=timezone.utc)


def _fixed_clock() -> datetime:
    return _NOW


# Synthetic set: one snapshot per day for 2026-09-01..16, plus one monthly anchor
# on the 20th from 2025-06 through 2026-03. It spans 16 distinct UTC days and 16
# calendar months (2025-06 .. 2026-09), i.e. more than six months.
_DAILY = [f"2026-09-{day:02d}T000000Z" for day in range(1, 17)]
_ANCHORS = (
    [f"2025-{month:02d}-20T000000Z" for month in range(6, 13)]
    + [f"2026-{month:02d}-20T000000Z" for month in range(1, 4)]
)
_ALL = _DAILY + _ANCHORS

# Hand-derived from the algorithm (see the scratch derivation in the PR body):
#   daily   = representatives of the 7 most recent days -> Sep 10..16
#   weekly  = reps of ISO weeks 38, 37, 36, 12 -> Sep 16, Sep 13, Sep 06, Mar 20
#   monthly = reps of Sep, Mar, Feb, Jan, Dec 2025, Nov 2025
#   today   = every id on 2026-09-16
_KEEP = {
    "2026-09-06T000000Z",
    "2026-09-10T000000Z",
    "2026-09-11T000000Z",
    "2026-09-12T000000Z",
    "2026-09-13T000000Z",
    "2026-09-14T000000Z",
    "2026-09-15T000000Z",
    "2026-09-16T000000Z",
    "2025-11-20T000000Z",
    "2025-12-20T000000Z",
    "2026-01-20T000000Z",
    "2026-02-20T000000Z",
    "2026-03-20T000000Z",
}
_PRUNE = {
    "2026-09-01T000000Z",
    "2026-09-02T000000Z",
    "2026-09-03T000000Z",
    "2026-09-04T000000Z",
    "2026-09-05T000000Z",
    "2026-09-07T000000Z",
    "2026-09-08T000000Z",
    "2026-09-09T000000Z",
    "2025-06-20T000000Z",
    "2025-07-20T000000Z",
    "2025-08-20T000000Z",
    "2025-09-20T000000Z",
    "2025-10-20T000000Z",
}


def _span_days(snapshot_ids: list[str]) -> int:
    parsed = sorted(
        datetime.strptime(snapshot_id, "%Y-%m-%dT%H%M%SZ")
        for snapshot_id in snapshot_ids
    )
    return (parsed[-1] - parsed[0]).days


# --- select_prunable: the pure GFS selection --------------------------------


def test_synthetic_set_spans_more_than_six_months() -> None:
    """The fixture must actually exercise the >6-month rule (REQ-BE-7)."""
    assert _span_days(_ALL) > 180


def test_gfs_selects_exactly_the_superseded_snapshots() -> None:
    """SC-BE-7.1: only snapshots outside the daily/weekly/monthly windows go."""
    selection = select_prunable(_ALL, now=_fixed_clock)
    assert set(selection.keep) == _KEEP
    assert set(selection.prune) == _PRUNE
    assert selection.unrecognized == ()
    assert set(selection.keep) | set(selection.prune) == set(_ALL)


def test_keep_set_is_never_pruned() -> None:
    """SC-BE-7.2: the keep set and the prune set are disjoint by construction."""
    selection = select_prunable(_ALL, now=_fixed_clock)
    assert set(selection.keep).isdisjoint(selection.prune)
    # The monthly representative of the 6th most recent month is kept, and the
    # one just outside it is pruned.
    assert "2025-11-20T000000Z" in selection.keep
    assert "2025-10-20T000000Z" in selection.prune
    # The representative of the last daily window day is kept; the oldest daily
    # snapshot is pruned.
    assert "2026-09-16T000000Z" in selection.keep
    assert "2026-09-01T000000Z" in selection.prune


def test_an_unparsable_id_is_never_pruned_and_is_recorded() -> None:
    """An id that cannot be classified is surfaced in ``unrecognized``, never cut."""
    weird = [
        "not-a-timestamp",
        "2026-13-40T999999Z",
        "2026-09-16T120530",
        "",
    ]
    selection = select_prunable(_ALL + weird, now=_fixed_clock)
    assert set(selection.unrecognized) == set(weird)
    assert set(selection.unrecognized).isdisjoint(selection.prune)
    assert set(selection.prune) == _PRUNE  # the weird ids changed no decision


def test_protected_ids_survive_regardless_of_age() -> None:
    """A pinned id is added to ``keep`` unconditionally, with no age test."""
    ancient = "2024-01-01T000000Z"
    ids = _ALL + [ancient]
    assert ancient in select_prunable(ids, now=_fixed_clock).prune  # would be cut
    pinned = select_prunable(ids, now=_fixed_clock, protected=[ancient])
    assert ancient in pinned.keep
    assert ancient not in pinned.prune
    assert "2024-01-01T000000Z" not in pinned.prune


def test_only_the_latest_same_day_snapshots_are_kept() -> None:
    """A same-day burst keeps the newest cap, never ALL of today.

    Regression for the disk-saturating loop: keeping every same-day snapshot
    meant a single busy session (one ~250 MB full snapshot per edit burst) could
    fill the destination with no prune until the UTC day rolled over.
    """
    today = [f"2026-09-16T{hour:02d}0000Z" for hour in range(0, 10)]
    # Enough distinct months that 2025-01 falls outside the 6-month window.
    anchors = [f"2026-{month:02d}-15T000000Z" for month in range(1, 9)]
    old = "2025-01-01T000000Z"

    selection = select_prunable(anchors + [old] + today, now=_fixed_clock)

    kept_today = sorted(set(today) & set(selection.keep))
    assert kept_today == today[-MAX_CURRENT_DAY_SNAPSHOTS:]
    assert set(today[:-MAX_CURRENT_DAY_SNAPSHOTS]) <= set(selection.prune)
    assert old in selection.prune


def test_a_protected_same_day_snapshot_survives_the_cap() -> None:
    today = [f"2026-09-16T{hour:02d}0000Z" for hour in range(0, 10)]
    pinned = today[0]

    selection = select_prunable(today, now=_fixed_clock, protected=[pinned])

    assert pinned in selection.keep
    assert len(set(today) & set(selection.keep)) == MAX_CURRENT_DAY_SNAPSHOTS + 1


def test_a_naive_clock_is_read_as_utc() -> None:
    """``now`` may be naive; the algorithm reads it as UTC, not as local time."""
    aware = select_prunable(_ALL, now=_fixed_clock)
    naive = select_prunable(
        _ALL, now=lambda: _NOW.replace(tzinfo=None)
    )
    assert naive == aware


# --- prune_snapshots: deletion, listing source and failure isolation --------


class _RecordingTransport:
    """A minimal seam double: records which verbs retention actually drove."""

    def __init__(self, snapshot_ids: list[str]) -> None:
        self._snapshot_ids = list(snapshot_ids)
        self.list_calls = 0
        self.read_meta_calls = 0
        self.prune_calls: list[tuple[str, ...]] = []
        self.writes: dict[str, Mapping[str, Any]] = {}

    def list_snapshots(self) -> list[SnapshotInfo]:
        self.list_calls += 1
        return [
            SnapshotInfo(snapshot_id, True, 0, 0)
            for snapshot_id in sorted(self._snapshot_ids)
        ]

    def read_meta(self, name: str) -> Mapping[str, Any] | None:
        self.read_meta_calls += 1
        return None

    def write_meta(self, name: str, payload: Mapping[str, Any]) -> None:
        self.writes[name] = dict(payload)

    def prune(self, snapshot_ids: Any) -> PruneResult:
        self.prune_calls.append(tuple(snapshot_ids))
        return PruneResult(deleted=tuple(snapshot_ids), failed=())


def test_candidates_come_from_the_listing_never_from_a_manifest() -> None:
    """Only ``list_snapshots()`` drives deletion; ``read_meta`` is never consulted."""
    transport = _RecordingTransport(_ALL)
    outcome = prune_snapshots(transport, now=_fixed_clock)
    assert transport.list_calls == 1
    assert transport.read_meta_calls == 0  # a disagreeing manifest cannot drive cuts
    assert len(transport.prune_calls) == 1
    assert set(transport.prune_calls[0]) == _PRUNE
    assert set(outcome.pruned) == _PRUNE
    assert outcome.status == STATUS_OK
    assert outcome.warnings == ()


def test_a_failed_delete_leaves_the_snapshot_and_records_keep_failed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A delete failure is isolated: the snapshot stays and the run degrades to ok."""
    transport = FolderTransport(tmp_path, sleep=lambda _seconds: None)
    transport.ensure_layout()
    snapshots = tmp_path / "Demiurgos" / "snapshots"
    for snapshot_id in _ALL:
        (snapshots / snapshot_id / "meta").mkdir(parents=True)
        (snapshots / snapshot_id / "entry.md").write_bytes(b"x")
    stuck = "2025-06-20T000000Z"  # a genuine prune candidate
    real_rmtree = shutil.rmtree

    def _stubborn(path: Any, *args: Any, **kwargs: Any) -> None:
        if Path(path).name == stuck:
            raise PermissionError(13, "held by a sync client", str(path))
        real_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(shutil, "rmtree", _stubborn)
    outcome = prune_snapshots(transport, now=_fixed_clock)
    assert outcome.status == STATUS_OK_WITH_WARNINGS
    assert (snapshots / stuck).is_dir()  # the snapshot STAYS on disk
    assert [snapshot_id for snapshot_id, _ in outcome.failed] == [stuck]
    assert stuck in outcome.failed[0][1]  # the error names the stuck snapshot
    assert set(outcome.pruned) == _PRUNE - {stuck}  # the rest were removed
    assert all((snapshots / snapshot_id).is_dir() for snapshot_id in _KEEP)
    assert all(
        not (snapshots / snapshot_id).exists()
        for snapshot_id in _PRUNE - {stuck}
    )
    assert any(stuck in warning for warning in outcome.warnings)
    stored = RetentionRecord.from_dict(transport.read_meta(RETENTION_META_NAME))
    assert [snapshot_id for snapshot_id, _ in stored.keep_failed] == [stuck]


def test_a_non_writable_snapshots_dir_skips_prune_with_a_warning(
    tmp_path: Path,
) -> None:
    """A non-writable ``snapshots/`` skips prune and the run still succeeds."""
    transport = FolderTransport(tmp_path, sleep=lambda _seconds: None)
    transport.ensure_layout()
    snapshots = tmp_path / "Demiurgos" / "snapshots"
    for snapshot_id in _ALL:
        (snapshots / snapshot_id).mkdir()
    outcome = prune_snapshots(
        transport, now=_fixed_clock, snapshots_writable=lambda: False
    )
    assert outcome.status == STATUS_OK_WITH_WARNINGS
    assert outcome.pruned == ()
    assert outcome.failed == ()
    assert any("not writable" in warning for warning in outcome.warnings)
    assert all((snapshots / snapshot_id).is_dir() for snapshot_id in _ALL)
    stored = RetentionRecord.from_dict(transport.read_meta(RETENTION_META_NAME))
    assert set(stored.keep) == _KEEP
    assert stored.keep_failed == ()
    assert stored.last_pruned_at is None


def test_retention_record_records_the_policy_and_protected_ids(
    tmp_path: Path,
) -> None:
    """``retention.json`` carries the policy, the keep set and every pin."""
    transport = FolderTransport(tmp_path, sleep=lambda _seconds: None)
    transport.ensure_layout()
    for snapshot_id in _ALL:
        (tmp_path / "Demiurgos" / "snapshots" / snapshot_id).mkdir()
    ancient = "2024-01-01T000000Z"
    (tmp_path / "Demiurgos" / "snapshots" / ancient).mkdir()
    outcome = prune_snapshots(
        transport, now=_fixed_clock, protected=[ancient]
    )
    stored = RetentionRecord.from_dict(transport.read_meta(RETENTION_META_NAME))
    assert stored.policy.daily == 7
    assert stored.policy.weekly == 4
    assert stored.policy.monthly == 6
    assert ancient in stored.protected
    assert ancient in stored.keep
    assert ancient not in outcome.pruned
    assert stored.last_pruned_at == "2026-09-16T12:00:00Z"
