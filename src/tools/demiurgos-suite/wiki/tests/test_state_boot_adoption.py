# -*- coding: utf-8 -*-
"""Boot adoption — an existing ``<data root>/data`` is published before boot (2b).

Policy (ii) makes the state directory follow the adoption marker, so the order
inside ``_lifespan`` is the contract: the adoption is the FIRST statement, before
session restore, the spool sweep, skill materialization and the backup engine.
These cells drive the real lifespan with injected roots and assert that order,
the adopted bytes, the fresh-install path, and that a failed adoption still
boots.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_WIKI = _HERE.parent
for _p in (str(_WIKI),):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import api_server  # noqa: E402
import guided_session_store  # noqa: E402
import state_root_migration as srm  # noqa: E402


def _roots(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    """Point BOTH roots at throwaway directories for one boot."""
    content = tmp_path / "content"
    content.mkdir()
    state = tmp_path / "state"
    state.mkdir()
    monkeypatch.setenv("DEMIURGOS_DATA_ROOT", str(content))
    monkeypatch.setenv("DEMIURGOS_STATE_ROOT", str(state))
    monkeypatch.setattr(api_server, "STATE_DIR", None)
    monkeypatch.setattr(api_server, "PROJECT_ROOT", None)
    return content, state


def _seed_legacy(content: Path) -> Path:
    legacy = content / srm.STATE_DIR_NAME
    legacy.mkdir(parents=True)
    (legacy / "guided-sessions.sqlite3").write_bytes(b"legacy-guided-db")
    (legacy / "local-state.json").write_text(
        json.dumps({"schema_version": 1, "revision": 7}), encoding="utf-8"
    )
    (legacy / "methodology").mkdir()
    (legacy / "methodology" / "library.json").write_text("{}", encoding="utf-8")
    return legacy


def _boot(monkeypatch: pytest.MonkeyPatch) -> None:
    """Run the real lifespan once, with startup side effects neutralized."""
    monkeypatch.setattr(api_server, "_load_persisted_sessions", lambda: None)
    monkeypatch.setattr(api_server, "gc_enabled", lambda: False)
    monkeypatch.setattr(api_server, "_materialize_skills", lambda: None)
    monkeypatch.setattr(
        api_server, "_converge_assistant_acceptance", lambda: False
    )

    class _Engine:
        def start(self) -> None:
            pass

        def stop(self, timeout: float = 5) -> None:
            pass

    monkeypatch.setattr(api_server, "_backup_engine", lambda: _Engine())

    async def _run() -> None:
        async with api_server._lifespan(api_server.app):
            pass

    asyncio.run(_run())


def test_boot_adopts_a_legacy_tree_before_any_store_opens(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """S5a: an existing install boots from the adopted copy, byte-identically."""
    content, state = _roots(tmp_path, monkeypatch)
    legacy = _seed_legacy(content)

    order: list[str] = []
    real_adopt = srm.adopt_existing_state

    def _adopt(**kwargs):
        result = real_adopt(**kwargs)
        order.append("adopt")
        return result

    monkeypatch.setattr(srm, "adopt_existing_state", _adopt)
    monkeypatch.setattr(
        api_server, "_load_persisted_sessions", lambda: order.append("sessions")
    )
    monkeypatch.setattr(api_server, "gc_enabled", lambda: True)
    monkeypatch.setattr(
        api_server,
        "reap_dead_spools",
        lambda *a, **k: order.append("spool") or {},
    )
    monkeypatch.setattr(
        api_server, "_materialize_skills", lambda: order.append("skills")
    )
    monkeypatch.setattr(
        api_server, "_converge_assistant_acceptance", lambda: False
    )

    class _Engine:
        def start(self) -> None:
            order.append("engine")

        def stop(self, timeout: float = 5) -> None:
            pass

    monkeypatch.setattr(api_server, "_backup_engine", lambda: _Engine())

    async def _run() -> None:
        async with api_server._lifespan(api_server.app):
            pass

    asyncio.run(_run())

    assert order == ["adopt", "sessions", "spool", "skills", "engine"]
    adopted = state / srm.STATE_DIR_NAME
    assert (adopted / srm.COMPLETE_MARKER).is_file()
    assert (adopted / "guided-sessions.sqlite3").read_bytes() == (
        legacy / "guided-sessions.sqlite3"
    ).read_bytes()
    # The store the process will open now points at the adopted copy.
    assert guided_session_store.default_db_path() == (
        adopted / "guided-sessions.sqlite3"
    )


def test_boot_reads_the_adopted_registry_not_the_legacy_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """S5a: the first boot after an upgrade sees the migrated local state."""
    content, state = _roots(tmp_path, monkeypatch)
    legacy = _seed_legacy(content)
    monkeypatch.setattr(api_server, "_LOCAL_STATE", None)

    _boot(monkeypatch)

    assert api_server._local_state().path == (
        state / srm.STATE_DIR_NAME / "local-state.json"
    )
    assert api_server._local_state().snapshot()["revision"] == 7
    # Copy, never move: the source is left in place and untouched.
    assert (legacy / "local-state.json").is_file()


def test_a_fresh_install_creates_state_in_the_state_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """S5b: with nothing to adopt, boot leaves the state directory absent."""
    content, state = _roots(tmp_path, monkeypatch)
    (content / "data" / "methodology").mkdir(parents=True)

    _boot(monkeypatch)

    assert not (state / srm.STATE_DIR_NAME).exists()
    assert guided_session_store.default_db_path() == (
        state / srm.STATE_DIR_NAME / "guided-sessions.sqlite3"
    )


def test_a_second_boot_does_not_re_adopt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    content, state = _roots(tmp_path, monkeypatch)
    _seed_legacy(content)
    _boot(monkeypatch)
    adopted = state / srm.STATE_DIR_NAME
    before = (adopted / "guided-sessions.sqlite3").read_bytes()

    # The author deleted a world after the upgrade: the legacy tree must not be
    # copied over the live one on the next boot.
    (content / srm.STATE_DIR_NAME / "guided-sessions.sqlite3").write_bytes(b"new")
    _boot(monkeypatch)

    assert (adopted / "guided-sessions.sqlite3").read_bytes() == before


def test_a_failed_adoption_still_boots_and_keeps_the_legacy_tree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    content, state = _roots(tmp_path, monkeypatch)
    legacy = _seed_legacy(content)

    def _boom(**_kwargs):
        raise OSError("disk full (simulated)")

    monkeypatch.setattr(srm, "adopt_existing_state", _boom)

    _boot(monkeypatch)  # must not raise

    assert not (state / srm.STATE_DIR_NAME).exists()
    assert guided_session_store.default_db_path() == (
        legacy / "guided-sessions.sqlite3"
    )


def test_an_empty_content_root_writes_no_evidence_and_adopts_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Nothing to adopt: no target, no migration-evidence record.

    A missing content root is covered at the layer (``test_state_paths``); here
    the env override MUST stay set, because deleting it would let the resolver
    read the developer's real bootstrap pointer.
    """
    content, state = _roots(tmp_path, monkeypatch)
    (content / "data").mkdir()

    _boot(monkeypatch)

    assert not (state / srm.STATE_DIR_NAME).exists()
    assert not (state / srm.EVIDENCE_DIR).exists()
    assert guided_session_store.default_db_path().parent == (
        state / srm.STATE_DIR_NAME
    )
