# -*- coding: utf-8 -*-
"""tests/test_update_router.py — ``/api/update`` router (status + channel + apply).

Covers ``GET /api/update/status``, ``PUT /api/update/channel`` and
``POST /api/update/apply``: fail-closed 401 auth (apply must NOT spawn a
process when unauthenticated), the channel default (``Estable``),
invalid-channel 400 with the persisted value unchanged, channel persistence
across reload, the url_base resolution chain (channel.json -> env -> default),
advisory fetch degradation, stable-ignores-prereleases (via the pointer
selection), beta offers the newer prerelease, no auto-downgrade, no update
when the current version is newest, and the apply dispatch contract
(detached Popen with stderr to a FILE — never a PIPE — plus the
``DEMIURGOS_URL_BASE`` / ``DEMIURGOS_VERSION`` env, 0.5s early-failure 500,
spawn-failure 500, unavailable 503, none-available 409, and Windows PS argv
parity).

The FastAPI app is built with an injected fake ``require_principal``, a
``LocalState`` rooted in ``tmp_path`` and a ``channel_fetch`` stub, so no real
network and no real install state are ever touched. The apply dispatch is
tested with a mocked ``subprocess.Popen`` (mirrors ``test_system_control.py``).
"""

from __future__ import annotations

import ast
import json
import subprocess
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


class _FakeProc:
    """Minimal ``subprocess.Popen`` stand-in for the apply dispatch tests.

    ``poll_result`` mirrors ``Popen.poll()``: None = still running, an int is
    the already-observed exit code (mirrors ``test_system_control._FakeProc``).
    """

    def __init__(self, poll_result: int | None):
        self._poll_result = poll_result

    def poll(self) -> int | None:
        return self._poll_result


