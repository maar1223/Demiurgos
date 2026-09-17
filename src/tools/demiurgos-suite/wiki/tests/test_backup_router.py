# -*- coding: utf-8 -*-
"""``/api/backup/*`` router tests (WU-14, task 14.8).

Covers the eight-route contract, the fail-closed auth posture, and — the whole
point of the WU-12 deferral — the LIVE ``GET /api/backup/status`` payload:
the response is asserted cloud-free at any nesting depth and vocabulary-clean
in es-ES and en (REQ-BUI-1, SC-BUI-1.3, SC-SF-4.1, SC-SF-4.2).

The app is built from the factory alone (no ``api_server`` import), so the suite
drives the real routes hermetically: the destination is a ``tmp_path`` folder
and every OS touchpoint is injected.
"""

from __future__ import annotations

import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

_HERE = Path(__file__).resolve().parent
_WIKI = _HERE.parent
if str(_WIKI) not in sys.path:
    sys.path.insert(0, str(_WIKI))

from backup.router import create_backup_router  # noqa: E402
from backup.state import read_destination  # noqa: E402
from backup.sync_folder import (  # noqa: E402
    MODE_STREAMING,
    MIRRORING_REMEDY,
    REASON_STREAMING,
    TargetCapabilities,
    TargetDecision,
    find_dishonest_status_keys,
    find_forbidden_vocabulary,
)

#: The router contract, exactly (REQ-BUI-1). No ninth route may appear.
EXPECTED_ROUTES = {
    ("GET", "/api/backup/status"),
    ("GET", "/api/backup/candidates"),
    ("POST", "/api/backup/destination"),
    ("POST", "/api/backup/run"),
    ("GET", "/api/backup/snapshots"),
    ("POST", "/api/backup/restore/preview"),
    ("POST", "/api/backup/restore"),
    ("GET", "/api/backup/restore/status"),
}

#: A valid body per route, so an unauthenticated call reaches the guard instead
#: of a 422 body-validation error (the guard is the first handler statement).
ROUTE_BODIES = {
    "/api/backup/destination": {"path": "/tmp/not-a-real-destination"},
    "/api/backup/run": {},
    "/api/backup/restore/preview": {"snapshot_id": "2026-01-01T000000Z"},
    "/api/backup/restore": {"snapshot_id": "2026-01-01T000000Z", "confirm": True},
}


def _principal(request=None) -> str:
    return "tester"


def _no_principal(request=None):
    return None


def _make_app(tmp_path: Path, *, require_principal=_principal, **seams) -> FastAPI:
    app = FastAPI()
    app.include_router(
        create_backup_router(require_principal, data_root=tmp_path, **seams)
    )
    return app


def _make_root(tmp_path: Path) -> Path:
    root = tmp_path / "data-root"
    for sub in ("mundos", "ideas", "data", "config"):
        (root / sub).mkdir(parents=True, exist_ok=True)
    return root


def _string_leaves(value):
    from typing import Mapping

    if isinstance(value, Mapping):
        for nested in value.values():
            yield from _string_leaves(nested)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _string_leaves(item)
    elif isinstance(value, str):
        yield value


def _streaming_decision(path: Path) -> TargetDecision:
    return TargetDecision(
        False,
        TargetCapabilities(
            kind="folder",
            path=str(path),
            writable=False,
            same_volume_as_data_root=False,
            mode_hint=MODE_STREAMING,
        ),
        remedy=MIRRORING_REMEDY,
        reason=REASON_STREAMING,
    )


# ---------------------------------------------------------------------------
# Route surface + fail-closed auth
# ---------------------------------------------------------------------------


def test_exactly_the_eight_routes_are_mounted(tmp_path: Path) -> None:
    """The factory's surface is EXACTLY the eight routes, and the app serves them."""
    router = create_backup_router(_principal, data_root=_make_root(tmp_path))
    observed = {
        (method, route.path)
        for route in router.routes
        for method in getattr(route, "methods", ())
    }
    assert observed == EXPECTED_ROUTES
    app = _make_app(_make_root(tmp_path))
    assert set(app.openapi()["paths"]) == {path for _, path in EXPECTED_ROUTES}


