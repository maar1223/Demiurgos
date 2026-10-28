# -*- coding: utf-8 -*-
"""A backup destination that overlaps the content root is refused (step 3).

The snapshot inventory walks the content root and INCLUDES every top-level
folder it does not recognise — deliberately, so nothing of the author's is ever
dropped silently. The backup's own layout (``current/``, ``snapshots/``,
``meta/``, ``world-trash-index/``) is exactly such a folder. So a destination
that IS the content root, or lives inside it, makes every run carry the previous
one, and ``current/`` copy itself on each pass: growth without a ceiling.

A destination that CONTAINS the content root is refused for the mirror reason:
the run would write its bookkeeping into the user's own folder and a restore
could swap members around the author's content.

Since step 3 the default content root is ``<documents>/Demiurgos`` — the folder
a user naturally picks for backups — so this overlap is reachable by default and
must be refused rather than merely documented.

A backup stored inside the thing it backs up is also one copy and one failure:
deleting the content folder deletes the backup with it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backup import runner as backup_runner
from backup.router import create_backup_router
from backup.state import (
    BackupDestination,
    BackupStateError,
    read_destination,
    write_destination,
)
from backup.transport.base import TargetCapabilities
from backup.sync_folder import TargetDecision

RECORD = {
    "schema_version": 1,
    "provider": "folder",
    "source": "user",
    "confidence": "heuristic",
    "mode_hint": "mirrored",
    "updated_at": "2026-10-26T02:07:51Z",
}


def _root(tmp_path: Path) -> Path:
    """A content root shaped like the real one."""
    root = tmp_path / "content-root"
    for sub in ("mundos", "ideas", "data", "config"):
        (root / sub).mkdir(parents=True, exist_ok=True)
    (root / "mundos" / "Avalor" / "lore").mkdir(parents=True, exist_ok=True)
    (root / "mundos" / "Avalor" / "lore" / "inicio.md").write_text(
        "# Inicio\n", encoding="utf-8"
    )
    return root


def _destination(path: Path) -> BackupDestination:
    return BackupDestination(
        path=str(path),
        provider="folder",
        source="user",
        confidence="heuristic",
        mode_hint="mirrored",
    )


def _seed_record(root: Path, destination: Path) -> None:
    """Write the record the way a run reads it, bypassing the guard on purpose.

    A config written before this guard existed (or hand-edited) must not be able
    to reach the writer: the run checks the pair again.
    """
    record = {**RECORD, "path": str(destination)}
    target = root / "config" / "backup.json"
    target.write_text(json.dumps(record, indent=2), encoding="utf-8")


def _accepting(path: Path) -> TargetDecision:
    return TargetDecision(
        True,
        TargetCapabilities(
            kind="folder",
            path=str(path),
            writable=True,
            same_volume_as_data_root=True,
            mode_hint="mirrored",
        ),
    )


# ---------------------------------------------------------------------------
# The state layer refuses every overlap shape
# ---------------------------------------------------------------------------


def test_the_content_root_itself_is_refused(tmp_path: Path) -> None:
    root = _root(tmp_path)
    with pytest.raises(BackupStateError) as failure:
        write_destination(root, _destination(root))
    assert "content root" in str(failure.value)
    assert read_destination(root) is None


def test_a_folder_inside_the_content_root_is_refused(tmp_path: Path) -> None:
    root = _root(tmp_path)
    (root / "Backups").mkdir()
    with pytest.raises(BackupStateError) as failure:
        write_destination(root, _destination(root / "Backups"))
    assert "content root" in str(failure.value)
    assert read_destination(root) is None


def test_a_folder_that_contains_the_content_root_is_refused(tmp_path: Path) -> None:
    root = _root(tmp_path)
    with pytest.raises(BackupStateError) as failure:
        write_destination(root, _destination(tmp_path))
    assert "content root" in str(failure.value)
    assert read_destination(root) is None


def test_a_sibling_folder_is_still_accepted(tmp_path: Path) -> None:
    """The pin for the behaviour this guard must NOT change."""
    root = _root(tmp_path)
    destination = tmp_path / "sync-folder"
    destination.mkdir()
    record = write_destination(root, _destination(destination))
    assert record.path == str(destination)
    assert read_destination(root) is not None


def test_the_guard_reads_through_symlinks(tmp_path: Path) -> None:
    """A link that points into the content root is the same folder."""
    root = _root(tmp_path)
    alias = tmp_path / "alias"
    alias.symlink_to(root / "Backups" if (root / "Backups").exists() else root)
    with pytest.raises(BackupStateError):
        write_destination(root, _destination(alias))


# ---------------------------------------------------------------------------
# The run refuses a record the writer would no longer accept
# ---------------------------------------------------------------------------


def test_a_persisted_overlap_never_publishes_into_the_content_root(
    tmp_path: Path,
) -> None:
    root = _root(tmp_path)
    before = sorted(p.name for p in root.iterdir())
    _seed_record(root, root)

    outcome = backup_runner.run_backup(
        data_root=root, evaluate=_accepting
    )

    assert outcome.refused is True
    assert outcome.status == backup_runner.STATUS_FAILED
    assert "content root" in (outcome.error or "")
    assert outcome.remedy
    # Nothing was published: no meta/, snapshots/, current/ or trash index.
    assert sorted(p.name for p in root.iterdir()) == before


def test_a_persisted_enclosing_folder_never_publishes(tmp_path: Path) -> None:
    root = _root(tmp_path)
    _seed_record(root, tmp_path)
    before = sorted(p.name for p in tmp_path.iterdir())

    outcome = backup_runner.run_backup(data_root=root, evaluate=_accepting)

    assert outcome.refused is True
    assert sorted(p.name for p in tmp_path.iterdir()) == before


# ---------------------------------------------------------------------------
# The API refuses it too, with a readable reason
# ---------------------------------------------------------------------------


def _client(root: Path) -> TestClient:
    app = FastAPI()
    app.include_router(
        create_backup_router(
            lambda request=None: "tester",
            data_root=root,
            evaluate=_accepting,
        )
    )
    return TestClient(app)


@pytest.mark.parametrize("shape", ["itself", "inside", "enclosing"])
def test_the_api_rejects_an_overlapping_folder(tmp_path: Path, shape: str) -> None:
    root = _root(tmp_path)
    if shape == "itself":
        chosen = root
    elif shape == "inside":
        (root / "Backups").mkdir()
        chosen = root / "Backups"
    else:
        chosen = tmp_path

    response = _client(root).post(
        "/api/backup/destination", json={"path": str(chosen)}
    )

    assert response.status_code == 400, response.text
    assert "content root" in response.json()["detail"]
    assert read_destination(root) is None


def test_the_api_still_accepts_a_sibling_folder(tmp_path: Path) -> None:
    root = _root(tmp_path)
    destination = tmp_path / "sync-folder"
    destination.mkdir()
    response = _client(root).post(
        "/api/backup/destination", json={"path": str(destination)}
    )
    assert response.status_code == 200, response.text
    record = read_destination(root)
    assert record is not None and record.path == str(destination)
