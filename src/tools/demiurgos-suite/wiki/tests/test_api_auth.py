"""Auth-vault credentials integration (auth-vault-credentials, PR 2).

Integration coverage for the credentials auth seam:

- R-AC-01: POST /api/auth/credentials/account (single account, optional
  password, words returned exactly once, blocking onboarding step).
- R-AC-02: POST /api/auth/credentials/login (password when set, passwordless
  "Enter" button when not), rate-limited wrong passwords.
- R-AC-03: cookie contract (httponly, samesite=lax, scheme-aware secure +
  ``DEMIURGOS_COOKIE_SECURE`` override, 8h / 30d TTL).
- R-AC-04: session status exposes ``last_auth_at`` (ISO 8601) and
  ``days_until_reauth`` countdown (clamped at 0).
- R-AC-05: recovery (words -> single-use token), recover/complete, and
  credential management (change password, remove password, change username,
  rotate words) — all gated on the words ownership key.
- R-AC-06: unified logout revokes the session.
- R-ERK-02: password and words verification use SEPARATE rate limiters.
- _resolve_principal with an active credentials session returns the correct
  EditPrincipal and gated writes accept that principal via the cookie alone.
- vault-settings-configure (R-VC-01..05, S-VC-01..05): the ``credentials_client``
  fixture now activates the vault via the PERSISTED ``capabilities.vault.enabled``
  flag (PRIMARY source, no env override); unit tests cover ``_vault_active()``
  combos, the missing-slot migration defaults, and integration tests cover the
  four vault lifecycle endpoints (config/enable/disable/reauth-interval).

NOTE on the http test transport: the Secure cookie attribute is scheme-aware
by default — over plain http the server sets a non-Secure cookie that the
transport jar keeps and sends back; when ``DEMIURGOS_COOKIE_SECURE`` pins
Secure=true, an http transport would never send it back. The tests force
those tokens into the client jar WITHOUT the Secure flag so the flow stays
hermetic, while the Set-Cookie attribute assertions (including Secure) are
made directly on the response headers.
"""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

