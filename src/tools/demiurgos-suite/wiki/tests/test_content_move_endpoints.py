# -*- coding: utf-8 -*-
"""The move job and its endpoints (step 5).

The plan is validated synchronously so a refusal never starts a job; the copy
runs in the background with counters; the pointer moves only after the copy
verified; and the cleanup deletes the recorded old copy only with the exact
typed path.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import data_root as resolver
from content_move_service import ContentMoveService
from content_root_router import create_content_root_router


def _content_root(tmp_path: Path) -> Path:
    root = tmp_path / "content"
    (root / "mundos" / "Avalor").mkdir(parents=True)
    (root / "mundos" / "Avalor" / "inicio.md").write_text("# x\n", encoding="utf-8")
    (root / "ideas").mkdir()
    (root / "ideas" / "a.md").write_text("# i\n", encoding="utf-8")
    (root / "config").mkdir()
    (root / "data").mkdir()
    (root / "data" / "methodology").mkdir()
    (root / "data" / "methodology" / "lib.json").write_text("{}", encoding="utf-8")
    (root / ".env").write_text("DEMIURGOS_AUTH_MODE=local-dev\n", encoding="utf-8")
    return root


def _empty(tmp_path: Path, name: str = "nuevo-disco") -> Path:
    target = tmp_path / name
    target.mkdir()
    return target


def _service(tmp_path: Path, published: list[Path]) -> ContentMoveService:
    return ContentMoveService(
        state_dir=tmp_path / "state" / "data",
        publish=published.append,
        run_inline=True,
    )


def _client(
    tmp_path: Path,
    root: Path | object,
    service: ContentMoveService,
    *,
    principal: bool = True,
) -> TestClient:
    """A client whose "folder in use" can be a path or a zero-arg provider."""
    app = FastAPI()
    app.include_router(
        create_content_root_router(
            (lambda request=None: "tester") if principal else (lambda request=None: None),
            env={},
            config_dir=tmp_path / "config" / "demiurgos",
            state_dir=tmp_path / "state",
            current_root=(root if callable(root) else (lambda: root)),
            move_service=service,
        )
    )
    return TestClient(app)


def test_a_move_runs_validates_and_publishes_the_new_folder(tmp_path: Path) -> None:
    root = _content_root(tmp_path)
    target = _empty(tmp_path)
    published: list[Path] = []

    response = _client(tmp_path, root, _service(tmp_path, published)).post(
        "/api/data-root/move", json={"target": str(target)}
    )

    assert response.status_code == 202, response.text
    job = response.json()["job"]
    assert job["state"] == "done"
    assert job["pointer_written"] is True
    assert job["total_files"] >= 3
    assert published == [target.resolve()]
    assert (target / "mundos" / "Avalor" / "inicio.md").is_file()
    assert (target / ".env").is_file()


def test_a_refused_plan_never_starts_a_job(tmp_path: Path) -> None:
    root = _content_root(tmp_path)
    target = _empty(tmp_path)
    (target / "ya-hay.md").write_text("x", encoding="utf-8")
    published: list[Path] = []

    response = _client(tmp_path, root, _service(tmp_path, published)).post(
        "/api/data-root/move", json={"target": str(target)}
    )

    assert response.status_code == 400
    assert "must be empty" in response.json()["detail"]
    assert published == []
    assert not (target / "mundos").exists()


def test_a_move_is_refused_while_another_one_runs(tmp_path: Path) -> None:
    root = _content_root(tmp_path)
    release = threading.Event()

    def slow_publish(path: Path) -> None:
        release.wait(5)

    service = ContentMoveService(
        state_dir=tmp_path / "state" / "data", publish=slow_publish
    )
    client = _client(tmp_path, root, service)
    first = client.post(
        "/api/data-root/move", json={"target": str(_empty(tmp_path, "uno"))}
    )
    assert first.status_code == 202, first.text

    second = client.post(
        "/api/data-root/move", json={"target": str(_empty(tmp_path, "dos"))}
    )
    release.set()
    assert second.status_code == 409
    assert "already running" in second.json()["detail"]

    job_id = first.json()["job"]["id"]
    deadline = time.time() + 5
    while time.time() < deadline:
        if client.get(f"/api/data-root/move/{job_id}").json()["job"]["state"] != "copying":
            break
        time.sleep(0.02)


def test_an_unknown_job_is_404(tmp_path: Path) -> None:
    client = _client(tmp_path, _content_root(tmp_path), _service(tmp_path, []))
    assert client.get("/api/data-root/move/nope").status_code == 404
    assert client.post("/api/data-root/move/nope/cancel").status_code == 404


def test_the_job_reports_its_state_and_counters(tmp_path: Path) -> None:
    root = _content_root(tmp_path)
    published: list[Path] = []
    client = _client(tmp_path, root, _service(tmp_path, published))
    started = client.post(
        "/api/data-root/move", json={"target": str(_empty(tmp_path))}
    ).json()["job"]

    polled = client.get(f"/api/data-root/move/{started['id']}").json()

    assert polled["job"]["state"] == "done"
    assert polled["job"]["copied_bytes"] > 0
    assert polled["last_move"]["state"] == "done"
    assert polled["last_move"]["pointer_written"] is True


# ---------------------------------------------------------------------------
# Cleanup: the recorded folder, typed back
# ---------------------------------------------------------------------------


def test_cleanup_needs_a_completed_move(tmp_path: Path) -> None:
    client = _client(tmp_path, _content_root(tmp_path), _service(tmp_path, []))
    response = client.post("/api/data-root/cleanup", json={"confirm": "/x"})
    assert response.status_code == 409
    assert "no completed move" in response.json()["detail"]


def test_cleanup_requires_the_exact_typed_path(tmp_path: Path) -> None:
    root = _content_root(tmp_path)
    target = _empty(tmp_path)
    published: list[Path] = []
    # The app keeps using the folder it booted with until it restarts; the test
    # models the restart by switching the provider after the move.
    in_use: dict[str, Path] = {"path": root}
    client = _client(
        tmp_path, lambda: in_use["path"], _service(tmp_path, published)
    )
    client.post("/api/data-root/move", json={"target": str(target)})
    in_use["path"] = target.resolve()

    wrong = client.post("/api/data-root/cleanup", json={"confirm": str(tmp_path)})
    assert wrong.status_code == 400
    assert "type the folder exactly" in wrong.json()["detail"]
    assert root.is_dir()

    before_restart = _client(tmp_path, root, _service(tmp_path, published))
    refused = before_restart.post(
        "/api/data-root/cleanup", json={"confirm": str(root)}
    )
    assert refused.status_code == 409
    assert "overlaps" in refused.json()["detail"]
    assert root.is_dir()

    correct = client.post("/api/data-root/cleanup", json={"confirm": str(root)})
    assert correct.status_code == 200, correct.text
    assert not root.exists()


def test_cleanup_never_deletes_the_folder_in_use(tmp_path: Path) -> None:
    root = _content_root(tmp_path)
    published: list[Path] = []
    service = _service(tmp_path, published)
    client = _client(tmp_path, root, service)
    client.post("/api/data-root/move", json={"target": str(_empty(tmp_path))})
    # The pointer now points at the new folder; pretend the app already runs there
    # while the record still names the old one: that pair must be refused when the
    # recorded folder IS the folder in use.
    moved_to = Path(service.last_move()["target"])
    moving_client = _client(tmp_path, moved_to, service)

    response = moving_client.post(
        "/api/data-root/cleanup", json={"confirm": str(moved_to)}
    )

    assert response.status_code in (400, 409)
    assert moved_to.is_dir()


def test_every_move_route_requires_a_principal(tmp_path: Path) -> None:
    root = _content_root(tmp_path)
    client = _client(tmp_path, root, _service(tmp_path, []), principal=False)
    assert client.post("/api/data-root/move", json={"target": str(root)}).status_code == 401
    assert client.get("/api/data-root/move/x").status_code == 401
    assert client.post("/api/data-root/move/x/cancel").status_code == 401
    assert client.get("/api/data-root/last-move").status_code == 401
    assert client.post("/api/data-root/cleanup", json={"confirm": ""}).status_code == 401


# ---------------------------------------------------------------------------
# The job record lives in the state directory, never in the content root
# ---------------------------------------------------------------------------


def test_the_record_never_lands_in_the_content_root(tmp_path: Path) -> None:
    root = _content_root(tmp_path)
    published: list[Path] = []
    service = _service(tmp_path, published)
    client = _client(tmp_path, root, service)

    client.post("/api/data-root/move", json={"target": str(_empty(tmp_path))})

    assert service.record_path().is_file()
    assert service.record_path().is_relative_to(tmp_path / "state")
    assert not list(root.rglob("content-move-last.json"))
    record = json.loads(service.record_path().read_text(encoding="utf-8"))
    assert record["schema_version"] == 1
    assert record["state"] == "done"
