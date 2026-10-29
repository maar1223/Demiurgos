# -*- coding: utf-8 -*-
"""``/api/data-root`` — the author sees and changes where their worlds live (step 4).

The contract under test: GET reports the folder the running app uses plus the
facts a picker needs; POST records a new one and refuses, with a readable
reason, every case that would leave the author's content unreachable (a relative
path, a missing folder, the machine-state folder, an empty folder that would
hide existing worlds) or that the environment pins.

A saved choice moves no bytes and needs a restart to take effect, so the payload
says both things out loud instead of pretending the process switched folders.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import data_root as resolver
from content_root_router import create_content_root_router

POINTER = resolver.POINTER_NAME


def _root(tmp_path: Path, *, worlds: int = 2) -> Path:
    root = tmp_path / "content-root"
    for sub in ("mundos", "ideas", "data", "config"):
        (root / sub).mkdir(parents=True, exist_ok=True)
    for index in range(worlds):
        (root / "mundos" / f"Mundo{index}" / "lore").mkdir(parents=True)
        (root / "mundos" / f"Mundo{index}" / "lore" / "inicio.md").write_text(
            "# Inicio\n", encoding="utf-8"
        )
    return root


def _config(tmp_path: Path) -> Path:
    config = tmp_path / "config" / "demiurgos"
    config.mkdir(parents=True, exist_ok=True)
    return config


def _write_pointer(config: Path, root: Path) -> None:
    (config / POINTER).write_text(
        json.dumps(
            {
                "schema_version": 1,
                "data_root": str(root),
                "updated_at": "2026-10-26T02:07:51Z",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _client(
    tmp_path: Path,
    *,
    root: Path | None = None,
    config: Path | None = None,
    env: dict[str, str] | None = None,
    principal: bool = True,
) -> TestClient:
    app = FastAPI()
    app.include_router(
        create_content_root_router(
            (lambda request=None: "tester") if principal else (lambda request=None: None),
            env=env or {},
            config_dir=config if config is not None else _config(tmp_path),
            state_dir=tmp_path / "state",
            current_root=(lambda: root) if root is not None else None,
        )
    )
    return TestClient(app)


# ---------------------------------------------------------------------------
# GET — what the running app uses, and the facts a picker needs
# ---------------------------------------------------------------------------


def test_an_unconfigured_root_is_reported_honestly(tmp_path: Path) -> None:
    payload = _client(tmp_path).get("/api/data-root").json()
    assert payload["configured"] is False
    assert payload["origin"] == "unconfigured"
    assert payload["path"] is None
    assert payload["recorded_path"] is None
    assert payload["pending_restart"] is False


def test_a_pointer_configured_root_reports_disk_facts_and_worlds(
    tmp_path: Path,
) -> None:
    root = _root(tmp_path)
    config = _config(tmp_path)
    _write_pointer(config, root)

    payload = _client(tmp_path, root=root, config=config).get("/api/data-root").json()

    assert payload["configured"] is True
    assert payload["origin"] == "pointer"
    assert payload["path"] == str(root.resolve())
    assert payload["worlds"] == 2
    assert payload["usable"] is True
    assert payload["disk"]["free_bytes"] > 0
    assert payload["disk"]["total_bytes"] >= payload["disk"]["free_bytes"]
    assert payload["pending_restart"] is False


def test_the_environment_is_reported_as_the_origin(tmp_path: Path) -> None:
    root = _root(tmp_path)
    payload = _client(
        tmp_path, root=root, env={resolver.ENV_VAR: str(root)}
    ).get("/api/data-root").json()
    assert payload["origin"] == "env"


def test_a_recorded_folder_that_differs_from_the_one_in_use_asks_for_a_restart(
    tmp_path: Path,
) -> None:
    in_use = _root(tmp_path)
    nueva = tmp_path / "nueva"
    nueva.mkdir()
    config = _config(tmp_path)
    _write_pointer(config, nueva)

    payload = _client(tmp_path, root=in_use, config=config).get("/api/data-root").json()

    assert payload["path"] == str(in_use.resolve())
    assert payload["recorded_path"] == str(nueva.resolve())
    assert payload["pending_restart"] is True


# ---------------------------------------------------------------------------
# POST — the choice persists, and the refusals name why
# ---------------------------------------------------------------------------


def test_the_choice_is_recorded_and_asks_for_a_restart(tmp_path: Path) -> None:
    current = _root(tmp_path, worlds=0)
    config = _config(tmp_path)
    chosen = tmp_path / "mis mundos"
    chosen.mkdir()

    response = _client(tmp_path, root=current, config=config).post(
        "/api/data-root", json={"path": str(chosen)}
    )

    assert response.status_code == 200, response.text
    assert response.json()["restart_required"] is True
    assert resolver.read_pointer(config_dir=config) == chosen.resolve()


def test_a_relative_path_is_refused(tmp_path: Path) -> None:
    current = _root(tmp_path, worlds=0)
    response = _client(tmp_path, root=current).post(
        "/api/data-root", json={"path": "mis-mundos"}
    )
    assert response.status_code == 400
    assert "absolute" in response.json()["detail"]


def test_a_missing_folder_is_refused(tmp_path: Path) -> None:
    current = _root(tmp_path, worlds=0)
    response = _client(tmp_path, root=current).post(
        "/api/data-root", json={"path": str(tmp_path / "nope")}
    )
    assert response.status_code == 400
    assert "existing directory" in response.json()["detail"]


@pytest.mark.parametrize("shape", ["itself", "inside", "enclosing"])
def test_the_machine_state_folder_is_refused(tmp_path: Path, shape: str) -> None:
    current = _root(tmp_path, worlds=0)
    state = (tmp_path / "state" / "data").resolve()
    state.mkdir(parents=True)
    chosen = {
        "itself": state,
        "inside": state / "inner",
        "enclosing": state.parent,
    }[shape]
    chosen.mkdir(parents=True, exist_ok=True)

    response = _client(tmp_path, root=current).post(
        "/api/data-root", json={"path": str(chosen)}
    )

    assert response.status_code == 400
    assert "machine-state" in response.json()["detail"]


def test_an_empty_folder_never_hides_existing_worlds(tmp_path: Path) -> None:
    current = _root(tmp_path, worlds=3)
    config = _config(tmp_path)
    _write_pointer(config, current)
    empty = tmp_path / "vacia"
    empty.mkdir()

    response = _client(tmp_path, root=current, config=config).post(
        "/api/data-root", json={"path": str(empty)}
    )

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert str(empty.resolve()) in detail
    assert str(current.resolve()) in detail
    assert "3" in detail
    # Nothing was recorded: the author's content stays reachable.
    assert resolver.read_pointer(config_dir=config) == current.resolve()


def test_a_folder_that_already_holds_worlds_is_accepted(tmp_path: Path) -> None:
    current = _root(tmp_path, worlds=3)
    other = _root(tmp_path / "otro", worlds=1)
    config = _config(tmp_path)

    response = _client(tmp_path, root=current, config=config).post(
        "/api/data-root", json={"path": str(other)}
    )

    assert response.status_code == 200, response.text
    assert resolver.read_pointer(config_dir=config) == other.resolve()


def test_the_launcher_exported_environment_does_not_freeze_the_folder(
    tmp_path: Path,
) -> None:
    """The shipped launchers export DEMIURGOS_DATA_ROOT from the pointer.

    That echo is the normal production case, not an author pin: refusing it made
    the change unreachable in the real app (verification blocker B1).
    """
    current = _root(tmp_path, worlds=1)
    other = _root(tmp_path / "otro", worlds=1)
    config = _config(tmp_path)
    _write_pointer(config, current)
    env = {resolver.ENV_VAR: str(current)}  # exactly what start-demiurgos.sh exports

    client = _client(tmp_path, root=current, config=config, env=env)
    payload = client.get("/api/data-root").json()
    assert payload["pinned"] is False
    assert payload["origin"] == "env"

    response = client.post("/api/data-root", json={"path": str(other)})

    assert response.status_code == 200, response.text
    assert resolver.read_pointer(config_dir=config) == other.resolve()


def test_rewriting_the_folder_in_use_asks_for_no_restart(tmp_path: Path) -> None:
    """No change, no restart: a false prompt teaches the author to ignore it."""
    current = _root(tmp_path, worlds=1)
    config = _config(tmp_path)
    _write_pointer(config, current)

    response = _client(tmp_path, root=current, config=config).post(
        "/api/data-root", json={"path": str(current)}
    )

    assert response.status_code == 200, response.text
    assert response.json()["restart_required"] is False


def test_a_real_override_disagreeing_with_the_pointer_is_pinned(
    tmp_path: Path,
) -> None:
    """A restart cannot adopt a pointer the environment outranks: say so."""
    recorded = _root(tmp_path, worlds=1)
    in_use = _root(tmp_path / "override", worlds=1)
    config = _config(tmp_path)
    _write_pointer(config, recorded)
    env = {resolver.ENV_VAR: str(in_use)}

    payload = _client(tmp_path, root=in_use, config=config, env=env).get(
        "/api/data-root"
    ).json()

    assert payload["pinned"] is True
    assert payload["pending_restart"] is False


def test_the_environment_pins_the_root_and_says_so(tmp_path: Path) -> None:
    current = _root(tmp_path, worlds=0)
    chosen = tmp_path / "otra"
    chosen.mkdir()
    env = {resolver.ENV_VAR: str(current)}

    response = _client(tmp_path, root=current, env=env).post(
        "/api/data-root", json={"path": str(chosen)}
    )

    assert response.status_code == 409
    assert resolver.ENV_VAR in response.json()["detail"]


# ---------------------------------------------------------------------------
# Both routes fail closed
# ---------------------------------------------------------------------------


def test_both_routes_require_a_principal(tmp_path: Path) -> None:
    client = _client(tmp_path, root=_root(tmp_path, worlds=0), principal=False)
    assert client.get("/api/data-root").status_code == 401
    assert (
        client.post("/api/data-root", json={"path": str(tmp_path)}).status_code == 401
    )


def test_the_launchers_stale_echo_is_a_restart_not_a_pin(tmp_path: Path) -> None:
    """After the APP writes the pointer, the boot-time echo disagrees with it.

    The launcher exports DEMIURGOS_DATA_ROOT from the pointer it read at start.
    Once the app moves the folder, that echo is stale: reporting "fixed by the
    variable" right after a successful move confused the author (and blamed a
    variable he never set).
    """
    old = _root(tmp_path, worlds=1)
    new = _root(tmp_path / "nuevo", worlds=1)
    config = _config(tmp_path)
    _write_pointer(config, new)
    # The app recorded this folder itself.
    from content_move_service import record_pointer_change

    record_pointer_change(tmp_path / "state", new)

    payload = _client(
        tmp_path, root=old, config=config, env={resolver.ENV_VAR: str(old)}
    ).get("/api/data-root").json()

    assert payload["pinned"] is False
    assert payload["pending_restart"] is True


def test_the_same_echo_without_an_app_change_is_still_a_pin(tmp_path: Path) -> None:
    a = _root(tmp_path, worlds=1)
    b = _root(tmp_path / "otra", worlds=1)
    config = _config(tmp_path)
    _write_pointer(config, b)

    payload = _client(
        tmp_path, root=a, config=config, env={resolver.ENV_VAR: str(a)}
    ).get("/api/data-root").json()

    assert payload["pinned"] is True


def test_recording_a_folder_counts_as_an_app_change(tmp_path: Path) -> None:
    current = _root(tmp_path, worlds=0)
    chosen = _root(tmp_path / "elegida", worlds=0)
    config = _config(tmp_path)

    _client(tmp_path, root=current, config=config).post(
        "/api/data-root", json={"path": str(chosen)}
    )

    from content_move_service import read_pointer_change

    change = read_pointer_change(tmp_path / "state")
    assert change is not None
    assert change["path"] == str(chosen.resolve())
