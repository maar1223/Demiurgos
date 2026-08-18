"""ONB-1.3 — LocalState registry: BOM-safe load, version compare, atomic commit,
corrupt/partial recovery, and arc-state (``.demiurgos-estado.json``) protection.

RED-first: these tests are written against the contract before the production
code is expected to pass them.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

_WIKI = Path(__file__).resolve().parents[1]
if str(_WIKI) not in __import__("sys").path:
    __import__("sys").path.insert(0, str(_WIKI))

from local_state import (  # noqa: E402
    ARC_STATE_FILENAME,
    SCHEMA_VERSION,
    LocalState,
    LocalStateCommitError,
    default_state,
)


@pytest.fixture()
def state_file(tmp_path: Path) -> Path:
    return tmp_path / "data" / "local-state.json"


def test_load_absent_file_returns_safe_default(state_file: Path) -> None:
    state = LocalState(state_file)
    data = state.snapshot()
    assert data["schema_version"] == SCHEMA_VERSION
    assert data["revision"] == 0
    assert data["onboarding"]["completed"] is False
    assert data["onboarding"]["current_step"] == "step0"


def test_atomic_commit_writes_no_bom_and_valid_json(state_file: Path) -> None:
    state = LocalState(state_file)
    rev = state.atomic_commit({"onboarding": {"completed": True, "current_step": "ready", "completed_steps": ["step0", "world"]}})
    assert rev == 1
    raw = state_file.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf"), "committed state must be UTF-8 without BOM"
    parsed = json.loads(raw.decode("utf-8"))
    assert parsed["revision"] == 1
    assert parsed["schema_version"] == SCHEMA_VERSION
    # No temp file may remain after a successful commit.
    assert not list(state_file.parent.glob("*.tmp"))


def test_commit_bumps_revision_monotonically(state_file: Path) -> None:
    state = LocalState(state_file)
    assert state.atomic_commit({}) == 1
    assert state.atomic_commit({}) == 2
    assert LocalState(state_file).snapshot()["revision"] == 2


def test_bom_input_is_tolerated_and_stripped(state_file: Path) -> None:
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_bytes(
        b"\xef\xbb\xbf" + json.dumps(default_state(), ensure_ascii=False).encode("utf-8")
    )
    state = LocalState(state_file)
    data = state.snapshot()
    assert data["schema_version"] == SCHEMA_VERSION
    assert data["revision"] == 0


def test_corrupt_json_quarantines_and_fails_safe(state_file: Path) -> None:
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text("{ not json !!!", encoding="utf-8")
    state = LocalState(state_file)
    data = state.snapshot()
    assert data["revision"] == 0
    backups = list(state_file.parent.glob("*.corrupt.*.bak"))
    assert backups, "corrupt state must be quarantined, not silently destroyed"


def test_version_mismatch_fails_safe(state_file: Path) -> None:
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(json.dumps({"schema_version": 99, "revision": 5}), encoding="utf-8")
    state = LocalState(state_file)
    assert state.snapshot()["revision"] == 0


def test_compare_version_contract(state_file: Path) -> None:
    state = LocalState(state_file)
    state.atomic_commit({})
    assert state.compare_version(1) is True
    assert state.compare_version(2) is False
    assert state.compare_version(None) is False


def test_atomic_commit_does_not_leave_temp_file_on_failure(state_file: Path) -> None:
    # Unwritable parent (file where a dir is expected) must fail cleanly.
    blocking = state_file.parent
    blocking.parent.mkdir(parents=True, exist_ok=True)
    blocking.write_text("occupied", encoding="utf-8")
    state = LocalState(state_file)
    with pytest.raises(LocalStateCommitError):
        state.atomic_commit({})
    # Nothing was renamed into place.
    assert not state_file.exists()


def test_concurrent_commits_are_serialized_and_lose_nothing(state_file: Path) -> None:
    state = LocalState(state_file)
    results: list[int] = []
    barrier = threading.Barrier(8)

    def worker(idx: int) -> None:
        barrier.wait()
        results.append(state.atomic_commit({"worker": idx}))

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(results) == 8
    assert sorted(results) == list(range(1, 9)), "revisions must be distinct and gapless"
    final = LocalState(state_file).snapshot()
    assert final["revision"] == 8
    # The final committed payload is present and the file parses.
    parsed = json.loads(state_file.read_text(encoding="utf-8"))
    assert parsed["worker"] in range(8)


def test_arc_state_file_is_never_touched(tmp_path: Path) -> None:
    estado = tmp_path / ARC_STATE_FILENAME
    estado.write_text('{"version": 1, "arcos": {}}', encoding="utf-8")
    before = estado.read_bytes()

    state = LocalState(tmp_path / "data" / "local-state.json")
    state.atomic_commit({"onboarding": {"completed_steps": ["step0"]}})
    state.atomic_commit({})
    state.load()

    assert estado.read_bytes() == before, "arc state must never be modified"
    assert list(tmp_path.glob("data/*.json")) == [tmp_path / "data" / "local-state.json"]


def test_round_trip_preserves_payload(state_file: Path) -> None:
    state = LocalState(state_file)
    state.atomic_commit({"capabilities": {"assistant": "pending", "world": "configured"}})
    reloaded = LocalState(state_file).snapshot()
    assert reloaded["capabilities"] == {"assistant": "pending", "world": "configured"}
    assert reloaded["revision"] == 1