_HERE = Path(__file__).resolve().parent
_WIKI = _HERE.parent
_SUITE = _WIKI.parent
for _p in (str(_WIKI), str(_SUITE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import api_server  # noqa: E402
from state_root_support import state_file  # noqa: E402

USERNAME = "vault-user"
PASSWORD = "correct horse battery staple"
DEFAULT_TTL_SECONDS = 8 * 3600
REMEMBER_ME_TTL_SECONDS = 30 * 24 * 3600
REAUTH_INTERVAL_D = 14


def _make_vault_client(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    vault_enabled: bool,
    base_url: str = "http://testserver",
) -> TestClient:
    """Build a TestClient sandboxed to *tmp_path* with the vault ON or OFF.

    ``_LOCAL_STATE`` is reset so the registry binds to the sandboxed project
    root; the session store, recovery tokens, and both rate limiters are reset
    for per-test isolation. ``DEMIURGOS_AUTH_MODE`` stays UNSET so the vault
    state comes exclusively from the persisted ``capabilities.vault.enabled``
    flag — the PRIMARY source (R-VC-01, S-VC-01c) — never the env override.
    ``base_url`` selects the request scheme for the scheme-aware Secure cookie
    tests (http://localhost, https://localhost, ...).
    """
    mundos = tmp_path / "mundos"
    lore = mundos / "test_mundo" / "lore"
    lore.mkdir(parents=True)
    (lore / "00_inicio.md").write_text(
        "---\ntype: criatura\ntitle: Inicio\n---\n# Inicio\n", encoding="utf-8"
    )
    monkeypatch.setattr(api_server, "MUNDOS_DIR", mundos)
    monkeypatch.setattr(api_server, "PROJECT_ROOT", tmp_path)
    monkeypatch.delenv("DEMIURGOS_AUTH_MODE", raising=False)
    monkeypatch.delenv("DEMIURGOS_COOKIE_SECURE", raising=False)
    monkeypatch.delenv("DEMIURGOS_REAUTH_INTERVAL_D", raising=False)
    api_server._graph_indices.clear()
    api_server._confirmation_store.clear()
    api_server._LOCAL_STATE = None
    with api_server._local_session_lock:
        api_server._sessions.clear()
        api_server._recovery_tokens.clear()
    api_server._password_rate_limiter.reset()
    api_server._words_rate_limiter.reset()
    if vault_enabled:
        registry = api_server._local_state()
        state = registry.snapshot()
        state.setdefault("capabilities", {})["vault"] = {
            "enabled": True, "reauth_interval_d": 14,
        }
        registry.atomic_commit(state)
    return TestClient(
        api_server.app,
        base_url=base_url,
        client=("127.0.0.1", 50000),
    )


@pytest.fixture()
def credentials_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """TestClient with a temp world + local state, vault ON via the persisted
    flag (flag-primary path, R-VC-01 / S-VC-01c).

    The env override is deliberately NOT set: the vault state must come from
    ``capabilities.vault.enabled`` so the whole credentials flow runs through
    the PRIMARY source. The ``DEMIURGOS_AUTH_MODE=credentials`` override path
    is covered by dedicated tests (S-VC-01b).
    """
    client = _make_vault_client(tmp_path, monkeypatch, vault_enabled=True)
    yield client
    api_server._LOCAL_STATE = None
    api_server._password_rate_limiter.reset()
    api_server._words_rate_limiter.reset()
    with api_server._local_session_lock:
        api_server._recovery_tokens.clear()


@pytest.fixture()
def vault_off_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """TestClient with a fresh install: vault OFF, no account, no env override
    (S-VC-02a, S-AC-02a/c — the activation starting point)."""
    client = _make_vault_client(tmp_path, monkeypatch, vault_enabled=False)
    yield client
    api_server._LOCAL_STATE = None
    api_server._password_rate_limiter.reset()
    api_server._words_rate_limiter.reset()
    with api_server._local_session_lock:
        api_server._recovery_tokens.clear()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_account(
    client: TestClient,
    username: str = USERNAME,
    password: str | None = PASSWORD,
) -> str:
    """Create the account and return the plaintext recovery words."""
    body: dict = {"username": username}
    if password is not None:
        body["password"] = password
    response = client.post("/api/auth/credentials/account", json=body)
    assert response.status_code == 200, response.text
    return response.json()["words"]


def _login(
    client: TestClient,
    password: str | None = None,
    remember_me: bool = False,
) -> str:
    """Login and plant the session token into the http test jar."""
    body: dict = {"remember_me": remember_me}
    if password is not None:
        body["password"] = password
    started = client.post("/api/auth/credentials/login", json=body)
    assert started.status_code == 200, started.text
    token = _session_token(started)
    _force_cookie(client, api_server._SESSION_COOKIE, token)
    return token


def _force_cookie(client: TestClient, name: str, value: str) -> None:
    """Plant a cookie in the test jar WITHOUT the Secure flag.

    The jar otherwise keeps the server-issued Secure cookie but refuses to
    send it over the http transport. The Set-Cookie attribute assertions are
    made separately on the response headers, so this only affects the
    outbound flow.
    """
    client.cookies.delete(name)
    client.cookies.set(name, value, domain="", path="/")


def _set_cookies(response) -> list[str]:
    return [h.lower() for h in response.headers.get_list("set-cookie")]


def _session_cookie(response) -> str:
    for header in _set_cookies(response):
        if header.startswith(api_server._SESSION_COOKIE + "="):
            return header
    raise AssertionError(
        f"no {api_server._SESSION_COOKIE} cookie in {_set_cookies(response)}"
    )


def _session_token(response) -> str:
    """Extract the bearer token from the RAW (original-case) Set-Cookie.

    The header must NOT be lowercased first: ``token_urlsafe`` values are
    case-sensitive and would hash differently.
    """
    for header in response.headers.get_list("set-cookie"):
        if header.lower().startswith(api_server._SESSION_COOKIE + "="):
            token = header.split(api_server._SESSION_COOKIE + "=", 1)[1].split(";", 1)[0].strip()
            assert token
            return token
    raise AssertionError(f"no {api_server._SESSION_COOKIE} cookie in response")


def _account_slot(client: TestClient) -> dict:
    return api_server._local_state().snapshot()["capabilities"]["account"]


class _CookieOnlyRequest:
    """Minimal request stand-in exposing only the cookie jar.

    Credentials-vault resolution reads only ``request.cookies`` (never the
    socket peer, unlike local-dev), so this is sufficient for principal
    resolution.
    """

    def __init__(self, cookies: dict[str, str]):
        self.cookies = cookies


# ---------------------------------------------------------------------------
# R-AC-01 — POST /api/auth/credentials/account
# ---------------------------------------------------------------------------


def test_account_creation_returns_words_once_and_creates_slot(
        credentials_client: TestClient):
    words = _create_account(credentials_client, password=PASSWORD)
    assert words and len(words.split()) >= 8

    account = _account_slot(credentials_client)
    assert account["username"] == USERNAME
    assert account["password_hash"]  # Argon2id hash
    assert account["words_hash"]  # Argon2id hash
    # The plaintext words are NEVER stored: only their hash.
    assert "words" not in account
    assert words not in str(account)

    # The words hash verifies against the returned plaintext.
    assert api_server.account_verify_words(
        words, account["words_hash"], api_server._words_rate_limiter) is True

    # The account step is recorded as completed in onboarding (blocking).
    status = credentials_client.get("/api/onboarding/status").json()
    assert "account" in status["completed_steps"]
    assert "account" not in status["pending_steps"]


def test_account_creation_passwordless_has_null_password_hash(
        credentials_client: TestClient):
    words = _create_account(credentials_client, password=None)
    assert words
    assert _account_slot(credentials_client)["password_hash"] is None


def test_account_creation_rejects_duplicate_account(
        credentials_client: TestClient):
    _create_account(credentials_client)
    second = credentials_client.post(
        "/api/auth/credentials/account",
        json={"username": "other-user", "password": "x"},
    )
    assert second.status_code == 409
    # The original account is untouched.
    assert _account_slot(credentials_client)["username"] == USERNAME


def test_account_creation_requires_username(credentials_client: TestClient):
    missing = credentials_client.post(
        "/api/auth/credentials/account", json={"username": "   "})
    assert missing.status_code == 422


def test_credentials_endpoints_forbidden_when_vault_off(
        credentials_client: TestClient):
    """With the vault OFF (flag cleared, no env override) vault-only endpoints
    are forbidden (403): the PERSISTED flag is the PRIMARY gate (R-AC-01).
    Account creation is the exception: it is part of the default onboarding
    flow and stays allowed on fresh installs (S-AC-01b)."""
    registry = api_server._local_state()
    state = registry.snapshot()
    state["capabilities"]["vault"] = {"enabled": False, "reauth_interval_d": 14}
    registry.atomic_commit(state)
    assert credentials_client.post(
        "/api/auth/credentials/login", json={}).status_code == 403
    assert credentials_client.post(
        "/api/auth/credentials/recover",
        json={"words": "x"}).status_code == 403
    assert credentials_client.post(
        "/api/auth/credentials/words/rotate",
        json={"words": "x"}).status_code == 403
    # S-AC-01b: the onboarding account step must still work with vault OFF.
    created = credentials_client.post(
        "/api/auth/credentials/account",
        json={"username": "fresh-user", "password": "x"})
    assert created.status_code == 200, created.text


# ---------------------------------------------------------------------------
# R-AC-02 / R-AC-03 — POST /api/auth/credentials/login + cookie contract
# ---------------------------------------------------------------------------


def test_login_with_password_sets_secure_httponly_cookie(
        credentials_client: TestClient, monkeypatch: pytest.MonkeyPatch):
    """S-AC-03a — an HTTPS deployment pins the Secure cookie attribute.

    Over plain http the scheme-aware default would NOT set Secure; the
    explicit ``DEMIURGOS_COOKIE_SECURE=true`` override pins the secure-cookie
    contract here (the scheme-aware default itself is covered by
    test_cookie_secure_flag_is_scheme_aware_with_env_override and the
    http/https integration tests below).
    """
    monkeypatch.setenv("DEMIURGOS_COOKIE_SECURE", "true")
    _create_account(credentials_client, password=PASSWORD)
    started = credentials_client.post(
        "/api/auth/credentials/login", json={"password": PASSWORD})
    assert started.status_code == 200
    body = started.json()
    assert body["mode"] == "credentials"
    assert body["enabled"] is True
    assert body["authenticated"] is True
    assert body["label"] == USERNAME
    assert body["provider"] == "credentials"

    cookie = _session_cookie(started)
    assert "httponly" in cookie
    assert "samesite=lax" in cookie
    assert "path=/" in cookie
    assert "secure" in cookie, "credentials mode must set the Secure flag"
    assert f"max-age={DEFAULT_TTL_SECONDS}" in cookie


def test_login_passwordless_creates_session(credentials_client: TestClient):
    _create_account(credentials_client, password=None)
    started = credentials_client.post(
        "/api/auth/credentials/login", json={"remember_me": False})
    assert started.status_code == 200
    assert started.json()["authenticated"] is True
    assert started.json()["provider"] == "credentials"


def test_login_rejects_wrong_password(credentials_client: TestClient):
    _create_account(credentials_client, password=PASSWORD)
    rejected = credentials_client.post(
        "/api/auth/credentials/login", json={"password": "wrong-password"})
    assert rejected.status_code == 401
    assert credentials_client.get(
        "/api/auth/session/status").json()["authenticated"] is False


def test_login_rate_limits_after_five_wrong_passwords(
        credentials_client: TestClient):
    """S-AC-02c: the 6th attempt is blocked even with the correct password."""
    _create_account(credentials_client, password=PASSWORD)
    for _ in range(5):
        rejected = credentials_client.post(
            "/api/auth/credentials/login", json={"password": "wrong"})
        assert rejected.status_code == 401
    blocked = credentials_client.post(
        "/api/auth/credentials/login", json={"password": PASSWORD})
    assert blocked.status_code == 401
    assert api_server._password_rate_limiter.check() is False


def test_login_requires_password_when_set(credentials_client: TestClient):
    _create_account(credentials_client, password=PASSWORD)
    missing = credentials_client.post(
        "/api/auth/credentials/login", json={"remember_me": False})
    assert missing.status_code == 422


def test_login_remember_me_extends_ttl_to_30_days(
        credentials_client: TestClient):
    """S-AC-03a: remember me -> max_age 30d (DEMIURGOS_REMEMBER_ME_TTL_D)."""
    _create_account(credentials_client, password=PASSWORD)
    started = credentials_client.post(
        "/api/auth/credentials/login",
        json={"password": PASSWORD, "remember_me": True},
    )
    assert started.status_code == 200
    assert f"max-age={REMEMBER_ME_TTL_SECONDS}" in _session_cookie(started)


def test_login_default_ttl_is_8_hours(credentials_client: TestClient):
    """S-AC-03b: no remember me -> max_age 8h."""
    _create_account(credentials_client, password=PASSWORD)
    started = credentials_client.post(
        "/api/auth/credentials/login", json={"password": PASSWORD})
    assert f"max-age={DEFAULT_TTL_SECONDS}" in _session_cookie(started)


def _scheme_request(scheme: str) -> SimpleNamespace:
    """Minimal request stand-in exposing the URL scheme (for unit tests)."""
    return SimpleNamespace(url=SimpleNamespace(scheme=scheme))


def test_cookie_secure_flag_is_scheme_aware_with_env_override(
        monkeypatch: pytest.MonkeyPatch):
    """S-AC-03c: scheme-aware default + explicit DEMIURGOS_COOKIE_SECURE.

    The default follows the request scheme (https -> Secure, http -> not),
    independent of the auth mode; the env override wins in both directions.
    """
    monkeypatch.delenv("DEMIURGOS_COOKIE_SECURE", raising=False)
    assert api_server._cookie_secure(_scheme_request("https")) is True
    assert api_server._cookie_secure(_scheme_request("http")) is False

    # Auth mode no longer drives the default (the bug being fixed): even in
    # credentials mode a plain-http request gets a non-Secure cookie.
    monkeypatch.setenv("DEMIURGOS_AUTH_MODE", "credentials")
    assert api_server._cookie_secure(_scheme_request("http")) is False
    assert api_server._cookie_secure(_scheme_request("https")) is True

    # The explicit env override wins over the scheme in every mode.
    monkeypatch.setenv("DEMIURGOS_COOKIE_SECURE", "true")
    assert api_server._cookie_secure(_scheme_request("http")) is True
    monkeypatch.setenv("DEMIURGOS_COOKIE_SECURE", "false")
    assert api_server._cookie_secure(_scheme_request("https")) is False


def test_login_over_http_sets_non_secure_cookie_and_session_persists(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Scheme-aware default over plain http (localhost / VPS over HTTP): the
    session cookie is NOT Secure, so the browser jar keeps it and the login
    actually persists end-to-end (the case the mode-based Secure default
    broke: a Secure cookie is never sent back over http)."""
    client = _make_vault_client(
        tmp_path, monkeypatch, vault_enabled=True, base_url="http://localhost")
    _create_account(client, password=PASSWORD)
    started = client.post(
        "/api/auth/credentials/login", json={"password": PASSWORD})
    assert started.status_code == 200
    assert "secure" not in _session_cookie(started)
    # The non-Secure cookie landed in the jar and is sent back: the session
    # persists with NO manual cookie forcing.
    assert client.get(
        "/api/auth/session/status").json()["authenticated"] is True


def test_login_over_https_sets_secure_cookie(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Scheme-aware default over https: the session cookie IS Secure."""
    client = _make_vault_client(
        tmp_path, monkeypatch, vault_enabled=True, base_url="https://localhost")
    _create_account(client, password=PASSWORD)
    started = client.post(
        "/api/auth/credentials/login", json={"password": PASSWORD})
    assert started.status_code == 200
    assert "secure" in _session_cookie(started)


def test_cookie_secure_env_override_forces_true_over_http(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """DEMIURGOS_COOKIE_SECURE=true forces the Secure flag even over http."""
    client = _make_vault_client(
        tmp_path, monkeypatch, vault_enabled=True, base_url="http://localhost")
    # The override is read at request time: set it after the sandboxed client
    # is built (the helper clears the env var for isolation).
    monkeypatch.setenv("DEMIURGOS_COOKIE_SECURE", "true")
    _create_account(client, password=PASSWORD)
    started = client.post(
        "/api/auth/credentials/login", json={"password": PASSWORD})
    assert started.status_code == 200
    assert "secure" in _session_cookie(started)


def test_cookie_secure_env_override_forces_false_over_https(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """DEMIURGOS_COOKIE_SECURE=false strips the Secure flag even over https."""
    client = _make_vault_client(
        tmp_path, monkeypatch, vault_enabled=True, base_url="https://localhost")
    # The override is read at request time: set it after the sandboxed client
    # is built (the helper clears the env var for isolation).
    monkeypatch.setenv("DEMIURGOS_COOKIE_SECURE", "false")
    _create_account(client, password=PASSWORD)
    started = client.post(
        "/api/auth/credentials/login", json={"password": PASSWORD})
    assert started.status_code == 200
    assert "secure" not in _session_cookie(started)


# ---------------------------------------------------------------------------
# R-ERK-02 — password vs words rate-limit separation
# ---------------------------------------------------------------------------


def test_password_limit_does_not_block_words_recovery(
        credentials_client: TestClient):
    """S-ERK-02a: exhausting the password limiter leaves words recovery open."""
    words = _create_account(credentials_client, password=PASSWORD)
    for _ in range(5):
        assert credentials_client.post(
            "/api/auth/credentials/login",
            json={"password": "wrong"}).status_code == 401
    assert credentials_client.post(
        "/api/auth/credentials/login",
        json={"password": PASSWORD}).status_code == 401  # password blocked

    recovered = credentials_client.post(
        "/api/auth/credentials/recover", json={"words": words})
    assert recovered.status_code == 200, "words recovery must not be limited"


def test_words_limit_does_not_block_password_login(
        credentials_client: TestClient):
    """S-ERK-02b: exhausting the words limiter leaves password login open."""
    _create_account(credentials_client, password=PASSWORD)
    for _ in range(5):
        assert credentials_client.post(
            "/api/auth/credentials/recover",
            json={"words": "wrong words"}).status_code == 401
    assert credentials_client.post(
        "/api/auth/credentials/recover",
        json={"words": "still wrong"}).status_code == 401  # words blocked

    started = credentials_client.post(
        "/api/auth/credentials/login", json={"password": PASSWORD})
    assert started.status_code == 200, "password login must not be limited"


# ---------------------------------------------------------------------------
# R-AC-05 — recovery (forgot password)
# ---------------------------------------------------------------------------


def test_recovery_issues_single_use_token(credentials_client: TestClient):
    words = _create_account(credentials_client, password=PASSWORD)
    recovered = credentials_client.post(
        "/api/auth/credentials/recover", json={"words": words})
    assert recovered.status_code == 200
    token = recovered.json()["recovery_token"]
    assert token

    completed = credentials_client.post(
        "/api/auth/credentials/recover/complete",
        json={"recovery_token": token, "new_password": "brand-new-pass"},
    )
    assert completed.status_code == 200
    assert completed.json() == {"success": True}

    # The new password works; the old one no longer does.
    assert credentials_client.post(
        "/api/auth/credentials/login",
        json={"password": "brand-new-pass"}).status_code == 200
    assert credentials_client.post(
        "/api/auth/credentials/login",
        json={"password": PASSWORD}).status_code == 401


def test_recovery_token_is_single_use(credentials_client: TestClient):
    words = _create_account(credentials_client, password=PASSWORD)
    token = credentials_client.post(
        "/api/auth/credentials/recover",
        json={"words": words}).json()["recovery_token"]
    assert credentials_client.post(
        "/api/auth/credentials/recover/complete",
        json={"recovery_token": token, "new_password": "x"}).status_code == 200
    # Replay of the consumed token fails.
    replay = credentials_client.post(
        "/api/auth/credentials/recover/complete",
        json={"recovery_token": token, "new_password": "y"})
    assert replay.status_code == 401


def test_recovery_complete_updates_username(credentials_client: TestClient):
    words = _create_account(credentials_client, password=PASSWORD)
    token = credentials_client.post(
        "/api/auth/credentials/recover",
        json={"words": words}).json()["recovery_token"]
    completed = credentials_client.post(
        "/api/auth/credentials/recover/complete",
        json={"recovery_token": token, "new_username": "renamed-user"})
    assert completed.status_code == 200
    assert _account_slot(credentials_client)["username"] == "renamed-user"


def test_recovery_rejects_wrong_words_and_rate_limits(
        credentials_client: TestClient):
    _create_account(credentials_client, password=PASSWORD)
    for _ in range(5):
        rejected = credentials_client.post(
            "/api/auth/credentials/recover", json={"words": "wrong words"})
        assert rejected.status_code == 401
    # The 6th attempt is blocked by the words limiter even with the correct
    # words (S-AC-05d).
    blocked = credentials_client.post(
        "/api/auth/credentials/recover", json={"words": "still wrong"})
    assert blocked.status_code == 401
    assert api_server._words_rate_limiter.check() is False


# ---------------------------------------------------------------------------
# R-AC-05 — credential management (words = ownership key)
# ---------------------------------------------------------------------------


def test_change_password_requires_an_active_session(
        credentials_client: TestClient):
    _create_account(credentials_client, password=PASSWORD)
    unauthenticated = credentials_client.post(
        "/api/auth/credentials/password",
        json={"words": "some words", "new_password": "x"})
    assert unauthenticated.status_code == 401


def test_change_password_via_words(credentials_client: TestClient):
    words = _create_account(credentials_client, password=PASSWORD)
    _login(credentials_client, password=PASSWORD)
    changed = credentials_client.post(
        "/api/auth/credentials/password",
        json={"words": words, "new_password": "new-secret"})
    assert changed.status_code == 200
    assert changed.json() == {"success": True}

    assert credentials_client.post(
        "/api/auth/credentials/login",
        json={"password": PASSWORD}).status_code == 401
    assert credentials_client.post(
        "/api/auth/credentials/login",
        json={"password": "new-secret"}).status_code == 200


def test_change_password_rejects_wrong_words(credentials_client: TestClient):
    _create_account(credentials_client, password=PASSWORD)
    _login(credentials_client, password=PASSWORD)
    rejected = credentials_client.post(
        "/api/auth/credentials/password",
        json={"words": "wrong words", "new_password": "x"})
    assert rejected.status_code == 401


def test_remove_password_via_words(credentials_client: TestClient):
    words = _create_account(credentials_client, password=PASSWORD)
    _login(credentials_client, password=PASSWORD)
    removed = credentials_client.post(
        "/api/auth/credentials/password/remove", json={"words": words})
    assert removed.status_code == 200
    assert _account_slot(credentials_client)["password_hash"] is None

    # The account is now passwordless: login without a password works.
    assert credentials_client.post(
        "/api/auth/credentials/login", json={"remember_me": False}).status_code == 200


def test_change_username_via_words(credentials_client: TestClient):
    words = _create_account(credentials_client, password=PASSWORD)
    _login(credentials_client, password=PASSWORD)
    renamed = credentials_client.post(
        "/api/auth/credentials/username",
        json={"words": words, "new_username": "new-handle"})
    assert renamed.status_code == 200
    assert _account_slot(credentials_client)["username"] == "new-handle"


def test_rotate_words_requires_ownership_words(credentials_client: TestClient):
    """R-ERK-01 (amended) — rotating requires the CURRENT recovery words.

    A session alone is NOT an ownership proof: otherwise anyone who knows the
    password could mint fresh words and escalate the session into permanent
    ownership. Both the no-session and the session-with-wrong-words cases are
    rejected.
    """
    old_words = _create_account(credentials_client, password=PASSWORD)

    # No session at all: rejected before the words are even checked.
    assert credentials_client.post(
        "/api/auth/credentials/words/rotate",
        json={"words": old_words}).status_code == 401

    _login(credentials_client, password=PASSWORD)

    # A valid session plus WRONG words (made-up ownership proof): rejected.
    assert credentials_client.post(
        "/api/auth/credentials/words/rotate",
        json={"words": "not the words"}).status_code == 401


def test_rotate_words_returns_new_words_once(credentials_client: TestClient):
    old_words = _create_account(credentials_client, password=PASSWORD)
    _login(credentials_client, password=PASSWORD)

    rotated = credentials_client.post(
        "/api/auth/credentials/words/rotate", json={"words": old_words})
    assert rotated.status_code == 200
    new_words = rotated.json()["new_words"]
    assert new_words and new_words != old_words

    # The old words no longer verify; the new ones do (R-ERK-01).
    assert credentials_client.post(
        "/api/auth/credentials/recover",
        json={"words": old_words}).status_code == 401
    assert credentials_client.post(
        "/api/auth/credentials/recover",
        json={"words": new_words}).status_code == 200


def test_rotate_words_cannot_escalate_a_session_to_ownership(
        credentials_client: TestClient):
    """Regression for the confirmed escalation chain.

    With a session but WITHOUT the words, rotation fails; therefore made-up
    words cannot be used to mint ownership and change the username. With the
    correct current words, rotation succeeds and the NEW words are the ones
    that prove ownership on /credentials/username, while the OLD ones do not.
    """
    old_words = _create_account(credentials_client, password=PASSWORD)
    _login(credentials_client, password=PASSWORD)

    # Step 1: a session alone cannot rotate with made-up words…
    assert credentials_client.post(
        "/api/auth/credentials/words/rotate",
        json={"words": "made up words"}).status_code == 401

    # …so those made-up words cannot be used to change the username either.
    assert credentials_client.post(
        "/api/auth/credentials/username",
        json={"words": "made up words", "new_username": "attacker"},
    ).status_code == 401
    assert _account_slot(credentials_client)["username"] == USERNAME

    # Step 2: the correct current words DO rotate, minting new ownership.
    rotated = credentials_client.post(
        "/api/auth/credentials/words/rotate", json={"words": old_words})
    assert rotated.status_code == 200
    new_words = rotated.json()["new_words"]
    assert new_words and new_words != old_words

    # Step 3: the NEW words now change the username; the OLD words no longer do.
    assert credentials_client.post(
        "/api/auth/credentials/username",
        json={"words": old_words, "new_username": "old-words-user"},
    ).status_code == 401
    assert credentials_client.post(
        "/api/auth/credentials/username",
        json={"words": new_words, "new_username": "new-words-user"},
    ).status_code == 200
    assert _account_slot(credentials_client)["username"] == "new-words-user"


# ---------------------------------------------------------------------------
# R-AC-04 — session status (last_auth_at + days_until_reauth) + logout
# ---------------------------------------------------------------------------


def test_session_status_exposes_credentials_provider(
        credentials_client: TestClient):
    """R-VC-06 — with the vault ON via the PERSISTED flag (no env override)
    the reported ``mode`` is ``credentials`` (the flag is PRIMARY, R-VC-01):
    the login UI must ask for the password once the vault is active, even if
    the env still defaults to disabled/local-dev."""
    status = credentials_client.get("/api/auth/session/status")
    assert status.status_code == 200
    assert status.json() == {
        "mode": "credentials",
        "enabled": True,
        "authenticated": False,
        "label": None,
        "provider": None,
        # No account yet: nothing to log in with, so no password prompt.
        "has_password": False,
    }

    _create_account(credentials_client, password=PASSWORD)
    _login(credentials_client, password=PASSWORD)
    status = credentials_client.get("/api/auth/session/status").json()
    assert status["authenticated"] is True
    assert status["provider"] == "credentials"
    assert status["label"] == USERNAME
    # The account has a password: the login UI must show the password prompt.
    assert status["has_password"] is True


def test_session_status_exposes_has_password_for_passwordless_account(
        credentials_client: TestClient):
    """S-AC-02b: a passwordless account reports has_password=false so the
    login UI renders the "Enter" button without a password field."""
    _create_account(credentials_client, password=None)
    status = credentials_client.get("/api/auth/session/status").json()
    assert status["has_password"] is False


def test_session_status_exposes_last_auth_at_and_reauth_countdown(
        credentials_client: TestClient, monkeypatch: pytest.MonkeyPatch):
    """R-AC-04 (task 2.8): countdown right after login == interval (14d)."""
    _create_account(credentials_client, password=PASSWORD)
    _login(credentials_client, password=PASSWORD)
    status = credentials_client.get("/api/auth/session/status").json()
    assert status["provider"] == "credentials"
    assert status["last_auth_at"]  # ISO 8601 string
    assert status["days_until_reauth"] == REAUTH_INTERVAL_D

    # The interval is configurable via DEMIURGOS_REAUTH_INTERVAL_D.
    monkeypatch.setenv("DEMIURGOS_REAUTH_INTERVAL_D", "30")
    status = credentials_client.get("/api/auth/session/status").json()
    assert status["days_until_reauth"] == 30


def test_reauth_countdown_counts_elapsed_days_and_clamps_at_zero(
        credentials_client: TestClient):
    _create_account(credentials_client, password=PASSWORD)
    token = _login(credentials_client, password=PASSWORD)
    with api_server._local_session_lock:
        record = api_server._sessions[api_server._hash_token(token)]
        record["last_auth_at"] = datetime.now(timezone.utc) - timedelta(days=10)
    status = credentials_client.get("/api/auth/session/status").json()
    assert status["days_until_reauth"] == REAUTH_INTERVAL_D - 10

    # Past the interval the countdown clamps at 0 (never negative).
    with api_server._local_session_lock:
        record = api_server._sessions[api_server._hash_token(token)]
        record["last_auth_at"] = datetime.now(timezone.utc) - timedelta(days=40)
    status = credentials_client.get("/api/auth/session/status").json()
    assert status["days_until_reauth"] == 0


def test_unified_logout_clears_credentials_session(
        credentials_client: TestClient):
    _create_account(credentials_client, password=None)
    token = _login(credentials_client, password=None)  # passwordless account
    logged_out = credentials_client.delete("/api/auth/session")
    assert logged_out.status_code == 200
    assert logged_out.json()["authenticated"] is False
    assert credentials_client.get(
        "/api/auth/session/status").json()["authenticated"] is False
    # Server-side revocation: the session record is gone (R-AC-06).
    with api_server._local_session_lock:
        assert api_server._hash_token(token) not in api_server._sessions


# ---------------------------------------------------------------------------
# _resolve_principal with a credentials session
# ---------------------------------------------------------------------------


def test_resolve_principal_with_credentials_session_returns_edit_principal(
        credentials_client: TestClient):
    _create_account(credentials_client, password=PASSWORD)
    token = _login(credentials_client, password=PASSWORD)

    principal = api_server._resolve_principal(
        _CookieOnlyRequest({api_server._SESSION_COOKIE: token}))
    assert isinstance(principal, api_server.EditPrincipal)
    assert principal.id.startswith("credentials-session-")
    assert principal.label == USERNAME

    with api_server._local_session_lock:
        record = api_server._sessions[api_server._hash_token(token)]
    assert record["provider"] == "credentials"
    assert record["label"] == USERNAME
    assert record["last_auth_at"] is not None

    # The seam integrates: a gated write accepts the credentials principal via
    # the browser cookie alone (no per-request network needed).
    target = api_server.MUNDOS_DIR / "test_mundo" / "lore" / "00_inicio.md"
    base_rev = hashlib.sha256(target.read_bytes()).hexdigest()
    confirmation = credentials_client.post(
        "/api/test_mundo/lore/edit-confirmation?path=00_inicio.md",
        json={
            "edit_id": "e1",
            "base_revision": base_rev,
            "proposed_content": "# Edit\n",
        },
    )
    assert confirmation.status_code == 200


def test_resolve_principal_fails_closed_without_credentials_session(
        credentials_client: TestClient):
    assert api_server._resolve_principal(_CookieOnlyRequest({})) is None


# ---------------------------------------------------------------------------
# vault-settings-configure — _vault_active() combos (S-VC-01a/b/c)
# ---------------------------------------------------------------------------


@pytest.fixture()
def vault_registry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Point api_server at a fresh temp registry and reset the cache so
    ``_vault_active``/``_reauth_interval_d``/``_vault_config`` read the
    sandboxed local state file. Yields the LocalState instance."""
    monkeypatch.setattr(api_server, "PROJECT_ROOT", tmp_path)
    monkeypatch.delenv("DEMIURGOS_AUTH_MODE", raising=False)
    monkeypatch.delenv("DEMIURGOS_REAUTH_INTERVAL_D", raising=False)
    api_server._LOCAL_STATE = None
    yield api_server._local_state()
    api_server._LOCAL_STATE = None


def _persist_vault_flag(registry, *, enabled: bool) -> None:
    state = registry.snapshot()
    state.setdefault("capabilities", {})["vault"] = {
        "enabled": enabled, "reauth_interval_d": 14,
    }
    registry.atomic_commit(state)


def test_vault_active_flag_only(vault_registry, monkeypatch: pytest.MonkeyPatch):
    """S-VC-01c — the persisted flag alone (no env override) activates."""
    monkeypatch.delenv("DEMIURGOS_AUTH_MODE", raising=False)
    _persist_vault_flag(vault_registry, enabled=True)
    assert api_server._vault_active() is True


def test_vault_active_env_only(vault_registry, monkeypatch: pytest.MonkeyPatch):
    """S-VC-01b — the env override alone (flag OFF) activates."""
    monkeypatch.setenv("DEMIURGOS_AUTH_MODE", "credentials")
    assert api_server._vault_active() is True


def test_vault_active_both_flag_and_env(vault_registry, monkeypatch: pytest.MonkeyPatch):
    """S-VC-01b/c — flag AND override both on: still active."""
    monkeypatch.setenv("DEMIURGOS_AUTH_MODE", "credentials")
    _persist_vault_flag(vault_registry, enabled=True)
    assert api_server._vault_active() is True


def test_vault_active_neither_flag_nor_env(vault_registry, monkeypatch: pytest.MonkeyPatch):
    """Neither source set: vault inactive (fresh install default)."""
    monkeypatch.delenv("DEMIURGOS_AUTH_MODE", raising=False)
    _persist_vault_flag(vault_registry, enabled=False)
    assert api_server._vault_active() is False


# ---------------------------------------------------------------------------
# vault-settings-configure — migration defaults (S-VC-01a)
# ---------------------------------------------------------------------------


def test_legacy_install_without_vault_slot_defaults_via_get(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """S-VC-01a — an installation written before the vault slot existed loads
    cleanly; ``_vault_active()``/``_reauth_interval_d()`` fall back to
    ``{enabled: False, reauth_interval_d: 14}`` via safe ``.get()`` — no
    error, and words are never regenerated (the legacy account stays
    untouched, still unconfigured)."""
    monkeypatch.delenv("DEMIURGOS_AUTH_MODE", raising=False)
    monkeypatch.delenv("DEMIURGOS_REAUTH_INTERVAL_D", raising=False)
    monkeypatch.setattr(api_server, "PROJECT_ROOT", tmp_path)
    api_server._LOCAL_STATE = None
    state_path = state_file("local-state.json")
    state_path.parent.mkdir(parents=True)
    state_path.write_text(json.dumps({
        "schema_version": 1,
        "revision": 3,
        "onboarding": {
            "completed": True,
            "current_step": "ready",
            "completed_steps": ["step0", "account", "world"],
        },
        "locale": {"ui": "es", "conversation": "es", "content": "es",
                   "region": "AR", "region_explicit": True,
                   "iana_timezone": "America/Argentina/Buenos_Aires"},
        "capabilities": {
            # Pre-vault install: account exists, NO vault slot.
            "account": {
                "username": "ada",
                "password_hash": None,
                "words_hash": "$argon2id$legacy-install",
            },
        },
    }), encoding="utf-8")

    registry = api_server._local_state()
    assert "vault" not in registry.snapshot()["capabilities"]
    # .get() defaults: vault OFF, reauth interval 14, no error.
    assert api_server._vault_active() is False
    assert api_server._reauth_interval_d() == 14
    # The public config mirrors the defaults; the legacy account alone never
    # activates the vault (S-ID-01b).
    config = api_server._vault_config()
    assert config["enabled"] is False
    assert config["env_override"] is False
    assert config["account_exists"] is True
    assert config["reauth_interval_d"] == 14
    api_server._LOCAL_STATE = None


# ---------------------------------------------------------------------------
# vault-settings-configure — vault lifecycle endpoints (S-VC-02..05)
# ---------------------------------------------------------------------------


def test_vault_config_public_when_vault_off(vault_off_client: TestClient):
    """S-VC-02a — vault OFF, no account: config is public and reports the
    defaults."""
    resp = vault_off_client.get("/api/auth/vault/config")
    assert resp.status_code == 200
    assert resp.json() == {
        "enabled": False,
        "account_exists": False,
        "username": None,
        "has_password": False,
        "reauth_interval_d": REAUTH_INTERVAL_D,
        "env_override": False,
    }


def test_vault_config_public_when_vault_on(credentials_client: TestClient):
    """S-VC-02b — vault ON: config stays public for the Settings panel and
    never exposes secrets (no words, no password hash, no session material)."""
    _create_account(credentials_client, password=PASSWORD)
    resp = credentials_client.get("/api/auth/vault/config")
    assert resp.status_code == 200
    body = resp.json()
    assert body["enabled"] is True
    assert body["account_exists"] is True
    assert body["username"] == USERNAME
    assert body["has_password"] is True
    assert body["reauth_interval_d"] == REAUTH_INTERVAL_D
    assert body["env_override"] is False
    assert "words" not in body
    assert "password" not in body
    assert "hash" not in str(body)


def test_vault_enable_without_account_creates_and_returns_words_once(
        vault_off_client: TestClient):
    """S-VC-03a — no account: enable creates the account, activates the vault
    via the persisted flag, and returns the words exactly once."""
    resp = vault_off_client.post(
        "/api/auth/vault/enable",
        json={"username": USERNAME, "password": PASSWORD})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["enabled"] is True
    words = body["words"]
    assert words and len(words.split()) >= 8

    registry = api_server._local_state()
    snapshot = registry.snapshot()
    account = snapshot["capabilities"]["account"]
    assert account["username"] == USERNAME
    assert account["password_hash"]
    assert account["words_hash"]
    assert snapshot["capabilities"]["vault"]["enabled"] is True
    # The plaintext words verify against the stored hash and are NEVER stored.
    assert "words" not in account
    assert api_server.account_verify_words(
        words, account["words_hash"], api_server._words_rate_limiter) is True
    # The config now reports the ON state.
    config = vault_off_client.get("/api/auth/vault/config").json()
    assert config["enabled"] is True
    assert config["account_exists"] is True
    # A second enable is rejected: the vault is already ON (S-VC-03d).
    again = vault_off_client.post(
        "/api/auth/vault/enable",
        json={"username": USERNAME, "password": PASSWORD})
    assert again.status_code == 409


def test_vault_enable_with_existing_account_verifies_words(
        vault_off_client: TestClient):
    """S-VC-03b/c — account exists, vault OFF: correct words activate the
    vault; wrong words return 400 and the flag stays OFF."""
    words = _create_account(vault_off_client, password=PASSWORD)

    wrong = vault_off_client.post(
        "/api/auth/vault/enable", json={"words": "totally wrong words"})
    assert wrong.status_code == 400
    assert api_server._local_state().snapshot()[
        "capabilities"]["vault"]["enabled"] is False

    ok = vault_off_client.post("/api/auth/vault/enable", json={"words": words})
    assert ok.status_code == 200, ok.text
    assert ok.json() == {"enabled": True}
    assert api_server._local_state().snapshot()[
        "capabilities"]["vault"]["enabled"] is True


def test_vault_enable_conflict_when_already_on(credentials_client: TestClient):
    """S-VC-03d — vault already ON: enable is rejected with 409."""
    _create_account(credentials_client, password=PASSWORD)
    resp = credentials_client.post(
        "/api/auth/vault/enable",
        json={"username": USERNAME, "password": PASSWORD})
    assert resp.status_code == 409


def test_vault_disable_with_correct_words(credentials_client: TestClient):
    """S-VC-04a — correct words disable the vault and persist the flag."""
    words = _create_account(credentials_client, password=PASSWORD)
    resp = credentials_client.post(
        "/api/auth/vault/disable", json={"words": words})
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"enabled": False}
    assert api_server._local_state().snapshot()[
        "capabilities"]["vault"]["enabled"] is False


def test_vault_disable_without_words_returns_400(credentials_client: TestClient):
    """S-VC-04b — a session alone NEVER suffices: missing words -> 400."""
    _create_account(credentials_client, password=PASSWORD)
    resp = credentials_client.post("/api/auth/vault/disable", json={})
    assert resp.status_code == 400
    assert api_server._local_state().snapshot()[
        "capabilities"]["vault"]["enabled"] is True


def test_vault_disable_wrong_words_400_and_rate_limited(
        credentials_client: TestClient):
    """S-VC-04c — wrong words return 400 AND increment the words rate limiter;
    the 6th attempt is blocked even with the correct words."""
    words = _create_account(credentials_client, password=PASSWORD)
    for _ in range(5):
        rejected = credentials_client.post(
            "/api/auth/vault/disable", json={"words": "wrong words"})
        assert rejected.status_code == 400
    blocked = credentials_client.post(
        "/api/auth/vault/disable", json={"words": words})
    assert blocked.status_code == 400
    assert api_server._words_rate_limiter.check() is False


def test_vault_disable_when_off_returns_409(vault_off_client: TestClient):
    """Vault already OFF: disable is rejected (409, no mutation)."""
    resp = vault_off_client.post(
        "/api/auth/vault/disable", json={"words": "x y"})
    assert resp.status_code == 409


def test_vault_reauth_interval_persists_and_is_effective(
        credentials_client: TestClient):
    """S-VC-05a — with the vault ON and authenticated, the interval persists
    and the session countdown follows it."""
    _create_account(credentials_client, password=PASSWORD)
    _login(credentials_client, password=PASSWORD)
    resp = credentials_client.post(
        "/api/auth/vault/reauth-interval", json={"reauth_interval_d": 7})
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"reauth_interval_d": 7}
    assert api_server._local_state().snapshot()[
        "capabilities"]["vault"]["reauth_interval_d"] == 7
    assert credentials_client.get(
        "/api/auth/vault/config").json()["reauth_interval_d"] == 7
    assert credentials_client.get(
        "/api/auth/session/status").json()["days_until_reauth"] == 7


def test_vault_reauth_interval_env_override_wins(
        credentials_client: TestClient, monkeypatch: pytest.MonkeyPatch):
    """S-VC-05b — DEMIURGOS_REAUTH_INTERVAL_D overrides the persisted value:
    the response and config report the EFFECTIVE interval while the flag value
    is still persisted."""
    monkeypatch.setenv("DEMIURGOS_REAUTH_INTERVAL_D", "30")
    resp = credentials_client.post(
        "/api/auth/vault/reauth-interval", json={"reauth_interval_d": 7})
    assert resp.status_code == 200
    assert resp.json() == {"reauth_interval_d": 30}
    assert credentials_client.get(
        "/api/auth/vault/config").json()["reauth_interval_d"] == 30
    # The flag value IS persisted (7) — the override only wins on reads.
    assert api_server._local_state().snapshot()[
        "capabilities"]["vault"]["reauth_interval_d"] == 7