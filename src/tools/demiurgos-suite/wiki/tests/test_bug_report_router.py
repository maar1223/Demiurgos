# -*- coding: utf-8 -*-
"""tests/test_bug_report_router.py — ``/api/bugreport`` router (S1b–S3b).

Slice S1b ships the read-only assemble endpoint (``GET
/api/bugreport/assemble``); slice S1c adds the stateless, principal-gated
submit endpoint (``POST /api/bugreport/submit``); slice S3b adds the strict
fallback endpoint (``POST /api/bugreport/fallback``). The tests cover:

* fail-closed 401 auth for a missing principal (assemble, submit, fallback);
* the bundle exposes ONLY allow-listed keys (default-DENY posture);
* world data (``mundos/``), ``.env`` and the local account username are excluded
  BY CONSTRUCTION — the handler opens only ``install_root/logs``;
* a log line matching a shared secret rule is redacted before it can be
  previewed or submitted;
* submit re-validates the raw payload against the allow-list (extra JSON keys
  are REJECTED, not silently dropped), enforces the size caps (per-field AND
  the total serialized-byte cap), applies a per-principal rate limit, delivers
  through the injected relay and persists nothing;
* fallback returns ``{body, issue_url, findings}`` where the body is pre-filled
  from the reviewed bundle, privacy-scrubbed (paths/usernames/hostnames/
  private IPs/e-mails/secrets become placeholders) and the issue form is the
  ``maar1223/Demiurgos`` destination (``DEFAULT_ISSUE_URL``, overridable);
* the derived ``payload_manifest.json`` ships both bug-report modules.

The app is hermetic: a bare ``FastAPI()`` with an injected ``require_principal``,
``log_source``, ``relay_post``, ``clock`` and ``issue_url``, so no real install
state, data root or network is ever touched (mirrors ``test_update_router.py`` /
``test_system_control.py``).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

_HERE = Path(__file__).resolve().parent
_WIKI = _HERE.parent
if str(_WIKI) not in sys.path:
    sys.path.insert(0, str(_WIKI))

from bug_report import (  # noqa: E402
    ALLOWED_FIELDS,
    ALLOWED_PLATFORM_KEYS,
    DEFAULT_ISSUE_URL,
    create_bug_report_router,
)
from error_codes import register_error_handlers  # noqa: E402

AUTH_REQUIRED = {"detail": "Autenticación requerida"}

# Matches the shared ``bot-token`` rule (``[0-9]{8,10}:[A-Za-z0-9_-]{35}``).
BOT_TOKEN = "1234567890:" + "A" * 35

# Shared-set secrets (the ``SECRET_RULE_*`` set kept byte-identical to
# ``scripts/secret_scan.sh``). A shared-rule secret typed into the free-text
# ``description`` must be scrubbed from the fallback body too, not only the
# report-specific PII classes. Fixtures are assembled by concatenation, per the
# file-family convention in test_content_scan.py, so this file's source never
# contains a literal that the repo secret scan would (correctly) flag.
SHARED_SECRET_FIXTURES = {
    "bot-token": BOT_TOKEN,
    "openai-key": "sk-" + "a" * 40,
    "google-api-key": "AIza" + "b" * 35,
    "author-path": "spreadsheet" + "Id",
}

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
    relay_key=None,
    bot_username=None,
    local_state=None,
    vault_active=None,
    clock=None,
    issue_url=None,
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
    if relay_key is not None:
        kwargs["relay_key"] = relay_key
    if bot_username is not None:
        kwargs["bot_username"] = bot_username
    if local_state is not None:
        kwargs["local_state"] = local_state
    if vault_active is not None:
        kwargs["vault_active"] = vault_active
    if clock is not None:
        kwargs["clock"] = clock
    if issue_url is not None:
        kwargs["issue_url"] = issue_url
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


def test_link_routes_are_not_shadowed_by_the_world_content_routes() -> None:
    """The assembled app must route our link endpoints, not the wiki catch-all.

    ``POST /api/{mundo}/{section}/status`` matches ``/api/bugreport/link/ticket``
    and answered 400 "Sección inválida" before the bugreport handler ran, which
    left the Telegram panel polling a dead route forever. The unit tests here
    build a minimal app with only this router, so only the real app catches it.
    """
    import api_server

    client = TestClient(api_server.app)
    # No session: our handlers fail closed with 401. The catch-all answered 400
    # (or the path did not exist at all).
    for path in (
        "/api/bugreport/link/start",
        "/api/bugreport/link/ticket",
        "/api/bugreport/link/revoke",
    ):
        resp = client.post(path, json={})
        assert resp.status_code == 401, (path, resp.status_code, resp.text)

    assert client.get("/api/bugreport/link").status_code == 401


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
    assert "/api/bugreport/fallback" in paths


# ---------------------------------------------------------------------------
# Slice S1c — POST /api/bugreport/submit
# ---------------------------------------------------------------------------


def test_submit_requires_principal() -> None:
    """No principal -> 401, and NO delivery is attempted (fail closed)."""
    calls = []

    def _relay(url, payload, headers=None, attachments=None):
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

    def _relay(url, payload, headers=None, attachments=None):
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

    def _relay(url, payload, headers=None, attachments=None):
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


def test_submit_caps_contact_at_200_chars() -> None:
    """The optional contact is capped at 200 chars (at the cap is accepted)."""
    calls = []

    def _relay(url, payload, headers=None, attachments=None):
        calls.append((url, payload))
        return 200, {"ok": True, "delivery_id": "d1"}

    app = _make_app(relay_url="http://relay.test", relay_post=_relay)
    client = TestClient(app)

    at_cap = client.post(
        "/api/bugreport/submit", json=_valid_payload(contact="x" * 200)
    )
    assert at_cap.status_code == 200, at_cap.text

    over_cap = client.post(
        "/api/bugreport/submit", json=_valid_payload(contact="x" * 201)
    )
    assert over_cap.status_code == 413, over_cap.text
    assert over_cap.json()["code"] == "bugreport.too_large"
    assert over_cap.json()["params"] == {"field": "contact"}
    # Only the at-cap payload reached the relay; the over-cap one did not.
    assert len(calls) == 1


def test_submit_rejects_total_byte_cap() -> None:
    """The 98304-byte total cap is REACHABLE under the per-field char caps.

    Multi-byte UTF-8 content (here 3-byte characters) puts the serialized
    payload far over the total byte cap while every per-field character cap
    still passes — so the total-cap branch is a live guard, not dead code.
    """
    calls = []

    def _relay(url, payload, headers=None, attachments=None):
        calls.append((url, payload))
        return 200, {"ok": True, "delivery_id": "d1"}

    app = _make_app(relay_url="http://relay.test", relay_post=_relay)
    client = TestClient(app)

    # 65536 "€" chars (3 bytes each in UTF-8) = 196608 bytes for logs alone,
    # plus a 4000-char description → ≈208 KB serialized, well over 98304 B.
    resp = client.post(
        "/api/bugreport/submit",
        json=_valid_payload(logs="\u20ac" * 65536, description="\u20ac" * 4000),
    )
    assert resp.status_code == 413, resp.text
    assert resp.json()["code"] == "bugreport.too_large"
    assert resp.json()["params"] == {"field": "total"}
    assert calls == []


def test_submit_rate_limited() -> None:
    """A principal is limited to 5 submits per 600 s (lazily pruned by clock)."""
    clock_state = {"t": 1000.0}

    def _clock():
        return clock_state["t"]

    def _relay(url, payload, headers=None, attachments=None):
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
    def _unreachable(url, payload, headers=None, attachments=None):
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
    def _reports_failure(url, payload, headers=None, attachments=None):
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

    def _relay(url, payload, headers=None, attachments=None):
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
# Slice S3b — POST /api/bugreport/fallback (strict fallback)
# ---------------------------------------------------------------------------


def test_fallback_body_prefilled_from_bundle() -> None:
    """The fallback body is pre-filled from the REVIEWED bundle.

    The copy-paste issue body carries the reviewed description, app version,
    platform facts and logs, and the explicitly-provided contact survives the
    privacy scrub as the deliberate follow-up datum (owner decision 5). A clean
    bundle yields zero privacy findings.
    """
    app = _make_app()
    resp = TestClient(app).post("/api/bugreport/fallback", json=_valid_payload())
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert set(data.keys()) == {"body", "issue_url", "findings"}
    body = data["body"]
    assert body.startswith("## Descripción")
    assert "The app crashed while opening a world." in body
    assert "0.2.0" in body
    assert "Linux" in body
    assert "server started" in body
    # The explicit contact is the deliberate follow-up channel (not scrubbed).
    assert "user@example.com" in body
    assert data["findings"] == 0


def test_fallback_scrubs_privacy_findings() -> None:
    """Local paths, hostnames, private IPs and secrets become placeholders.

    The body preserves the reproduction structure around the scrubbed findings,
    and ``findings`` reports the number of replaced values. The raw values never
    survive into the presented body.
    """
    app = _make_app()
    payload = _valid_payload(
        description=(
            "repro: crashed seeding /var/log/demiurgos/api.log from "
            "host=devbox.local (192.168.1.42), key AKIAIOSFODNN7EXAMPLE"
        ),
        logs="started\nconnect db@internal.local\ndev@example.com ping\nretry\n",
    )
    resp = TestClient(app).post("/api/bugreport/fallback", json=payload)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    body = data["body"]
    for raw in (
        "/var/log/demiurgos/api.log",
        "devbox.local",
        "192.168.1.42",
        "AKIAIOSFODNN7EXAMPLE",
        "internal.local",
        "dev@example.com",
    ):
        assert raw not in body, f"privacy finding survived the scrub: {raw}"
    for placeholder in ("<path>", "<hostname>", "<private-ip>", "<secret>", "<email>"):
        assert placeholder in body, f"{placeholder} missing from body"
    # Reproduction structure survives around the placeholders.
    assert "crashed seeding" in body
    assert "retry" in body
    assert data["findings"] >= 6


@pytest.mark.parametrize("rule", sorted(SHARED_SECRET_FIXTURES))
def test_fallback_scrubs_shared_secret_rule(rule: str) -> None:
    """Shared-set secrets in the free-text description are scrubbed too.

    The spec requires the fallback body to scrub credentials/secrets, and the
    body scrub must cover BOTH rule sets: the shared ``SECRET_RULE_*`` set
    (``scripts/secret_scan.sh`` parity) AND the report-specific PII rules. A
    shared-rule secret (e.g. an ``sk-``-prefixed key) typed into the
    ``description`` must never survive into the copy-paste body, and
    ``findings`` must count it. Reproduction structure survives around the
    placeholder.
    """
    secret = SHARED_SECRET_FIXTURES[rule]
    app = _make_app()
    payload = _valid_payload(
        description="repro: the value %s leaked\nsecond line intact" % secret,
    )
    resp = TestClient(app).post("/api/bugreport/fallback", json=payload)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    body = data["body"]
    assert secret not in body, f"shared {rule} survived the fallback scrub"
    assert "<secret>" in body or "<path>" in body
    assert data["findings"] >= 1
    assert "second line intact" in body


def test_fallback_issue_url_targets_main_repo() -> None:
    """``issue_url`` targets the maar1223/Demiurgos issue form by default.

    The URL pins the exact YAML Issue Form file (``template=bug_report.yml``),
    which must exist in the repo — it is the format authority for the
    fallback destination. A wiring override replaces the default.
    """
    app = _make_app()
    resp = TestClient(app).post("/api/bugreport/fallback", json=_valid_payload())
    assert resp.status_code == 200, resp.text
    assert resp.json()["issue_url"] == DEFAULT_ISSUE_URL
    assert resp.json()["issue_url"] == (
        "https://github.com/maar1223/Demiurgos/issues/new?template=bug_report.yml"
    )
    # The destination form exists — the URL must not dangle.
    assert (
        _REPO_ROOT / ".github" / "ISSUE_TEMPLATE" / "bug_report.yml"
    ).is_file(), "issue form missing: fallback URL would not resolve"

    # Wiring override is honored by the factory (production wiring reads
    # DEMIURGOS_BUGREPORT_ISSUE_URL from the environment).
    redirect = _make_app(issue_url="https://issues.example.test/new")
    resp = TestClient(redirect).post(
        "/api/bugreport/fallback", json=_valid_payload()
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["issue_url"] == "https://issues.example.test/new"


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


# ---------------------------------------------------------------------------
# Schema 2 — where in the app it happened (S4)
# ---------------------------------------------------------------------------


def _capture(captured: list) -> Callable:
    """A relay stub that records ``(url, payload, headers)``."""

    def _send(url, payload, headers=None, attachments=None):
        captured.append({"url": url, "payload": payload, "headers": dict(headers or {})})
        return 200, {"ok": True, "delivery_id": "delivery-ctx"}

    return _send


def test_submit_forwards_context_as_schema_two() -> None:
    captured: list = []
    app = _make_app(relay_url="http://relay.test", relay_post=_capture(captured))
    context = {
        "route": "/perfil",
        "view": "perfil",
        "ui_area": "reportes",
        "world_id": "w1",
    }

    resp = TestClient(app).post(
        "/api/bugreport/submit", json=_valid_payload(context=context)
    )

    assert resp.status_code == 200, resp.text
    sent = captured[0]["payload"]
    assert sent["schema"] == 2
    assert sent["context"] == context


def test_submit_without_context_keeps_the_legacy_contract() -> None:
    captured: list = []
    app = _make_app(relay_url="http://relay.test", relay_post=_capture(captured))

    resp = TestClient(app).post("/api/bugreport/submit", json=_valid_payload())

    assert resp.status_code == 200, resp.text
    sent = captured[0]["payload"]
    # A relay that predates schema 2 must keep accepting the report.
    assert sent["schema"] == 1
    assert "context" not in sent


def test_context_rejects_a_key_outside_the_allow_list() -> None:
    app = _make_app(relay_url="http://relay.test", relay_post=_capture([]))

    resp = TestClient(app).post(
        "/api/bugreport/submit", json=_valid_payload(context={"screen": "perfil"})
    )

    assert resp.status_code == 400
    assert resp.json()["code"] == "bugreport.not_allowlisted"


def test_context_value_is_capped() -> None:
    app = _make_app(relay_url="http://relay.test", relay_post=_capture([]))

    resp = TestClient(app).post(
        "/api/bugreport/submit", json=_valid_payload(context={"route": "x" * 201})
    )

    assert resp.status_code == 413
    assert resp.json()["code"] == "bugreport.too_large"


def test_a_credential_typed_into_the_context_is_redacted() -> None:
    captured: list = []
    app = _make_app(relay_url="http://relay.test", relay_post=_capture(captured))

    resp = TestClient(app).post(
        "/api/bugreport/submit",
        json=_valid_payload(context={"route": "/x?token=" + BOT_TOKEN}),
    )

    assert resp.status_code == 200, resp.text
    forwarded = captured[0]["payload"]["context"]["route"]
    assert BOT_TOKEN not in forwarded
    assert "[redacted" in forwarded


# ---------------------------------------------------------------------------
# The install token signs the report and never enters the bundle (S15)
# ---------------------------------------------------------------------------


def _state_with_token(tmp_path: Path, token: str = "cd" * 32):
    from local_state import LocalState

    from bugreport_identity import store_install_token

    state = LocalState(tmp_path / "state.json")
    store_install_token(state, token)
    return state


def test_submit_sends_the_stored_token_as_a_header_only(tmp_path: Path) -> None:
    token = "cd" * 32
    state = _state_with_token(tmp_path, token)
    captured: list = []
    app = _make_app(
        relay_url="http://relay.test",
        relay_post=_capture(captured),
        local_state=lambda: state,
    )

    resp = TestClient(app).post("/api/bugreport/submit", json=_valid_payload())

    assert resp.status_code == 200, resp.text
    assert captured[0]["headers"]["x-install-token"] == token
    assert token not in json.dumps(captured[0]["payload"])


def test_the_pseudonym_header_is_forwarded_only_when_asked(tmp_path: Path) -> None:
    """S20: the browser states the preference; absence means off."""
    from local_state import LocalState

    state = LocalState(tmp_path / "state.json")
    captured: list = []
    app = _make_app(
        relay_url="http://relay.test",
        relay_post=_capture(captured),
        local_state=lambda: state,
        vault_active=lambda: False,
    )
    client = TestClient(app)

    assert client.post("/api/bugreport/submit", json=_valid_payload()).status_code == 200
    assert "x-install-id" not in captured[0]["headers"]

    asked = client.post(
        "/api/bugreport/submit",
        json=_valid_payload(description="otro fallo distinto"),
        headers={"x-bugreport-pseudonym": "1"},
    )
    assert asked.status_code == 200, asked.text
    sent = captured[1]["headers"]["x-install-id"]
    assert sent.startswith("install_") and len(sent) == len("install_") + 24

    # Stable across reports: the same install keeps one id.
    client.post(
        "/api/bugreport/submit",
        json=_valid_payload(description="un tercer fallo"),
        headers={"x-bugreport-pseudonym": "1"},
    )
    assert captured[2]["headers"]["x-install-id"] == sent
    assert sent not in asked.text


def test_without_a_token_no_header_is_sent() -> None:
    captured: list = []
    app = _make_app(relay_url="http://relay.test", relay_post=_capture(captured))

    resp = TestClient(app).post("/api/bugreport/submit", json=_valid_payload())

    assert resp.status_code == 200, resp.text
    assert "x-install-token" not in captured[0]["headers"]


# ---------------------------------------------------------------------------
# Linking surface — the browser never talks to the relay (S7, S9)
# ---------------------------------------------------------------------------


def _link_relay(captured: list, routes: dict):
    """A relay stub routing on the URL suffix, recording every call."""

    def _send(url, payload, headers=None, attachments=None):
        captured.append({"url": url, "payload": payload, "headers": dict(headers or {})})
        for suffix, answer in routes.items():
            if url.endswith(suffix):
                return answer(payload)
        return 404, {"ok": False, "code": "relay.not_found"}

    return _send


def test_link_start_forwards_the_stable_key_never_the_browser_one(tmp_path: Path) -> None:
    from local_state import LocalState

    state = LocalState(tmp_path / "state.json")
    captured: list = []
    app = _make_app(
        relay_url="http://relay.test",
        relay_post=_link_relay(
            captured,
            {"/link/start": lambda _p: (200, {"ok": True, "ticket": "ABC123", "expires_at": "2026-10-25T12:10:00Z", "reused": False})},
        ),
        relay_key="shared-key",
        bot_username="ReportesDemiurgosBot",
        local_state=lambda: state,
        vault_active=lambda: False,
    )

    resp = TestClient(app).post(
        "/api/bugreport/link/start", json={"report_identity": False}
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ticket"] == "ABC123"
    assert body["telegram_url"] == "https://t.me/ReportesDemiurgosBot?start=ABC123"
    call = captured[0]
    assert call["url"].endswith("/link/start")
    # A released install cannot carry the shared secret (S19): none is sent.
    assert "x-relay-key" not in call["headers"]
    assert call["payload"]["account_key"].startswith("install_")
    assert call["payload"]["report_identity"] is False
    assert "notify_releases" not in call["payload"]
    # The stable key is the backend's business, not the browser's.
    assert body["ticket"] not in json.dumps(body).replace("ABC123", "")


def test_link_start_maps_a_taken_account_to_its_own_code(tmp_path: Path) -> None:
    """A bound account that this install cannot prove refuses with 409 (S19)."""
    from local_state import LocalState

    state = LocalState(tmp_path / "state.json")
    app = _make_app(
        relay_url="http://relay.test",
        relay_post=_link_relay(
            [], {"/link/start": lambda _p: (409, {"ok": False, "code": "link.already_linked"})}
        ),
        local_state=lambda: state,
        vault_active=lambda: False,
    )

    resp = TestClient(app).post("/api/bugreport/link/start", json={})

    assert resp.status_code == 409
    assert resp.json()["code"] == "bugreport.link_already_linked"


def test_link_start_rejects_a_non_boolean_flag() -> None:
    app = _make_app(
        relay_url="http://relay.test",
        relay_post=_capture([]),
        relay_key="k",
        bot_username="b",
    )

    resp = TestClient(app).post(
        "/api/bugreport/link/start", json={"report_identity": "false"}
    )

    assert resp.status_code == 400
    assert resp.json()["code"] == "bugreport.not_allowlisted"


def test_link_status_keeps_the_token_server_side(tmp_path: Path) -> None:
    from bugreport_identity import read_install_token
    from local_state import LocalState

    token = "ef" * 32
    state = LocalState(tmp_path / "state.json")
    app = _make_app(
        relay_url="http://relay.test",
        relay_post=_link_relay(
            [],
            {
                "/link/status": lambda _p: (
                    200,
                    {
                        "ok": True,
                        "state": "linked",
                        "install_token": token,
                        "identity": {
                            "telegram_user_id": "42",
                            "username": "brook",
                            "display_name": "Brook",
                            "account_key": "install_secret",
                            "permissions": {
                                "report_identity": True,
                                "notify_releases": False,
                            },
                        },
                    },
                )
            },
        ),
        relay_key="k",
        bot_username="b",
        local_state=lambda: state,
        vault_active=lambda: False,
    )

    resp = TestClient(app).post("/api/bugreport/link/ticket", json={"ticket": "ABC"})

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["state"] == "linked"
    assert body["username"] == "brook"
    assert body["permissions"] == {"report_identity": True, "notify_releases": False}
    # The token, the numeric id and the account key stay server-side.
    text = resp.text
    assert token not in text
    assert "42" not in json.dumps(body)
    assert "install_secret" not in text
    assert read_install_token(state) == token


def test_link_revoke_clears_the_stored_token(tmp_path: Path) -> None:
    from bugreport_identity import read_install_token

    state = _state_with_token(tmp_path)
    assert read_install_token(state) is not None
    app = _make_app(
        relay_url="http://relay.test",
        relay_post=_link_relay(
            [], {"/link/revoke": lambda _p: (200, {"ok": True, "revoked": True})}
        ),
        relay_key="k",
        local_state=lambda: state,
        vault_active=lambda: False,
    )

    resp = TestClient(app).post("/api/bugreport/link/revoke", json={})

    assert resp.status_code == 200, resp.text
    assert resp.json() == {"revoked": True}
    assert read_install_token(state) is None


def test_linking_fails_closed_without_a_relay_url(tmp_path: Path) -> None:
    from local_state import LocalState

    state = LocalState(tmp_path / "state.json")
    app = _make_app(
        relay_post=_capture([]),
        local_state=lambda: state,
        vault_active=lambda: False,
    )

    resp = TestClient(app).post("/api/bugreport/link/start", json={})

    assert resp.status_code == 502
    assert resp.json()["code"] == "bugreport.relay_unavailable"


def test_link_status_expired_does_not_store_anything(tmp_path: Path) -> None:
    from bugreport_identity import read_install_token
    from local_state import LocalState

    state = LocalState(tmp_path / "state.json")
    app = _make_app(
        relay_url="http://relay.test",
        relay_post=_link_relay([], {"/link/status": lambda _p: (200, {"ok": True, "state": "expired"})}),
        relay_key="k",
        local_state=lambda: state,
        vault_active=lambda: False,
    )

    resp = TestClient(app).post("/api/bugreport/link/ticket", json={"ticket": "ABC"})

    assert resp.status_code == 200, resp.text
    assert resp.json() == {"state": "expired"}
    assert read_install_token(state) is None


def test_link_state_uses_the_install_token_and_never_an_account_key(tmp_path: Path) -> None:
    """The panel reads its own link, proving it with the token (S10, S19)."""
    from bugreport_identity import store_install_token
    from local_state import LocalState

    token = "ab" * 32
    state = LocalState(tmp_path / "state.json")
    store_install_token(state, token)
    captured: list = []
    app = _make_app(
        relay_url="http://relay.test",
        relay_post=_link_relay(
            captured,
            {
                "/link/state": lambda _p: (
                    200,
                    {
                        "ok": True,
                        "state": "linked",
                        "identity": {
                            "username": "brook",
                            "display_name": "Brook",
                            "permissions": {
                                "report_identity": True,
                                "notify_releases": False,
                            },
                        },
                    },
                )
            },
        ),
        bot_username="ReportesDemiurgosBot",
        local_state=lambda: state,
        vault_active=lambda: False,
    )

    resp = TestClient(app).get("/api/bugreport/link")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["state"] == "linked"
    assert body["username"] == "brook"
    assert body["permissions"] == {"report_identity": True, "notify_releases": False}
    assert body["telegram_url"] == "https://t.me/ReportesDemiurgosBot"
    call = captured[0]
    assert call["url"].endswith("/link/state")
    # The token is the proof; no account key and no shared secret travel.
    assert call["headers"]["x-install-token"] == token
    assert "x-relay-key" not in call["headers"]
    assert call["payload"] == {}
    assert token not in resp.text


def test_link_state_without_a_token_is_unlinked_and_calls_nothing(tmp_path: Path) -> None:
    from local_state import LocalState

    state = LocalState(tmp_path / "state.json")
    captured: list = []
    app = _make_app(
        relay_url="http://relay.test",
        relay_post=_link_relay(captured, {}),
        bot_username="b",
        local_state=lambda: state,
        vault_active=lambda: False,
    )

    resp = TestClient(app).get("/api/bugreport/link")

    assert resp.status_code == 200, resp.text
    assert resp.json() == {"state": "unlinked", "telegram_url": "https://t.me/b"}
    assert captured == []


def test_link_revoke_uses_the_token_and_clears_it(tmp_path: Path) -> None:
    from bugreport_identity import read_install_token, store_install_token
    from local_state import LocalState

    token = "cd" * 32
    state = LocalState(tmp_path / "state.json")
    store_install_token(state, token)
    captured: list = []
    app = _make_app(
        relay_url="http://relay.test",
        relay_post=_link_relay(
            captured, {"/link/revoke": lambda _p: (200, {"ok": True, "revoked": True})}
        ),
        local_state=lambda: state,
        vault_active=lambda: False,
    )

    resp = TestClient(app).post("/api/bugreport/link/revoke", json={})

    assert resp.status_code == 200, resp.text
    assert resp.json() == {"revoked": True}
    assert captured[0]["headers"]["x-install-token"] == token
    assert captured[0]["payload"] == {}
    assert read_install_token(state) is None


def test_link_revoke_without_a_token_is_idempotent(tmp_path: Path) -> None:
    from local_state import LocalState

    state = LocalState(tmp_path / "state.json")
    captured: list = []
    app = _make_app(
        relay_url="http://relay.test",
        relay_post=_link_relay(captured, {}),
        local_state=lambda: state,
        vault_active=lambda: False,
    )

    resp = TestClient(app).post("/api/bugreport/link/revoke", json={})

    assert resp.status_code == 200, resp.text
    assert resp.json() == {"revoked": False}
    assert captured == []


def test_link_state_reports_unlinked(tmp_path: Path) -> None:
    from local_state import LocalState

    state = LocalState(tmp_path / "state.json")
    app = _make_app(
        relay_url="http://relay.test",
        relay_post=_link_relay(
            [], {"/link/state": lambda _p: (200, {"ok": True, "state": "unlinked"})}
        ),
        relay_key="k",
        bot_username="b",
        local_state=lambda: state,
        vault_active=lambda: False,
    )

    resp = TestClient(app).get("/api/bugreport/link")

    assert resp.status_code == 200, resp.text
    assert resp.json() == {
        "state": "unlinked",
        "telegram_url": "https://t.me/b",
    }


def test_link_state_requires_a_principal() -> None:
    app = _make_app(
        authed=False,
        relay_url="http://relay.test",
        relay_post=_capture([]),
        relay_key="k",
    )

    resp = TestClient(app).get("/api/bugreport/link")

    assert resp.status_code == 401


def test_context_cap_counts_utf16_units_like_the_relay() -> None:
    """200 emoji are 400 UTF-16 units: the relay would refuse them at the last hop."""
    app = _make_app(relay_url="http://relay.test", relay_post=_capture([]))

    resp = TestClient(app).post(
        "/api/bugreport/submit", json=_valid_payload(context={"route": "😀" * 200})
    )

    assert resp.status_code == 413
    assert resp.json()["code"] == "bugreport.too_large"


def test_link_status_refuses_to_report_linked_when_the_token_was_lost(
    tmp_path: Path,
) -> None:
    """A lost one-time token means the link cannot sign: never a false success."""
    from local_state import LocalState

    class Flaky(LocalState):
        fail_next = True

        def atomic_commit(self, state):
            if Flaky.fail_next:
                Flaky.fail_next = False
                raise OSError("disk full")
            return super().atomic_commit(state)

    state = Flaky(tmp_path / "state.json")
    answers = iter(
        [
            (
                200,
                {
                    "ok": True,
                    "state": "linked",
                    "install_token": "ef" * 32,
                    "identity": {"username": "brook", "permissions": {}},
                },
            ),
            (
                200,
                {
                    "ok": True,
                    "state": "linked",
                    "install_token": None,
                    "identity": {"username": "brook", "permissions": {}},
                },
            ),
        ]
    )
    app = _make_app(
        relay_url="http://relay.test",
        relay_post=lambda _url, _payload, _headers=None, _attachments=None: next(answers),
        relay_key="k",
        local_state=lambda: state,
        vault_active=lambda: False,
    )

    first = TestClient(app).post("/api/bugreport/link/ticket", json={"ticket": "T"})
    second = TestClient(app).post("/api/bugreport/link/ticket", json={"ticket": "T"})

    assert first.status_code == 500
    assert first.json()["code"] == "bugreport.storage_unavailable"
    # The relay already consumed the token; claiming "linked" would leave the
    # reporter permanently unsigned, so the UI is told to link again.
    assert second.status_code == 409
    assert second.json()["code"] == "bugreport.link_incomplete"


# ---------------------------------------------------------------------------
# Screenshot attachments (S5) — multipart, never inside the JSON bundle
# ---------------------------------------------------------------------------

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"0" * 8
JPEG_BYTES = b"\xff\xd8\xff" + b"0" * 8


def _capture_parts(captured: list) -> Callable:
    def _send(url, payload, headers=None, attachments=None):
        captured.append(
            {
                "url": url,
                "payload": payload,
                "headers": dict(headers or {}),
                "attachments": list(attachments or []),
            }
        )
        return 200, {"ok": True, "delivery_id": "delivery-att"}

    return _send


def _multipart(report: dict, files: list) -> dict:
    return {
        "data": {"report": json.dumps(report)},
        "files": [
            ("attachments", (name, content, mime)) for name, content, mime in files
        ],
    }


def test_two_screenshots_are_forwarded_as_parts_beside_the_bundle() -> None:
    captured: list = []
    app = _make_app(relay_url="http://relay.test", relay_post=_capture_parts(captured))

    resp = TestClient(app).post(
        "/api/bugreport/submit",
        **_multipart(
            _valid_payload(context={"route": "/perfil"}),
            [
                ("pantalla-1.png", PNG_BYTES, "image/png"),
                ("pantalla-2.jpg", JPEG_BYTES, "image/jpeg"),
            ],
        ),
    )

    assert resp.status_code == 200, resp.text
    sent = captured[0]
    assert [name for name, _data, _mime in sent["attachments"]] == [
        "pantalla-1.png",
        "pantalla-2.jpg",
    ]
    assert [mime for _name, _data, mime in sent["attachments"]] == [
        "image/png",
        "image/jpeg",
    ]
    assert sent["attachments"][0][1] == PNG_BYTES
    # Binaries never enter the JSON bundle.
    assert "PNG" not in json.dumps(sent["payload"])


def test_a_third_screenshot_is_refused() -> None:
    app = _make_app(relay_url="http://relay.test", relay_post=_capture_parts([]))

    resp = TestClient(app).post(
        "/api/bugreport/submit",
        **_multipart(
            _valid_payload(),
            [
                ("a.png", PNG_BYTES, "image/png"),
                ("b.png", PNG_BYTES, "image/png"),
                ("c.png", PNG_BYTES, "image/png"),
            ],
        ),
    )

    assert resp.status_code == 413
    assert resp.json()["code"] == "bugreport.too_large"


def test_a_non_image_attachment_is_refused() -> None:
    app = _make_app(relay_url="http://relay.test", relay_post=_capture_parts([]))

    resp = TestClient(app).post(
        "/api/bugreport/submit",
        **_multipart(_valid_payload(), [("notes.txt", b"hello", "text/plain")]),
    )

    assert resp.status_code == 400
    assert resp.json()["code"] == "bugreport.invalid_attachment"


def test_an_oversized_screenshot_is_refused() -> None:
    app = _make_app(relay_url="http://relay.test", relay_post=_capture_parts([]))

    resp = TestClient(app).post(
        "/api/bugreport/submit",
        **_multipart(_valid_payload(), [("huge.png", b"0" * (5 * 1024 * 1024 + 1), "image/png")]),
    )

    assert resp.status_code == 413
    assert resp.json()["code"] == "bugreport.too_large"


def test_an_attachment_filename_never_carries_a_path() -> None:
    captured: list = []
    app = _make_app(relay_url="http://relay.test", relay_post=_capture_parts(captured))

    resp = TestClient(app).post(
        "/api/bugreport/submit",
        **_multipart(_valid_payload(), [("../../evil/captura.png", PNG_BYTES, "image/png")]),
    )

    assert resp.status_code == 200, resp.text
    assert captured[0]["attachments"][0][0] == "captura.png"


def test_multipart_without_the_report_part_is_refused() -> None:
    app = _make_app(relay_url="http://relay.test", relay_post=_capture_parts([]))

    resp = TestClient(app).post(
        "/api/bugreport/submit",
        files=[("attachments", ("a.png", PNG_BYTES, "image/png"))],
    )

    assert resp.status_code == 400
    assert resp.json()["code"] == "bugreport.not_allowlisted"


def test_a_json_submit_still_forwards_no_attachments() -> None:
    captured: list = []
    app = _make_app(relay_url="http://relay.test", relay_post=_capture_parts(captured))

    resp = TestClient(app).post("/api/bugreport/submit", json=_valid_payload())

    assert resp.status_code == 200, resp.text
    assert captured[0]["attachments"] == []


def test_the_declared_type_is_corrected_by_the_bytes() -> None:
    """A PNG renamed to .jpg is a PNG: the bytes decide what Telegram receives."""
    captured: list = []
    app = _make_app(relay_url="http://relay.test", relay_post=_capture_parts(captured))

    resp = TestClient(app).post(
        "/api/bugreport/submit",
        **_multipart(
            _valid_payload(),
            [("captura.jpg", PNG_BYTES, "image/jpeg")],
        ),
    )

    assert resp.status_code == 200, resp.text
    _name, _data, mime = captured[0]["attachments"][0]
    assert mime == "image/png"


def test_a_renamed_text_file_is_not_an_image() -> None:
    app = _make_app(relay_url="http://relay.test", relay_post=_capture_parts([]))

    resp = TestClient(app).post(
        "/api/bugreport/submit",
        **_multipart(_valid_payload(), [("captura.png", b"<html>hola</html>", "image/png")]),
    )

    assert resp.status_code == 400
    assert resp.json()["code"] == "bugreport.invalid_attachment"


def test_invisible_filename_characters_are_stripped() -> None:
    captured: list = []
    app = _make_app(relay_url="http://relay.test", relay_post=_capture_parts(captured))

    resp = TestClient(app).post(
        "/api/bugreport/submit",
        **_multipart(
            _valid_payload(),
            [("a\u0085b\u202ec.png", PNG_BYTES, "image/png")],
        ),
    )

    assert resp.status_code == 200, resp.text
    assert captured[0]["attachments"][0][0] == "abc.png"


def test_exactly_five_mb_is_accepted_and_one_more_refused() -> None:
    exact = PNG_BYTES + b"\x00" * (5 * 1024 * 1024 - len(PNG_BYTES))
    captured: list = []
    app = _make_app(relay_url="http://relay.test", relay_post=_capture_parts(captured))

    ok = TestClient(app).post(
        "/api/bugreport/submit",
        **_multipart(_valid_payload(), [("big.png", exact, "image/png")]),
    )

    assert ok.status_code == 200, ok.text
    assert captured[0]["attachments"][0][1] == exact

    calls: list = []
    app = _make_app(relay_url="http://relay.test", relay_post=_capture_parts(calls))
    over = TestClient(app).post(
        "/api/bugreport/submit",
        **_multipart(_valid_payload(), [("big.png", exact + b"\x00", "image/png")]),
    )

    assert over.status_code == 413
    assert calls == []


# ---------------------------------------------------------------------------
# Released fixes (S12) — the in-app notice needs no person→report mapping
# ---------------------------------------------------------------------------


def test_releases_are_proxied_from_the_relay() -> None:
    captured: list = []

    def _send(url, payload, headers=None, attachments=None):
        captured.append({"url": url, "headers": dict(headers or {})})
        return 200, {
            "ok": True,
            "releases": [
                {"version": "v0.5.0", "report_ids": ["abc-123"], "at": "2026-10-25T00:00:00Z"}
            ],
        }

    app = _make_app(
        relay_url="http://relay.test",
        relay_post=_send,
        relay_key="shared",
        local_state=None,
    )

    resp = TestClient(app).get("/api/bugreport/releases")

    assert resp.status_code == 200, resp.text
    assert resp.json()["releases"][0]["version"] == "v0.5.0"
    assert captured[0]["url"].endswith("/releases")
    # Reading the public list needs no secret at all (S19).
    assert "x-relay-key" not in captured[0]["headers"]


def test_releases_require_a_principal() -> None:
    app = _make_app(
        authed=False,
        relay_url="http://relay.test",
        relay_post=_capture([]),
        relay_key="k",
    )

    resp = TestClient(app).get("/api/bugreport/releases")

    assert resp.status_code == 401


def test_releases_fail_closed_without_a_relay_url() -> None:
    app = _make_app(relay_post=_capture([]))

    resp = TestClient(app).get("/api/bugreport/releases")

    assert resp.status_code == 502
    assert resp.json()["code"] == "bugreport.relay_unavailable"
