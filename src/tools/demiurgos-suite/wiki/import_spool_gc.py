"""Dead import spool reaper (world-importer-spool-gc).

Reclaims abandoned data under ``data/import-spool/`` across three passes:

  1. Stale non-terminal jobs (``pending``/``review``, no lease, ``updated_at``
     older than TTL) are transitioned to ``cancelled`` (event
     ``stale_reaped``), their spool dir is cleaned, and the job row is
     cascade-deleted.
  2. Terminal-dead jobs (``cancelled``/``failed``/``completed``/``rolled_back``)
     whose spool dir still exists on disk are re-cleaned (the job row is kept).
  3. Orphan spool dirs with no matching job row and an mtime older than TTL
     are purged.

It operates exclusively on ``data/import-spool/`` and the import jobs store.
It never touches the world recycle bin, the papelera retention policy, world
source directories, or user source files, and it never modifies the
user-facing ``delete_job`` guard — it bypasses that guard via the store's
cascade delete.

Config (env): ``IMPORT_SPOOL_GC_TTL_DAYS`` (default 7),
``IMPORT_SPOOL_GC_ENABLED`` (default true), ``IMPORT_SPOOL_GC_GUARD_HOURS``
(default 24).
"""

from __future__ import annotations

import logging
import os
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

from import_intake import BoundedSpool
from import_models import ImportJobState
from import_store import ImportJobStore

logger = logging.getLogger("demiurgos-api")


def gc_ttl_days() -> int:
    """Reaper TTL in days; ``IMPORT_SPOOL_GC_TTL_DAYS`` (default 7)."""
    return int(os.getenv("IMPORT_SPOOL_GC_TTL_DAYS", "7"))


def gc_enabled() -> bool:
    """Reaper master switch; ``IMPORT_SPOOL_GC_ENABLED`` (default enabled)."""
    return os.getenv("IMPORT_SPOOL_GC_ENABLED", "true").strip().lower() not in (
        "false", "0", "")


def gc_guard_hours() -> int:
    """Lazy sweep guard interval in hours; ``IMPORT_SPOOL_GC_GUARD_HOURS`` (default 24)."""
    return int(os.getenv("IMPORT_SPOOL_GC_GUARD_HOURS", "24"))


def _age_days(iso: str, now: datetime) -> float | None:
    """Days between an ISO-8601 ``updated_at`` and *now* (or None if unparseable)."""
    try:
        ts = datetime.fromisoformat(iso)
    except (TypeError, ValueError):
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return (now - ts).total_seconds() / 86400.0


def _reap_stale_nonterminal(
    store: ImportJobStore,
    spool_dir: Path,
    cutoff_iso: str,
    *,
    now: datetime,
    log: logging.Logger,
) -> int:
    """Pass 1 — cancel + cleanup + cascade-delete stale non-terminal jobs."""
    count = 0
    for job in store.find_stale_nonterminal(cutoff_iso):
        try:
            # Audit trail first, then the guarded terminal transition. The
            # event is recorded before the mutation so it survives even if a
            # later step fails.
            store.add_event(job.job_id, "stale_reaped")
            store.update_job(
                job.job_id,
                expected_revision=job.revision,
                state=ImportJobState.CANCELLED,
            )
        except ValueError:
            # A concurrent mutation bumped the revision between our query and
            # this write — this is no longer the stale snapshot we examined,
            # so leave it alone rather than clobber a live transition.
            log.warning(
                "spool_gc: skipped stale job %s (revision changed concurrently)",
                job.job_id,
            )
            continue
        BoundedSpool(spool_dir, job.job_id, job.world).cleanup()
        store.delete_job(job.job_id)
        count += 1
        log.info(
            "spool_gc: job_id=%s state=%s age_days=%s reason=stale_reaped",
            job.job_id, job.state.value, _age_days(job.updated_at, now),
        )
    return count


def _reap_terminal_dead(
    store: ImportJobStore,
    spool_dir: Path,
    *,
    now: datetime,
    log: logging.Logger,
) -> int:
    """Pass 2 — re-clean leftover spool dirs of terminal jobs (row kept)."""
    count = 0
    for job in store.find_terminal_jobs():
        # Check the dir BEFORE constructing BoundedSpool: its constructor
        # recreates the job dir (``mkdir(parents=True, exist_ok=True)``), which
        # would re-materialize an empty dir for an already-cleaned job. Only
        # construct when the dir actually exists.
        if not Path(spool_dir, job.job_id).is_dir():
            continue
        BoundedSpool(spool_dir, job.job_id, job.world).cleanup()
        count += 1
        log.info(
            "spool_gc: job_id=%s state=%s age_days=%s reason=terminal_recleanup",
            job.job_id, job.state.value, _age_days(job.updated_at, now),
        )
    return count


def _reap_orphans(
    store: ImportJobStore,
    spool_dir: Path,
    ttl_seconds: float,
    *,
    now: datetime,
    log: logging.Logger,
) -> int:
    """Pass 3 — purge spool dirs with no job row and mtime older than TTL."""
    count = 0
    if not spool_dir.is_dir():
        return 0
    now_ts = now.timestamp()
    for entry in spool_dir.iterdir():
        if not entry.is_dir():
            continue
        if store.get_job(entry.name) is not None:
            continue  # a job row owns it — handled by Pass 1/2
        try:
            mtime = entry.stat().st_mtime
        except OSError:
            continue  # raced away; skip
        if (now_ts - mtime) <= ttl_seconds:
            continue  # younger than TTL — preserved
        try:
            shutil.rmtree(entry)
        except FileNotFoundError:
            continue  # removed between iterdir and rmtree
        count += 1
        log.info(
            "spool_gc: dir=%s age_days=%.2f reason=orphan_purged",
            entry.name, (now_ts - mtime) / 86400.0,
        )
    return count


def reap_dead_spools(
    store: ImportJobStore,
    spool_dir: Path,
    ttl_days: int = 7,
    *,
    logger: logging.Logger | None = None,
) -> dict[str, int]:
    """Run all three reaper passes. Returns counts per reason.

    Early-returns ``{}`` (no-op) when ``gc_enabled()`` is False.
    """
    if not gc_enabled():
        return {}
    log = logger if logger is not None else logging.getLogger("demiurgos-api")
    now = datetime.now(timezone.utc)
    cutoff_iso = (now - timedelta(days=ttl_days)).isoformat()
    spool = Path(spool_dir)
    return {
        "stale_reaped": _reap_stale_nonterminal(
            store, spool, cutoff_iso, now=now, log=log),
        "terminal_recleaned": _reap_terminal_dead(
            store, spool, now=now, log=log),
        "orphan_purged": _reap_orphans(
            store, spool, ttl_days * 86400.0, now=now, log=log),
    }
