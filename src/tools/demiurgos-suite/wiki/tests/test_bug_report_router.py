# -*- coding: utf-8 -*-
"""tests/test_bug_report_router.py — ``/api/bugreport`` router (S1b + S1c).

Slice S1b ships the read-only assemble endpoint (``GET
/api/bugreport/assemble``); slice S1c adds the stateless, principal-gated
submit endpoint (``POST /api/bugreport/submit``). The tests cover:

* fail-closed 401 auth for a missing principal (assemble and submit);
* the bundle exposes ONLY allow-listed keys (default-DENY posture);
* world data (``mundos/``), ``.env`` and the local account username are excluded
  BY CONSTRUCTION — the handler opens only ``install_root/logs``;
* a log line matching a shared secret rule is redacted before it can be
  previewed or submitted;
* submit re-validates the raw payload against the allow-list (extra JSON keys
  are REJECTED, not silently dropped), enforces the size caps, applies a
  per-principal rate limit, delivers through the injected relay and persists
  nothing;
* the derived ``payload_manifest.json`` ships both bug-report modules.

The app is hermetic: a bare ``FastAPI()`` with an injected ``require_principal``,
``log_source``, ``relay_post`` and ``clock``, so no real install state, data
root or network is ever touched (mirrors ``test_update_router.py`` /
``test_system_control.py``).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

_HERE = Path(__file__).resolve().parent
_WIKI = _HERE.parent
if str(_WIKI) not in sys.path:
    sys.path.insert(0, str(_WIKI))

from bug_report import (  # noqa: E402
    ALLOWED_FIELDS,
    ALLOWED_PLATFORM_KEYS,
    create_bug_report_router,
)
from error_codes import register_error_handlers  # noqa: E402

AUTH_REQUIRED = {"detail": "Autenticación requerida"}

# Matches the shared ``bot-token`` rule (``[0-9]{8,10}:[A-Za-z0-9_-]{35}``).
BOT_TOKEN = "1234567890:" + "A" * 35

_TOP_LEVEL_KEYS = {"app_version", "platform", "logs", "allow_list", "contact_slot"}

# Repo root: tests/ -> wiki/ -> demiurgos-suite/ -> tools/ -> src/ -> <root>.
_REPO_ROOT = _HERE.parents[4]


class _FakePrincipal:
    def __init__(self, pid: str = "tester"):
        self.id = pid


def _make_app(
    *,
    install_root: Path | None = None,
    log_source=None,
    authed: bool = True,
    app_version: str = "0.2.0",
    relay_url=None,
    relay_post=None,
    clock=None,
) -> FastAPI:
    """Build a hermetic app around the bug-report router.

    ``require_principal`` is a fresh principal per call (``_FakePrincipal`` with
    a stable id ``"tester"``), so the per-principal rate limit is exercised
    across requests. ``register_error_handlers`` renders the structured
    ``{"detail", "code", "params"}`` body so tests can assert the stable code.
    """

    def _require_principal(_request):
        return _FakePrincipal() if authed else None

    app = FastAPI()
    register_error_handlers(app)
    kwargs = {}
    if relay_post is not None:
        kwargs["relay_post"] = relay_post
    if clock is not None:
        kwargs["clock"] = clock
    app.include_router(
        create_bug_report_router(
            _require_principal,
            app_version=lambda: app_version,
            install_root=install_root,
            relay_url=relay_url,
            log_source=log_source,
            **kwargs,
        )
    )
    return app


def _valid_payload(**overrides):
    """A minimal, fully allow-listed submit payload (S1c contract)."""

    payload = {
        "app_version": "0.2.0",
        "platform": {
            "os": "Linux",
            "os_version": "6.0",
            "arch": "x86_64",
            "python_version": "3.12.0",
        },
        "description": "The app crashed while opening a world.",
        "contact": "user@example.com",
        "logs": "server started\nlistening\n",
    }
    payload.update(overrides)
    return payload


def _seed_install_tree(tmp_path: Path) -> Path:
    """Seed a tmp install root with benign logs AND world-data/``.env`` canaries.

    The canaries make the exclusion assertions meaningful: if the assemble
    handler ever read the world-data root or ``.env``, one of them would leak
    into the response.
    """
    install_root = tmp_path / "install"
    (install_root / "logs").mkdir(parents=True)
    (install_root / "logs" / "demiurgos-api.log").write_text(
        "server started\nlistening on http://localhost:8001\n", encoding="utf-8"
    )
    worlds = install_root / "mundos"
    worlds.mkdir()
    (worlds / "secreto.md").write_text(
        "CANARY_WORLD a hidden world body\n", encoding="utf-8"
    )
    (install_root / ".env").write_text(
        "CANARY_ENV=super-secret-value\n", encoding="utf-8"
    )
    return install_root


def _log_source_from(install_root: Path):
    """An injected log source that reads ONLY ``install_root/logs`` (prod shape)."""

    def _source():
        pairs = []
        for path in sorted((install_root / "logs").glob("*.log")):
            pairs.append(
                (path.name, path.read_text(encoding="utf-8", errors="replace"))
            )
        return pairs

    return _source


# ---------------------------------------------------------------------------
# Fail-closed auth (spec: submit/assemble are principal-gated)
# ---------------------------------------------------------------------------


def test_assemble_requires_principal(tmp_path: Path) -> None:
    install_root = _seed_install_tree(tmp_path)
    app = _make_app(
        install_root=install_root,
        log_source=_log_source_from(install_root),
        authed=False,
    )
    resp = TestClient(app).get("/api/bugreport/assemble")
    assert resp.status_code == 401
    assert resp.json() == AUTH_REQUIRED


# ---------------------------------------------------------------------------
# Default-DENY allow-list (spec: 'Assemble returns exactly the allow-listed keys')
# ---------------------------------------------------------------------------


def test_assemble_returns_only_allowlisted_keys(tmp_path: Path) -> None:
    install_root = _seed_install_tree(tmp_path)
    app = _make_app(
        install_root=install_root, log_source=_log_source_from(install_root)
    )
    resp = TestClient(app).get("/api/bugreport/assemble")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # Exactly the allow-listed top-level keys — nothing outside the list.
    assert set(body.keys()) == _TOP_LEVEL_KEYS
    assert set(body["platform"].keys()) <= ALLOWED_PLATFORM_KEYS
    assert set(body["allow_list"]) == set(ALLOWED_FIELDS)
    assert body["app_version"] == "0.2.0"
    # No identity key of any kind is assembled.
    assert "username" not in body
    assert "contact" not in body


# ---------------------------------------------------------------------------
# Exclusion by construction (spec: world data / `.env` / username)
# ---------------------------------------------------------------------------


def test_assemble_excludes_env_world_username(tmp_path: Path) -> None:
    install_root = _seed_install_tree(tmp_path)
    app = _make_app(
        install_root=install_root, log_source=_log_source_from(install_root)
    )
    resp = TestClient(app).get("/api/bugreport/assemble")
    assert resp.status_code == 200, resp.text
    text = resp.text
    # The benign log content IS assembled (proving the logs path is live)...
    assert "server started" in text
    # ...but no world-data, `.env` or username content ever reaches the bundle.
    assert "CANARY_WORLD" not in text
    assert "CANARY_ENV" not in text
    assert "secreto" not in text
    assert "super-secret-value" not in text


# ---------------------------------------------------------------------------
# Secret redaction (spec: 'A log line containing a secret is redacted or blocked')
# ---------------------------------------------------------------------------


def test_assemble_redacts_secret_log_line(tmp_path: Path) -> None:
    def _leaky_source():
        return [
            ("demiurgos-api.log", "boot\nleaked token %s\nready" % BOT_TOKEN),
        ]

    app = _make_app(install_root=tmp_path, log_source=_leaky_source)
    resp = TestClient(app).get("/api/bugreport/assemble")
    assert resp.status_code == 200, resp.text
    logs = resp.json()["logs"]
    assert logs["included"] is True
    # The raw secret never appears; the line is replaced by its rule placeholder.
    assert BOT_TOKEN not in logs["content"]
    assert "[redacted:" in logs["content"]
    assert logs["redacted_lines"] == 1
    # Useful reproduction structure survives around the redacted line.
    assert "boot" in logs["content"]
    assert "ready" in logs["content"]


# ---------------------------------------------------------------------------
# Registration smoke: the production app imports cleanly and exposes the route
# ---------------------------------------------------------------------------


def test_assemble_registered_in_api_server_app() -> None:
    """The production ``api_server`` app registers the assemble route.

    Importing the real app doubles as the clean-import smoke check for the
    ``include_router`` wiring (mirrors ``test_system_control``). The endpoint
    itself is NOT invoked here: against the real app it requires an
    authenticated local session, so registration is asserted through the
    OpenAPI schema instead.
    """
    import api_server  # noqa: F401

    # Included routers are nested behind wrapper objects in app.routes, so the
    # OpenAPI schema is the reliable surface to assert registration.
    paths = api_server.app.openapi()["paths"]
    assert "/api/bugreport/assemble" in paths
    assert "/api/bugreport/submit" in paths


# ---------------------------------------------------------------------------
# Slice S1c — POST /api/bugreport/submit
# ---------------------------------------------------------------------------


def test_submit_requires_principal() -> None:
    """No principal -> 401, and NO delivery is attempted (fail closed)."""
    calls = []

    def _relay(url, payload):
        calls.append((url, payload))
        return 200, {"ok": True, "delivery_id": "d1"}

    app = _make_app(authed=False, relay_url="http://relay.test", relay_post=_relay)
    resp = TestClient(app).post("/api/bugreport/submit", json=_valid_payload())
    assert resp.status_code == 401
    assert resp.json() == AUTH_REQUIRED
    assert calls == []


def test_submit_rejects_disallowed_field() -> None:
    """Extra JSON keys are REJECTED via raw-dict validation, never dropped.

    The design forbids a default Pydantic model precisely because it silently
    drops unknown keys and would let this scenario pass through.
    """
    calls = []

    def _relay(url, payload):
        calls.append((url, payload))
        return 200, {"ok": True, "delivery_id": "d1"}

    app = _make_app(relay_url="http://relay.test", relay_post=_relay)
    client = TestClient(app)

    # Top-level key outside the allow-list.
    resp = client.post(
        "/api/bugreport/submit",
        json=_valid_payload(world_data="CANARY_WORLD secret world body"),
    )
    assert resp.status_code == 400, resp.text
    assert resp.json()["code"] == "bugreport.not_allowlisted"

    # Nested platform key outside its allow-list.
    resp = client.post(
        "/api/bugreport/submit",
        json=_valid_payload(platform={"os": "Linux", "token": "leak"}),
    )
    assert resp.status_code == 400, resp.text
    assert resp.json()["code"] == "bugreport.not_allowlisted"

    # Neither rejected request reached the relay.
    assert calls == []


def test_submit_rejects_oversized() -> None:
    """Per-field size caps reject oversized payloads with the distinct code."""
    calls = []

    def _relay(url, payload):
        calls.append((url, payload))
        return 200, {"ok": True, "delivery_id": "d1"}

    app = _make_app(relay_url="http://relay.test", relay_post=_relay)
    client = TestClient(app)

    too_long_description = client.post(
        "/api/bugreport/submit",
        json=_valid_payload(description="x" * 4001),
    )
    assert too_long_description.status_code == 413, too_long_description.text
    assert too_long_description.json()["code"] == "bugreport.too_large"

    too_long_logs = client.post(
        "/api/bugreport/submit",
        json=_valid_payload(logs="x" * 65537),
    )
    assert too_long_logs.status_code == 413, too_long_logs.text
    assert too_long_logs.json()["code"] == "bugreport.too_large"

    assert calls == []


def test_submit_rate_limited() -> None:
    """A principal is limited to 5 submits per 600 s (lazily pruned by clock)."""
    clock_state = {"t": 1000.0}

    def _clock():
        return clock_state["t"]

    def _relay(url, payload):
        return 200, {"ok": True, "delivery_id": "d1"}

    app = _make_app(
        relay_url="http://relay.test", relay_post=_relay, clock=_clock
    )
    client = TestClient(app)

    for _ in range(5):
        resp = client.post("/api/bugreport/submit", json=_valid_payload())
        assert resp.status_code == 200, resp.text

    blocked = client.post("/api/bugreport/submit", json=_valid_payload())
    assert blocked.status_code == 429, blocked.text
    assert blocked.json()["code"] == "bugreport.rate_limited"

    # Once the window has slid past the oldest hit, the principal is unblocked.
    clock_state["t"] = 1000.0 + 601.0
    allowed_again = client.post("/api/bugreport/submit", json=_valid_payload())
    assert allowed_again.status_code == 200, allowed_again.text


def test_submit_relay_down_fails_closed() -> None:
    """Unreachable / misconfigured relay and relay-reported failure fail closed.

    Unreachable or unconfigured -> ``bugreport.relay_unavailable``; a relay that
    answers but reports ``ok:false`` -> ``bugreport.delivery_failed``. No secret
    or traceback is ever leaked in the response.
    """
    def _unreachable(url, payload):
        raise ConnectionError("relay unreachable: http://relay.test")

    app = _make_app(relay_url="http://relay.test", relay_post=_unreachable)
    resp = TestClient(app).post("/api/bugreport/submit", json=_valid_payload())
    assert resp.status_code == 502, resp.text
    assert resp.json()["code"] == "bugreport.relay_unavailable"
    assert "relay.test" not in resp.text

    # Misconfigured: no relay URL wired -> unavailable without any call.
    unconfigured = _make_app(relay_url=None)
    resp = TestClient(unconfigured).post(
        "/api/bugreport/submit", json=_valid_payload()
    )
    assert resp.status_code == 502, resp.text
    assert resp.json()["code"] == "bugreport.relay_unavailable"

    # Relay answered but reported failure.
    def _reports_failure(url, payload):
        return 200, {"ok": False, "code": "provider_error"}

    failing = _make_app(relay_url="http://relay.test", relay_post=_reports_failure)
    resp = TestClient(failing).post(
        "/api/bugreport/submit", json=_valid_payload()
    )
    assert resp.status_code == 502, resp.text
    assert resp.json()["code"] == "bugreport.delivery_failed"


def test_submit_success_stores_nothing(tmp_path: Path) -> None:
    """A successful submit returns ``{ok, delivery_id}`` and persists nothing.

    The relay receives the vendor-neutral contract; no report, copy or derived
    record is written to the install tree.
    """
    install_root = _seed_install_tree(tmp_path)
    before = sorted(p.relative_to(install_root) for p in install_root.rglob("*"))
    captured = {}

    def _relay(url, payload):
        captured["url"] = url
        captured["payload"] = payload
        return 200, {"ok": True, "delivery_id": "delivery-42"}

    app = _make_app(
        install_root=install_root,
        relay_url="http://relay.test",
        relay_post=_relay,
    )
    resp = TestClient(app).post("/api/bugreport/submit", json=_valid_payload())
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"ok": True, "delivery_id": "delivery-42"}

    # Nothing about the report is persisted server-side (stateless submit).
    after = sorted(p.relative_to(install_root) for p in install_root.rglob("*"))
    assert after == before

    # The relay received the fixed, vendor-neutral contract.
    assert captured["url"] == "http://relay.test"
    assert set(captured["payload"].keys()) == {
        "schema",
        "app_version",
        "platform",
        "description",
        "contact",
        "logs",
    }
    assert captured["payload"]["schema"] == 1
    assert captured["payload"]["description"] == _valid_payload()["description"]


# ---------------------------------------------------------------------------
# Manifest: the derived payload ships both bug-report modules (task 3.7)
# ---------------------------------------------------------------------------


def test_payload_manifest_includes_bug_report_modules() -> None:
    """``payload_manifest.json`` includes the new modules under ``payload``.

    Guards the in-app-updater lesson: a module shipped but missing from the
    derived manifest fails at import time on the installed build.
    """
    manifest = json.loads(
        (_REPO_ROOT / "payload_manifest.json").read_text(encoding="utf-8")
    )
    payload = manifest["payload"]
    assert "src/tools/demiurgos-suite/wiki/bug_report.py" in payload
    assert "src/tools/demiurgos-suite/wiki/content_scan.py" in payload