def test_every_route_fails_closed_unauthenticated(tmp_path: Path) -> None:
    """SC-BUI-1.3 — an unauthenticated call is 401, never a permissive default."""
    app = _make_app(_make_root(tmp_path), require_principal=_no_principal)
    client = TestClient(app)
    for method, path in sorted(EXPECTED_ROUTES):
        body = ROUTE_BODIES.get(path)
        response = client.request(method, path, json=body)
        assert response.status_code == 401, (method, path, response.text)
        assert "detail" in response.json()


def test_candidates_always_offer_the_picker_even_with_none_found(tmp_path: Path) -> None:
    app = _make_app(_make_root(tmp_path), discover=lambda: [])
    response = TestClient(app).get("/api/backup/candidates")
    assert response.status_code == 200
    assert response.json() == {"candidates": [], "picker": True}


# ---------------------------------------------------------------------------
# SC-SF-4.2 — the LIVE status payload is cloud-free and vocabulary-clean
# ---------------------------------------------------------------------------


def test_live_status_payload_is_honest_end_to_end(tmp_path: Path) -> None:
    """The deferral closed: the REAL route's response carries no delivery claim.

    A destination is chosen and a real run performed, so the payload carries the
    destination record, the local-write record and the copy string — the richest
    shape the route can produce. The assertions run on what the client received,
    not on the shared builder.
    """
    root = _make_root(tmp_path)
    destination = root / "sync-folder"
    destination.mkdir()
    client = TestClient(_make_app(root))

    assert client.post(
        "/api/backup/destination", json={"path": str(destination)}
    ).status_code == 200
    assert client.post("/api/backup/run").status_code == 200

    response = client.get("/api/backup/status")
    assert response.status_code == 200
    payload = response.json()

    # The dedicated contract is configured by real evidence...
    assert payload["state"] == "configured"
    assert payload["destination"]["path"] == str(destination)
    assert payload["last_write"]["status"] == "ok"

    # ...and the payload carries no upload/sync_state/cloud key at ANY depth.
    assert find_dishonest_status_keys(payload) == ()

    # ...and no forbidden delivery vocabulary in es-ES or en.
    for text in _string_leaves(payload):
        assert find_forbidden_vocabulary(text) == (), text

    # The copy claims the LOCAL write only, in both languages.
    assert payload["copy"]["en"].startswith("Written to ")
    assert payload["copy"]["es"].startswith("Escrito en ")
    assert "en la nube" not in payload["copy"]["es"].casefold()


def test_status_without_a_destination_is_honestly_pending(tmp_path: Path) -> None:
    payload = TestClient(_make_app(_make_root(tmp_path))).get(
        "/api/backup/status"
    ).json()
    assert payload["state"] == "pending"
    assert payload["destination"] is None
    assert payload["copy"] is None
    assert find_dishonest_status_keys(payload) == ()


# ---------------------------------------------------------------------------
# Destination selection + the streaming block
# ---------------------------------------------------------------------------


def test_destination_persists_author_config_without_secrets(tmp_path: Path) -> None:
    root = _make_root(tmp_path)
    destination = root / "chosen"
    destination.mkdir()
    response = TestClient(_make_app(root)).post(
        "/api/backup/destination", json={"path": str(destination)}
    )
    assert response.status_code == 200
    assert response.json()["state"] == "pending"  # chosen, no run yet
    record = read_destination(root)
    assert record is not None and record.path == str(destination)
    # The record is author config: a closed shape with no secret field.
    assert set(record.to_dict()) == {
        "schema_version",
        "path",
        "provider",
        "source",
        "confidence",
        "mode_hint",
        "updated_at",
    }


def test_rejected_folder_is_not_persisted(tmp_path: Path) -> None:
    root = _make_root(tmp_path)
    app = _make_app(
        root,
        evaluate=lambda path: TargetDecision(
            False,
            TargetCapabilities(
                kind="folder",
                path=str(path),
                writable=False,
                same_volume_as_data_root=False,
                mode_hint="unknown",
            ),
            reason="target is missing or not a directory",
        ),
    )
    response = TestClient(app).post(
        "/api/backup/destination", json={"path": str(root / "missing")}
    )
    assert response.status_code == 400
    assert read_destination(root) is None