def _make_app(
    *,
    local_state_path: Path,
    authed: bool = True,
    app_version: str = "0.1.1",
    install_root: Path | None = None,
    channel_fetch=None,
    channel_config_path: Path | None = None,
    install_argv: list[str] | None = None,
    install_available: bool | None = True,
    install_log: Path | None = None,
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
            install_argv=install_argv if install_argv is not None else ["/bin/true"],
            install_available=install_available,
            channel_config_path=channel_config_path,
            channel_fetch=channel_fetch,
            install_log=install_log,
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
# Apply dispatch (spec: 'Apply endpoint is principal-gated', 'Detached
# installer dispatch', 'Apply dispatches with channel URL and target version',
# 'Windows parity for apply') — mocked subprocess.Popen, mirrors
# test_system_control.py
# ---------------------------------------------------------------------------


def test_apply_requires_principal_and_starts_no_process(
    tmp_path: Path, monkeypatch
) -> None:
    """Unauthenticated apply fails closed with 401 and NEVER spawns (the
    principal guard runs before any resolution/dispatch)."""
    calls: dict = {}

    def fake_popen(argv, **kwargs):
        calls["argv"] = argv
        return _FakeProc(poll_result=None)

    monkeypatch.setattr(updater.subprocess, "Popen", fake_popen)
    app, _registry = _make_app(
        local_state_path=tmp_path / "local-state.json", authed=False,
        channel_fetch=_ChannelStub(latest="0.2.0"),
    )
    resp = TestClient(app).post("/api/update/apply")
    assert resp.status_code == 401
    assert resp.json() == AUTH_REQUIRED
    assert "argv" not in calls, "an unauthenticated apply must never spawn"


def test_apply_dispatches_detached_installer_with_env(
    tmp_path: Path, monkeypatch
) -> None:
    """Authenticated apply with an applicable update dispatches the installer
    DETACHED: start_new_session, stdout DEVNULL, stderr a FILE (never a PIPE),
    env carrying DEMIURGOS_URL_BASE + DEMIURGOS_VERSION, and — on an installed
    layout — DEMIURGOS_HOME pinned to the running install root."""
    calls: dict = {}
    install_root = tmp_path / "install"
    install_root.mkdir()

    def fake_popen(argv, **kwargs):
        calls["argv"] = argv
        calls["kwargs"] = kwargs
        return _FakeProc(poll_result=None)  # still running -> accepted

    monkeypatch.setattr(updater.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(updater.time, "sleep", lambda _seconds: None)
    app, _registry = _make_app(
        local_state_path=tmp_path / "local-state.json",
        app_version="0.1.1",
        install_root=install_root,
        channel_fetch=_ChannelStub(latest="0.2.0"),
        install_argv=["/bin/update-installer"],
        install_log=tmp_path / "demiurgos-installer.log",
    )
    resp = TestClient(app).post("/api/update/apply")
    assert resp.status_code == 200
    body = resp.json()
    assert body["action"] == "update"
    assert body["accepted"] is True
    assert body["version"] == "0.2.0"
    assert body["channel"] == "Estable"

    # The installer is dispatched with the fixed argv and detached.
    assert calls["argv"] == ["/bin/update-installer"]
    assert calls["kwargs"]["start_new_session"] is True
    assert calls["kwargs"]["stdout"] is subprocess.DEVNULL
    # The installer OUTLIVES this request; stderr must be a FILE, never a PIPE
    # (a pipe whose reader died kills the installer with SIGPIPE mid-install).
    assert calls["kwargs"]["stderr"] is not subprocess.PIPE
    assert calls["kwargs"]["stderr"] is not subprocess.DEVNULL
    assert Path(calls["kwargs"]["stderr"].name).name == "demiurgos-installer.log"

    # Env-only inputs: channel base + server-resolved version. No shell=True.
    assert "shell" not in calls["kwargs"] or calls["kwargs"]["shell"] is False
    env = calls["kwargs"]["env"]
    assert env["DEMIURGOS_URL_BASE"] == DEFAULT_CHANNEL_URL
    assert env["DEMIURGOS_VERSION"] == "0.2.0"
    assert env["DEMIURGOS_HOME"] == str(install_root)


def test_apply_uses_resolved_url_base_and_server_version(
    tmp_path: Path, monkeypatch
) -> None:
    """The dispatched env reflects the SERVER-resolved channel base and the
    pointer's offered version — never anything client-supplied (no body)."""
    calls: dict = {}
    install_root = tmp_path / "install"
    install_root.mkdir()
    cfg = {"schema_version": 1, "url_base": "https://mirror.example.test/ch"}
    (install_root / "channel.json").write_text(
        json.dumps(cfg) + "\n", encoding="utf-8"
    )

    def fake_popen(argv, **kwargs):
        calls["kwargs"] = kwargs
        return _FakeProc(poll_result=None)

    monkeypatch.setattr(updater.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(updater.time, "sleep", lambda _seconds: None)
    app, _registry = _make_app(
        local_state_path=tmp_path / "local-state.json",
        app_version="0.1.1",
        install_root=install_root,
        channel_fetch=_ChannelStub(latest="0.3.0"),
        install_log=tmp_path / "demiurgos-installer.log",
    )
    client = TestClient(app)
    resp = client.post("/api/update/apply", json={"version": "9.9.9"})
    assert resp.status_code == 200
    # The client body is ignored: the version stays server-resolved.
    assert calls["kwargs"]["env"]["DEMIURGOS_URL_BASE"] == (
        "https://mirror.example.test/ch"
    )
    assert calls["kwargs"]["env"]["DEMIURGOS_VERSION"] == "0.3.0"


def test_apply_none_available_when_fetch_fails(tmp_path: Path, monkeypatch) -> None:
    """An unreachable channel yields 409 update.none_available — nothing is
    dispatched (spec: nothing offered -> 409)."""
    calls: dict = {}

    def fake_popen(argv, **kwargs):
        calls["argv"] = argv
        return _FakeProc(poll_result=None)

    monkeypatch.setattr(updater.subprocess, "Popen", fake_popen)
    app, _registry = _make_app(
        local_state_path=tmp_path / "local-state.json",
        app_version="0.1.1",
        channel_fetch=_ChannelStub(latest="0.2.0", fail=True),
    )
    resp = TestClient(app).post("/api/update/apply")
    assert resp.status_code == 409
    assert resp.json()["code"] == "update.none_available"
    assert "argv" not in calls


def test_apply_none_available_when_offered_is_not_newer(
    tmp_path: Path, monkeypatch
) -> None:
    """The updater never downgrades and never re-installs the same version:
    apply dispatches only when the offered version is STRICTLY greater than
    the running version."""
    calls: dict = {}

    def fake_popen(argv, **kwargs):
        calls["argv"] = argv
        return _FakeProc(poll_result=None)

    monkeypatch.setattr(updater.subprocess, "Popen", fake_popen)
    for current, latest in (
        ("0.2.0", "0.2.0"),      # equal -> not applicable
        ("0.3.0", "0.2.0"),      # downgrade -> never
        ("0.2.0", "0.2.0-beta.1"),  # prerelease below release -> not newer
    ):
        app, _registry = _make_app(
            local_state_path=tmp_path / "local-state.json",
            app_version=current,
            channel_fetch=_ChannelStub(latest=latest),
        )
        resp = TestClient(app).post("/api/update/apply")
        assert resp.status_code == 409, (current, latest)
        assert resp.json()["code"] == "update.none_available", (current, latest)
    assert "argv" not in calls


def test_apply_none_available_when_advisory_unparseable(
    tmp_path: Path, monkeypatch
) -> None:
    """An unparseable advisory is never dispatched: the env version must be
    SemVer-valid before dispatch (defense in depth)."""
    calls: dict = {}

    def fake_popen(argv, **kwargs):
        calls["argv"] = argv
        return _FakeProc(poll_result=None)

    monkeypatch.setattr(updater.subprocess, "Popen", fake_popen)
    app, _registry = _make_app(
        local_state_path=tmp_path / "local-state.json",
        app_version="0.1.1",
        channel_fetch=_ChannelStub(latest="not-a-version"),
    )
    resp = TestClient(app).post("/api/update/apply")
    assert resp.status_code == 409
    assert resp.json()["code"] == "update.none_available"
    assert "argv" not in calls


def test_apply_installer_unavailable_returns_503(tmp_path: Path, monkeypatch) -> None:
    """When the boot-time existence check says the installer is absent, apply
    refuses with 503 and Popen is never called (mirrors the system-control
    launcher_available guard)."""
    calls: dict = {}

    def fake_popen(argv, **kwargs):
        calls["argv"] = argv
        return _FakeProc(poll_result=None)

    monkeypatch.setattr(updater.subprocess, "Popen", fake_popen)
    app, _registry = _make_app(
        local_state_path=tmp_path / "local-state.json",
        app_version="0.1.1",
        channel_fetch=_ChannelStub(latest="0.2.0"),
        install_argv=["/missing/install-demiurgos.sh"],
        install_available=False,
    )
    resp = TestClient(app).post("/api/update/apply")
    assert resp.status_code == 503
    body = resp.json()
    assert body["action"] == "update"
    assert body["accepted"] is False
    assert "installer not available" in body["error"]
    assert "install-demiurgos.sh" in body["error"]
    assert "argv" not in calls, "a missing installer must never be dispatched"


def test_apply_early_failure_returns_500_with_stderr(
    tmp_path: Path, monkeypatch
) -> None:
    """An installer that exits non-zero within the 0.5s peek window surfaces
    as a 500 with its stderr excerpt (spec 'Early failure is reported')."""

    def fake_popen(argv, **kwargs):
        # The installer's stderr is the injected log file; write what a
        # failing installer would have written there.
        kwargs["stderr"].write(b"install-demiurgos: signature check failed\n")
        return _FakeProc(poll_result=3)

    monkeypatch.setattr(updater.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(updater.time, "sleep", lambda _seconds: None)
    app, _registry = _make_app(
        local_state_path=tmp_path / "local-state.json",
        app_version="0.1.1",
        channel_fetch=_ChannelStub(latest="0.2.0"),
        install_log=tmp_path / "demiurgos-installer.log",
    )
    resp = TestClient(app).post("/api/update/apply")
    assert resp.status_code == 500
    body = resp.json()
    assert body["action"] == "update"
    assert body["accepted"] is False
    assert "3" in body["error"]
    assert "signature check failed" in body["error"]


def test_apply_exit_zero_within_peek_is_accepted(tmp_path: Path, monkeypatch) -> None:
    """An installer that finishes with exit 0 within the peek window -> 200
    (mirrors the system-control exit-zero contract)."""

    def fake_popen(argv, **kwargs):
        return _FakeProc(poll_result=0)

    monkeypatch.setattr(updater.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(updater.time, "sleep", lambda _seconds: None)
    app, _registry = _make_app(
        local_state_path=tmp_path / "local-state.json",
        app_version="0.1.1",
        channel_fetch=_ChannelStub(latest="0.2.0"),
    )
    resp = TestClient(app).post("/api/update/apply")
    assert resp.status_code == 200
    assert resp.json()["accepted"] is True


def test_apply_spawn_failure_returns_500(tmp_path: Path, monkeypatch) -> None:
    """A spawn failure (bad path, permission denied) surfaces as a 500, never
    a misleading 'accepted'."""

    def fake_popen(argv, **kwargs):
        raise FileNotFoundError(2, "No such file or directory", argv[0])

    monkeypatch.setattr(updater.subprocess, "Popen", fake_popen)
    app, _registry = _make_app(
        local_state_path=tmp_path / "local-state.json",
        app_version="0.1.1",
        channel_fetch=_ChannelStub(latest="0.2.0"),
        install_argv=["/missing/install-demiurgos.sh"],
    )
    resp = TestClient(app).post("/api/update/apply")
    assert resp.status_code == 500
    body = resp.json()
    assert body["accepted"] is False
    assert "installer" in body["error"]


def test_apply_windows_ps_argv_parity(tmp_path: Path, monkeypatch) -> None:
    """Windows apply dispatches the PowerShell installer with the exact
    `[\"powershell\", \"-NoProfile\", \"-File\", <ps1>]` argv shape (spec
    'PowerShell installer is dispatched on Windows')."""
    calls: dict = {}
    ps1 = "/install/scripts/install-demiurgos.ps1"

    def fake_popen(argv, **kwargs):
        calls["argv"] = argv
        calls["kwargs"] = kwargs
        return _FakeProc(poll_result=None)

    monkeypatch.setattr(updater.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(updater.time, "sleep", lambda _seconds: None)
    app, _registry = _make_app(
        local_state_path=tmp_path / "local-state.json",
        app_version="0.1.1",
        channel_fetch=_ChannelStub(latest="0.2.0"),
        install_argv=["powershell", "-NoProfile", "-File", ps1],
        install_log=tmp_path / "demiurgos-installer.log",
    )
    resp = TestClient(app).post("/api/update/apply")
    assert resp.status_code == 200
    assert calls["argv"] == ["powershell", "-NoProfile", "-File", ps1]
    # Same detached contract on Windows: stderr FILE, never PIPE.
    assert calls["kwargs"]["start_new_session"] is True
    assert calls["kwargs"]["stderr"] is not subprocess.PIPE


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