# -*- coding: utf-8 -*-
"""Regression cells for the content-move production wiring (step 5).

These exist because the first implementation passed its own tests and was still
broken in the shipped app:

* the router built a NEW ``ContentMoveService`` per request, so a job id was
  unreadable to the next request (progress and cancel answered 404) and two
  moves could run at once;
* a cancel that arrived while hashing still published the pointer;
* the record went through ``resolve_state_dir()``, which policy (ii) can answer
  with ``<content root>/data`` — the record then modified the source of the very
  move it described and vanished with it;
* a world could be created between the move and the restart, landing in the OLD
  root where the next start would not look for it.

Every cell here fails against that implementation.
"""

from __future__ import annotations

import hashlib
import threading
import time
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import content_mover
import data_root as resolver
from content_mover import MoveOutcome, execute_move, plan_move
from content_move_service import MoveJob
from content_move_service import ContentMoveService
from content_root_router import create_content_root_router

RECORD_NAME = "content-move-last.json"


def _content_root(tmp_path: Path, *, legacy_state: bool = False) -> Path:
    root = tmp_path / "content"
    (root / "mundos" / "W" / "lore").mkdir(parents=True)
    (root / "mundos" / "W" / "lore" / "a.md").write_text("# A\n", encoding="utf-8")
    (root / "ideas").mkdir()
    (root / "ideas" / "i.md").write_text("# I\n", encoding="utf-8")
    (root / "plantillas").mkdir()
    (root / "plantillas" / "p.md").write_text("p\n", encoding="utf-8")
    (root / "config").mkdir()
    (root / "config" / "backup.json").write_text("{}\n", encoding="utf-8")
    (root / "data" / "methodology").mkdir(parents=True)
    (root / "data" / "methodology" / "l.json").write_text("{}", encoding="utf-8")
    (root / ".env").write_text("DEMIURGOS_AUTH_MODE=local-dev\n", encoding="utf-8")
    if legacy_state:
        (root / "data" / "idea-capture.sqlite3").write_bytes(b"SQLite format 3\x00")
    return root


def _hashes(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file() and not path.is_symlink()
    }


def _production_client(
    tmp_path: Path, root, *, env: dict[str, str] | None = None
) -> TestClient:
    """The router wired exactly as ``api_server.py`` does: no injected service."""
    app = FastAPI()
    app.include_router(
        create_content_root_router(
            lambda request=None: "tester",
            env={} if env is None else env,
            config_dir=tmp_path / "cfg",
            state_dir=tmp_path / "state",
            current_root=(root if callable(root) else (lambda: root)),
        )
    )
    return TestClient(app)


# ---------------------------------------------------------------------------
# S7 — one job, visible to the next request and exclusive
# ---------------------------------------------------------------------------


