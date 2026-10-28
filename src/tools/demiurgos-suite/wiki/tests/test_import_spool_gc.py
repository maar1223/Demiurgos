# -*- coding: utf-8 -*-
"""World importer spool GC (world-importer-spool-gc) — unit + integration tests.

Covers the dead import spool reaper:
  - R3  stale non-terminal reaping (cancel + event + cleanup + cascade delete)
  - R4  terminal-dead re-cleanup (idempotent, row kept)
  - R5  orphan purge by dir mtime
  - R6  active / leased / recent / mid-flight jobs never reaped
  - R7  configurable TTL
  - R8  enable/disable switch
  - R9  logging (job_id, state, age_days, reason)
  - R1  startup sweep (lifespan)
  - R2  lazy sweep guard + endpoint hook
  - R11 path scoping (no mundos / recycle-bin references)
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_WIKI = _HERE.parent
for _p in (str(_WIKI),):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import import_spool_gc as gc  # noqa: E402
from import_models import ImportJob, ImportJobState  # noqa: E402
from state_root_support import state_file  # noqa: E402
from import_store import ImportJobStore  # noqa: E402


class _FakePrincipal:
    def __init__(self, pid: str = "tester"):
        self.id = pid


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _iso(days_ago: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()


def _job(
    job_id: str,
    state: ImportJobState = ImportJobState.PENDING,
    *,
    updated_days_ago: float = 10,
    world: str = "demo",
    principal: str = "alice",
) -> ImportJob:
    now = datetime.now(timezone.utc)
    return ImportJob(
        job_id=job_id,
        world=world,
        owner_principal=principal,
        state=state,
        source_kind="loose",
        opaque_token=f"tok-{job_id}",
        created_at=(now - timedelta(days=updated_days_ago)).isoformat(),
        updated_at=(now - timedelta(days=updated_days_ago)).isoformat(),
    )


def _set_mtime(path: Path, days_ago: float) -> None:
    t = (datetime.now(timezone.utc) - timedelta(days=days_ago)).timestamp()
    os.utime(path, (t, t))


@pytest.fixture
def store() -> ImportJobStore:
    return ImportJobStore(":memory:")


@pytest.fixture
def spool(tmp_path: Path) -> Path:
    p = tmp_path / "spool"
    p.mkdir()
    return p


# ---------------------------------------------------------------------------
# Store query methods (tasks 1.1 / 1.2)
# ---------------------------------------------------------------------------


class TestFindStaleNonterminal:
    def test_returns_stale_review(self, store):
        store.create_job(_job("j1", ImportJobState.REVIEW, updated_days_ago=10))
        assert [j.job_id for j in store.find_stale_nonterminal(_iso(7))] == ["j1"]

    def test_excludes_leased_review(self, store):
        store.create_job(_job("j1", ImportJobState.REVIEW, updated_days_ago=10),
                         lease_owner="worker-1")
        assert store.find_stale_nonterminal(_iso(7)) == []

    def test_excludes_recent_review(self, store):
        store.create_job(_job("j1", ImportJobState.REVIEW, updated_days_ago=2))
        assert store.find_stale_nonterminal(_iso(7)) == []

    def test_includes_stale_pending(self, store):
        store.create_job(_job("j1", ImportJobState.PENDING, updated_days_ago=8))
        assert [j.job_id for j in store.find_stale_nonterminal(_iso(7))] == ["j1"]

    def test_excludes_intaking(self, store):
        store.create_job(_job("j1", ImportJobState.INTAKING, updated_days_ago=30))
        assert store.find_stale_nonterminal(_iso(7)) == []


class TestFindTerminalJobs:
    def test_returns_terminal_states(self, store):
        for i, st in enumerate((ImportJobState.CANCELLED, ImportJobState.FAILED,
                                ImportJobState.COMPLETED, ImportJobState.ROLLED_BACK)):
            store.create_job(_job(f"j{i}", st))
        assert {j.job_id for j in store.find_terminal_jobs()} == {"j0", "j1", "j2", "j3"}

    def test_excludes_non_terminal(self, store):
        for st in (ImportJobState.REVIEW, ImportJobState.PENDING, ImportJobState.APPROVED):
            store.create_job(_job(st.value, st))
        assert store.find_terminal_jobs() == []


# ---------------------------------------------------------------------------
# Config helpers (task 2.1)
# ---------------------------------------------------------------------------


class TestConfig:
    def test_defaults(self, monkeypatch):
        for k in ("IMPORT_SPOOL_GC_TTL_DAYS", "IMPORT_SPOOL_GC_ENABLED",
                  "IMPORT_SPOOL_GC_GUARD_HOURS"):
            monkeypatch.delenv(k, raising=False)
        assert gc.gc_ttl_days() == 7
        assert gc.gc_enabled() is True
        assert gc.gc_guard_hours() == 24

    def test_overrides(self, monkeypatch):
        monkeypatch.setenv("IMPORT_SPOOL_GC_TTL_DAYS", "30")
        monkeypatch.setenv("IMPORT_SPOOL_GC_ENABLED", "false")
        monkeypatch.setenv("IMPORT_SPOOL_GC_GUARD_HOURS", "1")
        assert gc.gc_ttl_days() == 30
        assert gc.gc_enabled() is False
        assert gc.gc_guard_hours() == 1


# ---------------------------------------------------------------------------
# Pass 1 — stale non-terminal reaping (R3)
# ---------------------------------------------------------------------------


class TestPass1Stale:
    def test_stale_review_reaped(self, store, spool):
        store.create_job(_job("j1", ImportJobState.REVIEW, updated_days_ago=10))
        (spool / "j1").mkdir()
        counts = gc.reap_dead_spools(store, spool, ttl_days=7)
        assert counts["stale_reaped"] == 1
        assert store.get_job("j1") is None
        assert not (spool / "j1").exists()

    def test_stale_pending_reaped(self, store, spool):
        store.create_job(_job("j1", ImportJobState.PENDING, updated_days_ago=8))
        (spool / "j1").mkdir()
        counts = gc.reap_dead_spools(store, spool, ttl_days=7)
        assert counts["stale_reaped"] == 1
        assert store.get_job("j1") is None
        assert not (spool / "j1").exists()

    def test_recent_job_not_reaped(self, store, spool):
        store.create_job(_job("j1", ImportJobState.REVIEW, updated_days_ago=2))
        (spool / "j1").mkdir()
        counts = gc.reap_dead_spools(store, spool, ttl_days=7)
        assert counts["stale_reaped"] == 0
        assert store.get_job("j1") is not None
        assert (spool / "j1").exists()


# ---------------------------------------------------------------------------
# Pass 1b — inaccessible world (R-1b): non-terminal job whose world no longer
# exists is reaped immediately (no TTL grace), because the UI cannot reach it.
# ---------------------------------------------------------------------------


def _mk_worlds(tmp_path: Path, *names: str) -> Path:
    mundos = tmp_path / "mundos"
    mundos.mkdir()
    for name in names:
        (mundos / name).mkdir()
    return mundos


class TestInaccessibleWorldReap:
    def test_young_review_for_missing_world_reaped(self, store, spool, tmp_path):
        mundos = _mk_worlds(tmp_path, "demo")
        store.create_job(_job("j1", ImportJobState.REVIEW, updated_days_ago=2,
                              world="ghost"))
        (spool / "j1").mkdir()
        counts = gc.reap_dead_spools(store, spool, ttl_days=7, mundos_dir=mundos)
        assert counts["stale_reaped"] == 1
        assert store.get_job("j1") is None
        assert not (spool / "j1").exists()

    def test_young_review_for_existing_world_not_reaped(self, store, spool, tmp_path):
        mundos = _mk_worlds(tmp_path, "demo")
        store.create_job(_job("j1", ImportJobState.REVIEW, updated_days_ago=2,
                              world="demo"))
        (spool / "j1").mkdir()
        counts = gc.reap_dead_spools(store, spool, ttl_days=7, mundos_dir=mundos)
        assert counts["stale_reaped"] == 0
        assert store.get_job("j1") is not None
        assert (spool / "j1").exists()

    def test_old_review_for_existing_world_reaped_by_age(self, store, spool, tmp_path):
        mundos = _mk_worlds(tmp_path, "demo")
        store.create_job(_job("j1", ImportJobState.REVIEW, updated_days_ago=10,
                              world="demo"))
        (spool / "j1").mkdir()
        counts = gc.reap_dead_spools(store, spool, ttl_days=7, mundos_dir=mundos)
        assert counts["stale_reaped"] == 1
        assert store.get_job("j1") is None
        assert not (spool / "j1").exists()

    def test_no_mundos_dir_falls_back_to_age_only(self, store, spool):
        # Without mundos_dir the inaccessible-world rule is off: a young job
        # for a non-existent world is NOT reaped (age-only, backward compat).
        store.create_job(_job("j1", ImportJobState.REVIEW, updated_days_ago=2,
                              world="ghost"))
        (spool / "j1").mkdir()
        counts = gc.reap_dead_spools(store, spool, ttl_days=7)
        assert counts["stale_reaped"] == 0
        assert store.get_job("j1") is not None

    def test_inaccessible_reason_logged(self, store, spool, tmp_path, caplog):
        mundos = _mk_worlds(tmp_path, "demo")
        store.create_job(_job("j1", ImportJobState.REVIEW, updated_days_ago=2,
                              world="ghost"))
        (spool / "j1").mkdir()
        with caplog.at_level(logging.INFO, logger="demiurgos-api"):
            gc.reap_dead_spools(store, spool, ttl_days=7, mundos_dir=mundos)
        assert any("reason=inaccessible_world_reaped" in r.message
                   for r in caplog.records)


# ---------------------------------------------------------------------------
# Pass 2 — terminal-dead re-cleanup (R4)
# ---------------------------------------------------------------------------


class TestPass2Terminal:
    def test_cleans_leftover_dir_keeps_row(self, store, spool):
        store.create_job(_job("j1", ImportJobState.COMPLETED, updated_days_ago=5))
        (spool / "j1").mkdir()
        counts = gc.reap_dead_spools(store, spool, ttl_days=7)
        assert counts["terminal_recleaned"] == 1
        assert store.get_job("j1") is not None
        assert not (spool / "j1").exists()

    def test_already_clean_is_noop_no_dir_recreated(self, store, spool):
        # No spool dir for the terminal job. The reaper must NOT construct
        # BoundedSpool here (its constructor would recreate the dir) — the
        # result is a no-op with no leftover empty dir.
        store.create_job(_job("j1", ImportJobState.FAILED, updated_days_ago=5))
        counts = gc.reap_dead_spools(store, spool, ttl_days=7)
        assert counts["terminal_recleaned"] == 0
        assert store.get_job("j1") is not None
        assert not (spool / "j1").exists()


# ---------------------------------------------------------------------------
# Pass 3 — orphan purge (R5)
# ---------------------------------------------------------------------------


class TestPass3Orphans:
    def test_old_orphan_deleted(self, store, spool):
        d = spool / "abc123"
        d.mkdir()
        _set_mtime(d, 10)
        counts = gc.reap_dead_spools(store, spool, ttl_days=7)
        assert counts["orphan_purged"] == 1
        assert not d.exists()

    def test_young_orphan_preserved(self, store, spool):
        d = spool / "def456"
        d.mkdir()
        _set_mtime(d, 2)
        counts = gc.reap_dead_spools(store, spool, ttl_days=7)
        assert counts["orphan_purged"] == 0
        assert d.exists()

    def test_dir_with_matching_job_row_not_orphan(self, store, spool):
        # An `approved` job is not stale-nonterminal (Pass 1) nor terminal
        # (Pass 2), so only the orphan pass could touch its dir — and it must
        # skip it because the job row exists.
        store.create_job(_job("j1", ImportJobState.APPROVED, updated_days_ago=10))
        d = spool / "j1"
        d.mkdir()
        _set_mtime(d, 10)
        counts = gc.reap_dead_spools(store, spool, ttl_days=7)
        assert counts["orphan_purged"] == 0
        assert d.exists()


# ---------------------------------------------------------------------------
# Disable switch + active jobs never harmed (R8, R6/R10)
# ---------------------------------------------------------------------------


class TestReapDeadSpools:
    def test_disabled_returns_empty_and_does_nothing(self, store, spool, monkeypatch):
        monkeypatch.setenv("IMPORT_SPOOL_GC_ENABLED", "false")
        store.create_job(_job("j1", ImportJobState.REVIEW, updated_days_ago=10))
        (spool / "j1").mkdir()
        assert gc.reap_dead_spools(store, spool, ttl_days=7) == {}
        assert store.get_job("j1") is not None
        assert (spool / "j1").exists()

    def test_leased_job_untouched(self, store, spool):
        store.create_job(_job("j1", ImportJobState.REVIEW, updated_days_ago=10),
                         lease_owner="worker-1")
        (spool / "j1").mkdir()
        counts = gc.reap_dead_spools(store, spool, ttl_days=7)
        assert counts == {"stale_reaped": 0, "terminal_recleaned": 0, "orphan_purged": 0}
        assert store.get_job("j1") is not None
        assert (spool / "j1").exists()

    def test_midflight_job_untouched(self, store, spool):
        store.create_job(_job("j1", ImportJobState.INTAKING, updated_days_ago=30))
        (spool / "j1").mkdir()
        counts = gc.reap_dead_spools(store, spool, ttl_days=7)
        assert counts["stale_reaped"] == 0
        assert store.get_job("j1") is not None
        assert (spool / "j1").exists()


# ---------------------------------------------------------------------------
# Logging (R9)
# ---------------------------------------------------------------------------


class TestLogging:
    def test_stale_reaped_logged(self, store, spool, caplog):
        store.create_job(_job("j1", ImportJobState.REVIEW, updated_days_ago=10))
        (spool / "j1").mkdir()
        with caplog.at_level(logging.INFO, logger="demiurgos-api"):
            gc.reap_dead_spools(store, spool, ttl_days=7)
        assert any(
            "job_id=j1" in r.getMessage()
            and "state=review" in r.getMessage()
            and "reason=stale_reaped" in r.getMessage()
            and "age_days=" in r.getMessage()
            for r in caplog.records
        )

    def test_orphan_purged_logged(self, store, spool, caplog):
        d = spool / "abc"
        d.mkdir()
        _set_mtime(d, 10)
        with caplog.at_level(logging.INFO, logger="demiurgos-api"):
            gc.reap_dead_spools(store, spool, ttl_days=7)
        assert any(
            "dir=abc" in r.getMessage() and "reason=orphan_purged" in r.getMessage()
            for r in caplog.records
        )


# ---------------------------------------------------------------------------
# Startup sweep (R1)
# ---------------------------------------------------------------------------


class TestStartupSweep:
    def test_lifespan_reaps_stale_job(self, tmp_path, monkeypatch):
        import api_server

        store = ImportJobStore(":memory:")
        store.create_job(_job("j1", ImportJobState.REVIEW, updated_days_ago=10))
        spool = state_file("import-spool")
        (spool / "j1").mkdir(parents=True)

        monkeypatch.setattr(api_server, "PROJECT_ROOT", tmp_path)
        monkeypatch.setattr(api_server, "_import_store", lambda: store)
        monkeypatch.setattr(api_server, "gc_enabled", lambda: True)
        monkeypatch.setattr(api_server, "gc_ttl_days", lambda: 7)
        # This cell drives one startup sweep, not the acceptance convergence:
        # the real convergence thread outlives the test and writes into the
        # NEXT test's state directory.
        monkeypatch.setattr(
            api_server, "_converge_assistant_acceptance", lambda: False
        )

        async def _run():
            async with api_server._lifespan(api_server.app):
                pass

        asyncio.run(_run())
        assert store.get_job("j1") is None
        assert not (spool / "j1").exists()

    def test_lifespan_never_crashes_on_error(self, tmp_path, monkeypatch):
        import api_server

        def _boom(*_a, **_k):
            raise RuntimeError("boom")

        monkeypatch.setattr(api_server, "PROJECT_ROOT", tmp_path)
        monkeypatch.setattr(api_server, "_import_store", lambda: None)
        monkeypatch.setattr(api_server, "gc_enabled", lambda: True)
        monkeypatch.setattr(api_server, "gc_ttl_days", lambda: 7)
        monkeypatch.setattr(api_server, "reap_dead_spools", _boom)
        # See the note above: the real convergence thread would outlive the test.
        monkeypatch.setattr(
            api_server, "_converge_assistant_acceptance", lambda: False
        )

        async def _run():
            async with api_server._lifespan(api_server.app):
                pass

        asyncio.run(_run())  # must not raise


# ---------------------------------------------------------------------------
# Lazy guard + endpoint hook (R2)
# ---------------------------------------------------------------------------


class TestLazyGuard:
    def test_second_call_within_guard_is_noop(self, monkeypatch):
        import api_server

        calls = []
        monkeypatch.setattr(api_server, "gc_enabled", lambda: True)
        monkeypatch.setattr(api_server, "gc_guard_hours", lambda: 24)
        monkeypatch.setattr(api_server, "gc_ttl_days", lambda: 7)
        monkeypatch.setattr(api_server, "_import_store", lambda: None)
        monkeypatch.setattr(api_server, "PROJECT_ROOT", Path("/tmp/none"))
        monkeypatch.setattr(
            api_server, "reap_dead_spools",
            lambda *a, **k: (calls.append(1), {})[1],
        )
        # force the first run to be allowed
        monkeypatch.setattr(
            api_server, "_last_reap_at",
            datetime.now(timezone.utc) - timedelta(hours=25),
        )
        api_server._maybe_reap_spool()
        assert len(calls) == 1
        # within the 24h guard -> no second run
        api_server._maybe_reap_spool()
        assert len(calls) == 1

    def test_runs_again_after_guard_expires(self, monkeypatch):
        import api_server

        calls = []
        monkeypatch.setattr(api_server, "gc_enabled", lambda: True)
        monkeypatch.setattr(api_server, "gc_guard_hours", lambda: 24)
        monkeypatch.setattr(api_server, "gc_ttl_days", lambda: 7)
        monkeypatch.setattr(api_server, "_import_store", lambda: None)
        monkeypatch.setattr(api_server, "PROJECT_ROOT", Path("/tmp/none"))
        monkeypatch.setattr(
            api_server, "reap_dead_spools",
            lambda *a, **k: (calls.append(1), {})[1],
        )
        monkeypatch.setattr(
            api_server, "_last_reap_at",
            datetime.now(timezone.utc) - timedelta(hours=25),
        )
        api_server._maybe_reap_spool()
        assert len(calls) == 1
        # advance the clock past the guard
        monkeypatch.setattr(
            api_server, "_last_reap_at",
            datetime.now(timezone.utc) - timedelta(hours=25),
        )
        api_server._maybe_reap_spool()
        assert len(calls) == 2

    def test_disabled_is_noop(self, monkeypatch):
        import api_server

        calls = []
        monkeypatch.setattr(api_server, "gc_enabled", lambda: False)
        monkeypatch.setattr(
            api_server, "reap_dead_spools",
            lambda *a, **k: (calls.append(1), {})[1],
        )
        api_server._maybe_reap_spool()
        assert calls == []


class TestLazyEndpoint:
    def test_on_list_called_on_list_jobs(self, tmp_path):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from import_router import create_import_router

        store = ImportJobStore(":memory:")
        spool = tmp_path / "spool"
        spool.mkdir()
        mundos = tmp_path / "mundos"
        (mundos / "world1" / "lore").mkdir(parents=True)
        calls = []

        def on_list():
            calls.append(1)

        app = FastAPI()
        app.include_router(
            create_import_router(
                require_principal=lambda request: _FakePrincipal(),
                mundos_dir=lambda: mundos,
                spool_dir=lambda: spool,
                store=store,
                on_list=on_list,
            )
        )
        client = TestClient(app)
        resp = client.get("/api/world1/imports")
        assert resp.status_code == 200
        assert calls == [1]

    def test_default_no_on_list(self, tmp_path):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from import_router import create_import_router

        store = ImportJobStore(":memory:")
        spool = tmp_path / "spool"
        spool.mkdir()
        mundos = tmp_path / "mundos"
        (mundos / "world1" / "lore").mkdir(parents=True)
        app = FastAPI()
        app.include_router(
            create_import_router(
                require_principal=lambda request: _FakePrincipal(),
                mundos_dir=lambda: mundos,
                spool_dir=lambda: spool,
                store=store,
            )
        )
        client = TestClient(app)
        assert client.get("/api/world1/imports").status_code == 200


# ---------------------------------------------------------------------------
# Path scoping (R11)
# ---------------------------------------------------------------------------


class TestPathScoping:
    def test_module_has_no_forbidden_references(self):
        src = Path(gc.__file__).read_text(encoding="utf-8")
        # Hard out-of-scope domains: the reaper must never reference the world
        # recycle bin or the papelera retention policy (separate domain).
        for forbidden in ("world_recycle_bin", "PAPELERA_RETENTION_DAYS"):
            assert forbidden not in src
        # mundos/ is READ ONLY, never written. The reaper probes world
        # existence via ``_job_world_exists`` (which only calls ``.is_dir()``)
        # and its single destructive call (``shutil.rmtree``) targets spool
        # entries — never a mundos path.
        assert "mundos_dir" in src
        assert "def _job_world_exists" in src
        assert "is_dir()" in src
        assert src.count("shutil.rmtree") == 1