def test_streaming_target_is_persisted_as_error_with_the_remedy(tmp_path: Path) -> None:
    """SC-SF-3.1 — selecting a verified streaming target blocks runs, shows the remedy."""
    root = _make_root(tmp_path)
    destination = root / "streamed"
    destination.mkdir()
    app = _make_app(root, evaluate=lambda path: _streaming_decision(path))
    client = TestClient(app)

    selected = client.post("/api/backup/destination", json={"path": str(destination)})
    assert selected.status_code == 200
    assert selected.json()["state"] == "error"
    assert selected.json()["warning"] == MIRRORING_REMEDY
    assert selected.json()["accepted"] is False

    run = client.post("/api/backup/run")
    assert run.status_code == 409
    assert MIRRORING_REMEDY in run.json()["detail"]
    # No bytes were written: no last-write record exists.
    assert client.get("/api/backup/status").json()["last_write"] is None


def test_run_without_a_destination_is_refused(tmp_path: Path) -> None:
    response = TestClient(_make_app(_make_root(tmp_path))).post("/api/backup/run")
    assert response.status_code == 409


# ---------------------------------------------------------------------------
# Snapshots + restore gates
# ---------------------------------------------------------------------------


def test_snapshots_lists_nothing_without_a_destination(tmp_path: Path) -> None:
    response = TestClient(_make_app(_make_root(tmp_path))).get("/api/backup/snapshots")
    assert response.status_code == 200
    assert response.json() == {"snapshots": []}


def test_snapshots_lists_what_the_run_published(tmp_path: Path) -> None:
    root = _make_root(tmp_path)
    destination = root / "chosen"
    destination.mkdir()
    client = TestClient(_make_app(root))
    client.post("/api/backup/destination", json={"path": str(destination)})
    client.post("/api/backup/run")
    listing = client.get("/api/backup/snapshots").json()["snapshots"]
    assert listing and listing[0]["complete"] is True


def test_restore_requires_explicit_confirmation(tmp_path: Path) -> None:
    root = _make_root(tmp_path)
    destination = root / "chosen"
    destination.mkdir()
    client = TestClient(_make_app(root))
    client.post("/api/backup/destination", json={"path": str(destination)})
    response = client.post(
        "/api/backup/restore", json={"snapshot_id": "2026-01-01T000000Z"}
    )
    assert response.status_code == 400
    assert "confirmation" in response.json()["detail"]


def test_restore_uses_the_injected_runner(tmp_path: Path) -> None:
    root = _make_root(tmp_path)
    destination = root / "chosen"
    destination.mkdir()
    calls: list[dict] = []

    class _Result:
        def to_dict(self):
            return {"snapshot_id": "2026-01-01T000000Z", "status": "ok"}

    def fake_restore(**kwargs):
        calls.append(kwargs)
        return _Result()

    client = TestClient(_make_app(root, restore=fake_restore))
    client.post("/api/backup/destination", json={"path": str(destination)})
    response = client.post(
        "/api/backup/restore",
        json={"snapshot_id": "2026-01-01T000000Z", "confirm": True},
    )
    assert response.status_code == 200
    assert response.json() == {"snapshot_id": "2026-01-01T000000Z", "status": "ok"}
    assert calls and calls[0]["snapshot_id"] == "2026-01-01T000000Z"


def test_preview_uses_the_injected_runner(tmp_path: Path) -> None:
    root = _make_root(tmp_path)
    destination = root / "chosen"
    destination.mkdir()
    client = TestClient(
        _make_app(root, preview=lambda transport, data_root, snapshot_id: {
            "validation": {"snapshot_id": snapshot_id},
            "conflicts": {"snapshot_id": snapshot_id, "blockers": []},
            "blocked": False,
        })
    )
    client.post("/api/backup/destination", json={"path": str(destination)})
    response = client.post(
        "/api/backup/restore/preview",
        json={"snapshot_id": "2026-01-01T000000Z"},
    )
    assert response.status_code == 200
    assert response.json()["blocked"] is False


def test_restore_status_reports_the_maintenance_marker(tmp_path: Path) -> None:
    root = _make_root(tmp_path)
    client = TestClient(_make_app(root))
    payload = client.get("/api/backup/restore/status").json()
    assert payload == {"pending": False, "leftovers": [], "last_write": None}