def test_the_production_router_keeps_one_visible_and_exclusive_job(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _content_root(tmp_path)
    one = tmp_path / "one"
    one.mkdir()
    two = tmp_path / "two"
    two.mkdir()
    release = threading.Event()

    def blocked(plan, **kwargs):
        release.wait(5)
        return MoveOutcome(
            copied_files=plan.total_files, copied_bytes=plan.total_bytes
        )

    monkeypatch.setattr(content_mover, "execute_move", blocked)
    client = _production_client(tmp_path, root)
    try:
        first = client.post("/api/data-root/move-content", json={"target": str(one)})
        assert first.status_code == 202, first.text
        job_id = first.json()["job"]["id"]
        assert client.get(f"/api/data-root/move-content/{job_id}").status_code == 200
        second = client.post("/api/data-root/move-content", json={"target": str(two)})
        assert second.status_code == 409, second.text
    finally:
        release.set()


# ---------------------------------------------------------------------------
# S3 — a cancel that arrives while hashing publishes nothing
# ---------------------------------------------------------------------------


def test_cancel_during_verification_publishes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _content_root(tmp_path)
    target = tmp_path / "target"
    target.mkdir()
    published: list[Path] = []
    flag = {"cancel": False}
    real = content_mover._fingerprint

    def fingerprint(path, entries):
        result = real(path, entries)
        if Path(path) == root.resolve():
            flag["cancel"] = True
        return result

    monkeypatch.setattr(content_mover, "_fingerprint", fingerprint)

    outcome = execute_move(
        plan_move(root, target),
        publish=published.append,
        should_cancel=lambda: flag["cancel"],
    )

    assert outcome.cancelled is True
    assert published == []
    assert list(target.iterdir()) == []


# ---------------------------------------------------------------------------
# S5/S7/S9 — the record lives outside the content root and survives a restart
# ---------------------------------------------------------------------------


def test_the_record_never_lands_in_the_content_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _content_root(tmp_path, legacy_state=True)
    target = tmp_path / "target"
    target.mkdir()
    config = tmp_path / "cfg"
    resolver.write_pointer(root, config_dir=config)
    env = {"DEMIURGOS_DATA_ROOT": str(root)}
    monkeypatch.setattr(
        content_mover,
        "_default_publish",
        lambda chosen: resolver.write_pointer(chosen, config_dir=config),
    )
    before = _hashes(root)

    client = _production_client(tmp_path, root, env=env)
    started = client.post("/api/data-root/move-content", json={"target": str(target)})
    assert started.status_code == 202, started.text

    deadline = time.time() + 10
    while time.time() < deadline:
        if (target / "mundos").exists():
            break
        time.sleep(0.02)
    time.sleep(0.15)

    assert not any(root.rglob(RECORD_NAME)), "the record landed in the source"
    assert _hashes(root) == before

    restarted = _production_client(
        tmp_path, target, env={"DEMIURGOS_DATA_ROOT": str(target)}
    )
    last = restarted.get("/api/data-root/last-move")
    assert last.status_code == 200
    assert last.json()["last_move"] is not None


def test_a_failed_move_does_not_erase_a_good_record(tmp_path: Path) -> None:
    """The record authorises a delete: losing it leaves two full trees."""
    published: list[Path] = []
    service = ContentMoveService(
        record_dir=tmp_path / "state" / "move", publish=published.append, run_inline=True
    )
    good_source = _content_root(tmp_path)
    good_target = tmp_path / "good"
    good_target.mkdir()
    service.start(source=good_source, target=good_target, forbidden=[])
    assert service.last_move()["state"] == "done"

    bad_source = _content_root(tmp_path / "otro")
    bad_target = tmp_path / "bad"
    bad_target.mkdir()
    (bad_target / "algo").write_text("x", encoding="utf-8")
    with pytest.raises(content_mover.MoveError):
        service.start(source=bad_source, target=bad_target, forbidden=[])

    record = service.last_move()
    assert record is not None
    assert record["state"] == "done"
    assert record["source"] == str(good_source.resolve())


def test_cleanup_refuses_when_the_pointer_moved_again(tmp_path: Path) -> None:
    """A third folder in the pointer means the record no longer describes reality."""
    published: list[Path] = []
    pointer = {"path": None}
    service = ContentMoveService(
        record_dir=tmp_path / "state" / "move",
        publish=published.append,
        pointer=lambda: pointer["path"],
        run_inline=True,
    )
    source = _content_root(tmp_path)
    target = tmp_path / "target"
    target.mkdir()
    service.start(source=source, target=target, forbidden=[])
    pointer["path"] = tmp_path / "tercero"

    with pytest.raises(content_mover.MoveError) as failure:
        service.delete_source(typed=str(source), forbidden=[])

    assert "no longer points" in str(failure.value)
    assert source.is_dir()


# ---------------------------------------------------------------------------
# S4 — what a checkout-shaped content root carries
# ---------------------------------------------------------------------------


def test_a_checkout_content_root_carries_only_the_author_members(
    tmp_path: Path,
) -> None:
    root = _content_root(tmp_path)
    for name in ("src", "frontend", "docs", ".wrangler", "output"):
        (root / name).mkdir()
        (root / name / "f.txt").write_text("generated\n", encoding="utf-8")
    (root / ".demiurgos-estado.json").write_text("{}", encoding="utf-8")
    target = tmp_path / "target"
    target.mkdir()

    plan = plan_move(root, target)
    execute_move(plan, publish=lambda path: None)

    # `output/` DOES travel on purpose: the backup carries it too, and a move
    # that dropped author-visible exports would silently lose work. What must not
    # travel is code, a tool cache and the legacy machine-state file.
    assert plan.members == (
        ".env",
        "config",
        "data",
        "ideas",
        "mundos",
        "output",
        "plantillas",
    )
    assert not (target / "src").exists()
    assert not (target / "frontend").exists()
    assert not (target / "docs").exists()
    assert not (target / ".wrangler").exists()
    assert not (target / ".demiurgos-estado.json").exists()


def test_the_plan_reports_the_state_files_it_leaves_behind(tmp_path: Path) -> None:
    root = _content_root(tmp_path, legacy_state=True)
    (root / "data" / "world-trash").mkdir()
    (root / "data" / "world-trash" / "old.md").write_text("x\n", encoding="utf-8")
    target = tmp_path / "target"
    target.mkdir()

    reasons = dict(plan_move(root, target).skipped)

    for relative in ("data/idea-capture.sqlite3", "data/world-trash"):
        assert relative in reasons, relative
        assert reasons[relative].startswith("excluded:")
