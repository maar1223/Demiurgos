# -*- coding: utf-8 -*-
"""GFS retention for the backup tree (WU-10): select, then permanently prune.

Two responsibilities, both driven by the REAL snapshot listing and never by a
manifest:

* :func:`select_prunable` is pure. It parses snapshot ids as UTC, groups them by
  UTC calendar day / ISO week / calendar month, and returns the keep set — daily
  7 / weekly 4 / monthly 6 representatives, plus ALL of the current UTC day and
  every protected id — together with the ids a prune may delete. An id that does
  not parse is NEVER pruned: it cannot be classified, so it is reported in
  ``unrecognized`` and surfaced instead of deleted.
* :func:`prune_snapshots` drives the transport. Candidates come from
  :meth:`BackupTransport.list_snapshots` (a directory listing, never a
  manifest), deletion goes through :meth:`BackupTransport.prune` — which already
  retries a locked destination with the shared 3x backoff — and every failure is
  ISOLATED: the snapshot stays, its id is recorded in
  ``retention.json.keep_failed`` with the error, and the run reports
  ``ok_with_warnings``. Failing the whole run because a sync client holds one
  handle would be the wrong trade.

**Permanent deletion is the product decision.** A plain folder has no trash, so
a pruned snapshot is gone (REQ-BE-7). This is the ONLY deletion in the system,
and ``current/`` is never a candidate.

**Hermetic by construction.** ``now`` is injected and the algorithm never reads
the system clock, so a run is deterministic under test. ``now`` may return a
naive ``datetime``, which is read as UTC. Everything is computed in UTC, so no
DST transition enters the arithmetic; the deliberate limitation is that a
"daily" snapshot is a UTC day, not a local one, so a snapshot taken late in a
local evening may fall into the next UTC day.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Sequence

from backup.manifest import (
    GFS_DAILY_7_WEEKLY_4_MONTHLY_6,
    GfsPolicy,
    RetentionRecord,
)
from backup.transport.base import BackupTransport

#: The ``meta/`` document this module owns (schema in ``backup.manifest``).
RETENTION_META_NAME = "retention.json"
#: The exact id shape ``list_snapshots()`` recognises (SC-BE-1.2).
SNAPSHOT_ID_TIME_FORMAT = "%Y-%m-%dT%H%M%SZ"
#: Run status: completed cleanly, or completed with a non-fatal prune warning.
STATUS_OK = "ok"
STATUS_OK_WITH_WARNINGS = "ok_with_warnings"


@dataclass(frozen=True)
class PruneSelection:
    """What a GFS pass keeps and what it may delete.

    ``keep`` and ``prune`` are disjoint; ``unrecognized`` holds the ids that
    could not be parsed and are therefore never pruned.
    """

    keep: tuple[str, ...]
    prune: tuple[str, ...]
    unrecognized: tuple[str, ...]


@dataclass(frozen=True)
class RetentionOutcome:
    """What one retention pass did, including the failures it isolated.

    ``status`` is ``ok`` or ``ok_with_warnings``; ``warnings`` explains every
    ``ok_with_warnings`` (a failed delete, or a skipped prune), ``failed``
    mirrors ``record.keep_failed``, and ``pruned`` names the snapshots that were
    actually removed.
    """

    record: RetentionRecord
    status: str
    warnings: tuple[str, ...]
    pruned: tuple[str, ...]
    failed: tuple[tuple[str, str], ...]


def _as_utc(moment: datetime) -> datetime:
    """*moment* in UTC; a naive value is read as UTC (never the local zone)."""
    if moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def _utc_stamp(moment: datetime) -> str:
    """*moment* as ``YYYY-MM-DDTHH:MM:SSZ`` for ``last_pruned_at``."""
    return _as_utc(moment).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_snapshot_id(snapshot_id: str) -> datetime | None:
    """The id as a UTC instant, or ``None`` when it does not parse.

    ``None`` means "cannot classify", and an unclassifiable id is never pruned.
    """
    try:
        moment = datetime.strptime(snapshot_id, SNAPSHOT_ID_TIME_FORMAT)
    except (TypeError, ValueError):
        return None
    return moment.replace(tzinfo=timezone.utc)


def _latest_by_period(
    parsed: list[tuple[str, datetime]],
    period_key: Callable[[datetime], Any],
) -> dict[Any, tuple[datetime, str]]:
    """Map each period to its representative ``(moment, id)`` — the LATEST id.

    For an elapsed period that is its last snapshot; for the current period it is
    the newest so far. Ids are compared as ``(moment, id)`` so a same-instant tie
    resolves deterministically.
    """
    latest: dict[Any, tuple[datetime, str]] = {}
    for snapshot_id, moment in parsed:
        key = period_key(moment)
        candidate = (moment, snapshot_id)
        current = latest.get(key)
        if current is None or candidate > current:
            latest[key] = candidate
    return latest


def _representatives(latest: dict[Any, tuple[datetime, str]], count: int) -> set[str]:
    """The ids of the *count* most recent periods in *latest*."""
    recent = sorted(latest, reverse=True)[:count]
    return {latest[key][1] for key in recent}


def select_prunable(
    snapshot_ids: Sequence[str],
    *,
    now: Callable[[], datetime],
    policy: GfsPolicy = GFS_DAILY_7_WEEKLY_4_MONTHLY_6,
    protected: Sequence[str] = (),
) -> PruneSelection:
    """Select the ids a GFS prune may delete, keeping every in-policy snapshot.

    ``keep`` is the union of four disjoint rules, each computed in UTC:

    1. ``daily`` — representatives of the ``policy.daily`` most recent distinct
       UTC days;
    2. ``weekly`` — representatives of the ``policy.weekly`` most recent distinct
       ISO weeks (``isocalendar()`` year + week);
    3. ``monthly`` — representatives of the ``policy.monthly`` most recent
       distinct calendar months;
    4. ``today`` — EVERY id in the current UTC day, so a same-day burst is never
       pruned mid-day.

    A representative is always the LATEST id of its period. Every ``protected``
    id that is present is added unconditionally (a manual pin, no age test), and
    an unparsable id is never pruned — it lands in ``unrecognized``.
    """
    moment = _as_utc(now())
    parsed: list[tuple[str, datetime]] = []
    unrecognized: list[str] = []
    for snapshot_id in snapshot_ids:
        parsed_moment = _parse_snapshot_id(snapshot_id)
        if parsed_moment is None:
            unrecognized.append(snapshot_id)
        else:
            parsed.append((snapshot_id, parsed_moment))

    daily = _latest_by_period(parsed, lambda value: value.date())
    weekly = _latest_by_period(parsed, lambda value: value.isocalendar()[:2])
    monthly = _latest_by_period(parsed, lambda value: (value.year, value.month))
    present = {snapshot_id for snapshot_id, _ in parsed}
    today = moment.date()

    keep = (
        _representatives(daily, policy.daily)
        | _representatives(weekly, policy.weekly)
        | _representatives(monthly, policy.monthly)
        | {
            snapshot_id
            for snapshot_id, value in parsed
            if value.date() == today
        }
        | {snapshot_id for snapshot_id in protected if snapshot_id in present}
    )
    prune = tuple(
        snapshot_id
        for snapshot_id, _ in sorted(parsed, key=lambda pair: (pair[1], pair[0]))
        if snapshot_id not in keep
    )
    return PruneSelection(
        keep=tuple(sorted(keep)),
        prune=prune,
        unrecognized=tuple(unrecognized),
    )


def prune_snapshots(
    transport: BackupTransport,
    *,
    now: Callable[[], datetime],
    policy: GfsPolicy = GFS_DAILY_7_WEEKLY_4_MONTHLY_6,
    protected: Sequence[str] = (),
    snapshots_writable: Callable[[], bool] | None = None,
    meta_name: str = RETENTION_META_NAME,
) -> RetentionOutcome:
    """Prune the policy-expired snapshots and record the whole decision.

    The candidate set comes ONLY from ``transport.list_snapshots()`` — a manifest
    is never consulted, so a leftover directory is never forgotten and a
    manifest-less directory is never invisible. Deletion goes through
    ``transport.prune`` (the shared 3x backoff lives there) and the result is
    written to ``retention.json`` so ``keep``, ``keep_failed``, ``unrecognized``
    and ``protected`` are all inspectable after the fact.

    **Failure isolation.** A failed delete leaves the snapshot in place, records
    its id and error in ``keep_failed``, and downgrades the run to
    ``ok_with_warnings`` — never ``failed``. When ``snapshots_writable()`` is
    false the prune is skipped with a warning and the run still succeeds; the
    probe is injected because the nine-verb transport contract exposes no
    writability query, and ``None`` assumes writable so a caller that does not
    probe still prunes.
    """
    moment = _as_utc(now())
    candidates = [info.snapshot_id for info in transport.list_snapshots()]
    selection = select_prunable(
        candidates, now=lambda: moment, policy=policy, protected=protected
    )

    writable = True if snapshots_writable is None else snapshots_writable()
    warnings: list[str] = []
    pruned: tuple[str, ...] = ()
    failed: tuple[tuple[str, str], ...] = ()
    last_pruned_at: str | None = None
    if selection.prune and not writable:
        warnings.append("snapshots directory is not writable; prune skipped")
    elif selection.prune:
        result = transport.prune(selection.prune)
        pruned = result.deleted
        failed = result.failed
        last_pruned_at = _utc_stamp(moment)
        warnings.extend(
            f"prune failed for {snapshot_id}: {error}"
            for snapshot_id, error in failed
        )

    record = RetentionRecord(
        policy=policy,
        keep=selection.keep,
        keep_failed=failed,
        unrecognized=selection.unrecognized,
        protected=tuple(protected),
        last_pruned_at=last_pruned_at,
    )
    transport.write_meta(meta_name, record.to_dict())
    return RetentionOutcome(
        record=record,
        status=STATUS_OK_WITH_WARNINGS if warnings else STATUS_OK,
        warnings=tuple(warnings),
        pruned=pruned,
        failed=failed,
    )
