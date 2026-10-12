# -*- coding: utf-8 -*-
"""tests/test_update_router.py — Slice 2b ``/api/update`` router (status + channel).

Covers ``GET /api/update/status`` and ``PUT /api/update/channel``: fail-closed
401 auth, the channel default (``Estable``), invalid-channel 400 with the
persisted value unchanged, channel persistence across reload, the url_base
resolution chain (channel.json -> env -> default), advisory fetch degradation,
stable-ignores-prereleases (via the pointer selection), beta offers the newer
prerelease, no auto-downgrade, and no update when the current version is
newest.

The FastAPI app is built with an injected fake ``require_principal``, a
``LocalState`` rooted in ``tmp_path`` and a ``channel_fetch`` stub, so no real
network and no real install state are ever touched (mirrors
``test_system_control.py``).
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

_HERE = Path(__file__).resolve().parent
_WIKI = _HERE.parent
for _p in (str(_WIKI),):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import updater  # noqa: E402
from local_state import LocalState  # noqa: E402
from updater import (  # noqa: E402
    DEFAULT_CHANNEL_URL,
    VALID_CHANNELS,
    _fetch_text,
    _pointer_for,
    _read_channel,
    _resolve_url_base,
    create_update_router,
)

AUTH_REQUIRED = {"detail": "Autenticación requerida"}


class _FakePrincipal:
    def __init__(self, pid: str = "tester"):
        self.id = pid


class _ChannelStub:
    """Serves the release pointers a real channel publishes, recording fetches.

    ``latest`` / ``latest_beta`` mirror the channel-asset pointers the release
    gate (slice 0) keeps channel-correct; ``fail`` simulates an unreachable
    channel; ``urls`` records every fetched URL so a test can assert WHICH
    pointer the router consulted.
    """

    def __init__(
        self,
        latest: str | None = None,
        latest_beta: str | None = None,
        *,
        fail: bool = False,
    ):
        self.latest = latest
        self.latest_beta = latest_beta
        self.fail = fail
        self.urls: list[str] = []

    def __call__(self, url: str) -> str | None:
        self.urls.append(url)
        if self.fail:
            return None
        if url.endswith("/latest-beta"):
            return self.latest_beta
        if url.endswith("/latest"):
            return self.latest
        return None


def _make_app(
    *,
    local_state_path: Path,
    authed: bool = True,
    app_version: str = "0.1.1",
    install_root: Path | None = None,
    channel_fetch=None,
    channel_config_path: Path | None = None,
) -> tuple[FastAPI, LocalState]:
    """Build the router over a ``LocalState`` rooted at *local_state_path*."""
    registry = LocalState(local_state_path)

    def _require_principal(_request) -> _FakePrincipal | None:
        return _FakePrincipal() if authed else None

    app = FastAPI()
    app.include_router(
        create_update_router(
            _require_principal,
            app_version=lambda: app_version,
            install_root=install_root,
            local_state=lambda: registry,
            install_argv=["/bin/true"],
            install_available=True,
            channel_config_path=channel_config_path,
            channel_fetch=channel_fetch,
        )
    )
    return app, registry


def _get_status(client: TestClient) -> dict:
    resp = client.get("/api/update/status")
    assert resp.status_code == 200, resp.text
    return resp.json()


# ---------------------------------------------------------------------------
# Fail-closed auth (spec: 'Unauthenticated status/channel switch fails closed')
# ---------------------------------------------------------------------------


def test_status_requires_principal(tmp_path: Path) -> None:
    app, _registry = _make_app(
        local_state_path=tmp_path / "local-state.json", authed=False,
        channel_fetch=_ChannelStub(latest="0.2.0"),
    )
    resp = TestClient(app).get("/api/update/status")
    assert resp.status_code == 401
    assert resp.json() == AUTH_REQUIRED


def test_channel_put_requires_principal_and_leaves_state_unchanged(tmp_path: Path) -> None:
    state_path = tmp_path / "local-state.json"
    app, registry = _make_app(
        local_state_path=state_path, authed=False,
        channel_fetch=_ChannelStub(latest="0.2.0"),
    )
    resp = TestClient(app).put("/api/update/channel", json={"channel": "Beta"})
    assert resp.status_code == 401
    assert resp.json() == AUTH_REQUIRED
    # No write happened: the update slot is still absent.
    snapshot = registry.snapshot()
    assert "update" not in snapshot.get("capabilities", {})

    # A fresh registry on the same file (restart) still defaults to Estable.
    reloaded = LocalState(state_path)
    assert _read_channel(reloaded) == "Estable"


# ---------------------------------------------------------------------------
# Channel default and persistence
# ---------------------------------------------------------------------------


def test_default_channel_is_estable(tmp_path: Path) -> None:
    app, _registry = _make_app(
        local_state_path=tmp_path / "local-state.json",
        channel_fetch=_ChannelStub(latest="0.2.0"),
    )
    status = _get_status(TestClient(app))
    assert status["channel"] == "Estable"
    assert status["url_base"] == DEFAULT_CHANNEL_URL
    assert status["latest"] == "0.2.0"
    assert status["update_available"] is True
    assert status["advisory_unavailable"] is False


def test_invalid_channel_rejected_with_persisted_value_unchanged(tmp_path: Path) -> None:
    state_path = tmp_path / "local-state.json"
    app, registry = _make_app(
        local_state_path=state_path,
        channel_fetch=_ChannelStub(latest="0.2.0", latest_beta="0.2.0-beta.2"),
    )
    client = TestClient(app)
    # Establish a persisted channel first.
    ok = client.put("/api/update/channel", json={"channel": "Beta"})
    assert ok.status_code == 200
    assert ok.json() == {"channel": "Beta"}

    for bad in ("Canary", "estable", "", 7, None):
        resp = client.put("/api/update/channel", json={"channel": bad})
        assert resp.status_code == 400, bad
        assert resp.json()["code"] == "update.invalid_channel"
        assert resp.json()["detail"]

    # Persisted value is unchanged (still Beta) across every rejection.
    status = _get_status(client)
    assert status["channel"] == "Beta"
    assert registry.snapshot()["capabilities"]["update"]["channel"] == "Beta"


def test_channel_persists_across_reload(tmp_path: Path) -> None:
    state_path = tmp_path / "local-state.json"
    first, _registry = _make_app(
        local_state_path=state_path,
        channel_fetch=_ChannelStub(latest="0.2.0", latest_beta="0.2.0-beta.2"),
    )
    resp = TestClient(first).put("/api/update/channel", json={"channel": "Beta"})
    assert resp.status_code == 200

    # Simulate a process restart: a fresh LocalState reads the same file.
    second, _registry2 = _make_app(
        local_state_path=state_path,
        channel_fetch=_ChannelStub(latest="0.2.0", latest_beta="0.2.0-beta.2"),
    )
    status = _get_status(TestClient(second))
    assert status["channel"] == "Beta"
    assert status["latest"] == "0.2.0-beta.2"


# ---------------------------------------------------------------------------
# url_base resolution chain (spec: channel.json -> env -> default)
# ---------------------------------------------------------------------------


def test_url_base_from_channel_json(tmp_path: Path) -> None:
    install_root = tmp_path / "install"
    install_root.mkdir()
    cfg = {
        "schema_version": 1,
        "url_base": "https://mirror.example.test/channel",
    }
    (install_root / "channel.json").write_text(
        json.dumps(cfg) + "\n", encoding="utf-8"
    )
    stub = _ChannelStub(latest="0.2.0")
    app, _registry = _make_app(
        local_state_path=tmp_path / "local-state.json",
        install_root=install_root,
        channel_fetch=stub,
    )
    status = _get_status(TestClient(app))
    assert status["url_base"] == "https://mirror.example.test/channel"
    assert stub.urls == ["https://mirror.example.test/channel/latest"]


def test_url_base_from_env_when_no_channel_json(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DEMIURGOS_CHANNEL_URL", "https://env.example.test/ch")
    stub = _ChannelStub(latest="0.2.0")
    app, _registry = _make_app(
        local_state_path=tmp_path / "local-state.json",
        channel_fetch=stub,
    )
    status = _get_status(TestClient(app))
    assert status["url_base"] == "https://env.example.test/ch"
    assert stub.urls == ["https://env.example.test/ch/latest"]


def test_url_base_default_when_nothing_set(tmp_path: Path) -> None:
    env = {}
    assert _resolve_url_base(None, env) == DEFAULT_CHANNEL_URL
    # channel.json without a usable url_base falls through too.
    bogus = tmp_path / "channel.json"
    bogus.write_text('{"schema_version": 1, "url_base": ""}\n', encoding="utf-8")
    assert _resolve_url_base(bogus, env) == DEFAULT_CHANNEL_URL
    # An unreadable path never fails.
    assert _resolve_url_base(tmp_path / "missing.json", env) == DEFAULT_CHANNEL_URL


# ---------------------------------------------------------------------------
# Advisory fetch behavior (spec: degradation, pointer selection, no-downgrade)
# ---------------------------------------------------------------------------


def test_fetch_failure_degrades_gracefully(tmp_path: Path) -> None:
    app, _registry = _make_app(
        local_state_path=tmp_path / "local-state.json",
        app_version="0.1.1",
        channel_fetch=_ChannelStub(latest="0.2.0", fail=True),
    )
    status = _get_status(TestClient(app))
    assert status["current_version"] == "0.1.1"
    assert status["channel"] == "Estable"
    assert status["url_base"] == DEFAULT_CHANNEL_URL
    assert status["latest"] is None
    assert status["update_available"] is False
    assert status["advisory_unavailable"] is True


def test_empty_pointer_treated_as_unavailable(tmp_path: Path) -> None:
    app, _registry = _make_app(
        local_state_path=tmp_path / "local-state.json",
        app_version="0.1.1",
        channel_fetch=_ChannelStub(latest="   "),
    )
    status = _get_status(TestClient(app))
    assert status["latest"] is None
    assert status["update_available"] is False
    assert status["advisory_unavailable"] is True


def test_stable_channel_ignores_prereleases(tmp_path: Path) -> None:
    """Estable consults ONLY the stable ``latest`` pointer, never the beta one
    (spec 'Stable channel ignores prereleases')."""
    stub = _ChannelStub(latest="0.2.0", latest_beta="0.2.0-beta.1")
    app, _registry = _make_app(
        local_state_path=tmp_path / "local-state.json",
        app_version="0.1.1",
        channel_fetch=stub,
    )
    status = _get_status(TestClient(app))
    assert status["channel"] == "Estable"
    assert status["latest"] == "0.2.0"
    assert status["update_available"] is True
    assert stub.urls == [f"{DEFAULT_CHANNEL_URL}/latest"]


def test_beta_channel_offers_newer_prerelease(tmp_path: Path) -> None:
    stub = _ChannelStub(latest="0.2.0", latest_beta="0.2.0-beta.2")
    app, _registry = _make_app(
        local_state_path=tmp_path / "local-state.json",
        app_version="0.1.1",
        channel_fetch=stub,
    )
    client = TestClient(app)
    resp = client.put("/api/update/channel", json={"channel": "Beta"})
    assert resp.status_code == 200

    status = _get_status(client)
    assert status["channel"] == "Beta"
    assert status["latest"] == "0.2.0-beta.2"
    assert status["update_available"] is True
    assert stub.urls[-1] == f"{DEFAULT_CHANNEL_URL}/latest-beta"


def test_no_downgrade_when_leaving_beta(tmp_path: Path) -> None:
    """Leaving Beta for a stable line BEHIND the running beta never offers a
    downgrade (spec 'No downgrade when leaving Beta')."""
    stub = _ChannelStub(latest="0.2.0", latest_beta="0.3.0-beta.1")
    app, _registry = _make_app(
        local_state_path=tmp_path / "local-state.json",
        app_version="0.3.0-beta.1",
        channel_fetch=stub,
    )
    client = TestClient(app)
    assert client.put("/api/update/channel", json={"channel": "Beta"}).status_code == 200
    assert _get_status(client)["latest"] == "0.3.0-beta.1"

    # Switch back to Estable: the stable latest (0.2.0) is OLDER than the
    # running beta (0.3.0-beta.1) — no update may be offered.
    assert client.put("/api/update/channel", json={"channel": "Estable"}).status_code == 200
    status = _get_status(client)
    assert status["channel"] == "Estable"
    assert status["latest"] == "0.2.0"
    assert status["update_available"] is False


def test_leaving_beta_never_offers_below_semver_current(tmp_path: Path) -> None:
    """Spec-text gray case: running 0.2.0-beta.2 on Estable whose latest is
    0.2.0 — 0.2.0 is STRICTLY GREATER under SemVer, so it may be offered as an
    upgrade, but a version below the running one is never offered."""
    stub = _ChannelStub(latest="0.2.0")
    app, _registry = _make_app(
        local_state_path=tmp_path / "local-state.json",
        app_version="0.2.0-beta.2",
        channel_fetch=stub,
    )
    status = _get_status(TestClient(app))
    assert status["channel"] == "Estable"
    assert status["latest"] == "0.2.0"
    assert status["update_available"] is True  # 0.2.0 > 0.2.0-beta.2 (upgrade)


def test_no_update_when_current_is_newest(tmp_path: Path) -> None:
    for current, latest in (("0.2.0", "0.2.0"), ("0.2.0", "0.2.0-beta.1")):
        app, _registry = _make_app(
            local_state_path=tmp_path / "local-state.json",
            app_version=current,
            channel_fetch=_ChannelStub(latest=latest),
        )
        status = _get_status(TestClient(app))
        assert status["latest"] == latest
        assert status["update_available"] is False, (current, latest)
        assert status["advisory_unavailable"] is False


def test_unparseable_advisory_never_offers(tmp_path: Path) -> None:
    app, _registry = _make_app(
        local_state_path=tmp_path / "local-state.json",
        app_version="0.1.1",
        channel_fetch=_ChannelStub(latest="not-a-version"),
    )
    status = _get_status(TestClient(app))
    # The raw advisory is still surfaced (display-only) but never offered.
    assert status["latest"] == "not-a-version"
    assert status["update_available"] is False
    assert status["advisory_unavailable"] is False


# ---------------------------------------------------------------------------
# Helpers — direct unit coverage
# ---------------------------------------------------------------------------


def test_pointer_for_channel() -> None:
    assert _pointer_for("Estable") == "latest"
    assert _pointer_for("Beta") == "latest-beta"


def test_read_channel_default_and_persisted(tmp_path: Path) -> None:
    state_path = tmp_path / "local-state.json"
    fresh = LocalState(state_path)
    assert _read_channel(fresh) == "Estable"

    snapshot = fresh.snapshot()
    snapshot.setdefault("capabilities", {})["update"] = {"channel": "Beta"}
    fresh.atomic_commit(snapshot)
    assert _read_channel(LocalState(state_path)) == "Beta"


def test_resolve_url_base_env_beats_default() -> None:
    env = {"DEMIURGOS_CHANNEL_URL": "https://env.example.test"}
    assert _resolve_url_base(None, env) == "https://env.example.test"


def test_fetch_text_file_scheme(tmp_path: Path) -> None:
    pointer = tmp_path / "latest"
    pointer.write_text("0.2.0\n", encoding="utf-8")
    assert _fetch_text(pointer.as_uri()) == "0.2.0"
    assert _fetch_text(f"{pointer.as_uri()}-missing") is None


def test_fetch_text_rejects_disallowed_schemes() -> None:
    assert _fetch_text("http://example.test/latest") is None
    assert _fetch_text("ftp://example.test/latest") is None
    assert _fetch_text("not a url::") is None


def test_updater_has_no_forbidden_dependency() -> None:
    """Hard constraint: updater must reuse semver.py and must not import
    ``packaging`` nor reference ``methodology_library._version_key``."""
    source = (Path(updater.__file__)).read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert not alias.name.startswith("packaging"), alias.name
        elif isinstance(node, ast.ImportFrom):
            assert not (node.module or "").startswith("packaging"), node.module
    assert "_version_key" not in source


def test_valid_channels_only_estable_and_beta() -> None:
    assert VALID_CHANNELS == ("Estable", "Beta")