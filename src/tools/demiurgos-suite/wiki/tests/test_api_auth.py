"""7.4-7.5 — Google/emergency vault session integration (auth-google-vault).

Integration coverage for the unified vault auth seam (Phase 4):

- 7.4: POST /api/auth/google/session and /api/auth/emergency/session cookie
  contract (httponly, samesite=lax, scheme-aware secure, 8h / 14d TTL), 401
  on bad id_token, missing or mismatched nonce, rate-limit 401, rotation 401
  without a session, unified status ``provider``, unified logout.
- 7.5: ``_resolve_principal`` with an active google session returns the
  correct EditPrincipal (provider google, principal_id=sub, label=email) and
  gated writes accept that principal via the browser cookie alone.

NOTE on the http test transport: the real server sets Secure cookies in
google mode; an http transport would never send them back. The tests force
those cookies into the client jar WITHOUT the Secure flag so the flow stays
hermetic, while the Set-Cookie attribute assertions (including Secure) are
made directly on the response headers.
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

_HERE = Path(__file__).resolve().parent
_WIKI = _HERE.parent
_SUITE = _WIKI.parent
for _p in (str(_WIKI), str(_SUITE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import api_server  # noqa: E402
import emergency_key  # noqa: E402

GOOGLE_CLIENT_ID = "test-client.apps.googleusercontent.com"
GOOGLE_SUB = "google-subject-123"
GOOGLE_EMAIL = "vault-user@example.com"
EMERGENCY_KEY = "alpha bravo charlie delta echo foxtrot golf hotel"
EMERGENCY_LABEL = "Emergency recovery"

DEFAULT_TTL_SECONDS = 8 * 3600
REMEMBER_ME_TTL_SECONDS = 14 * 24 * 3600


@pytest.fixture()
def google_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """TestClient with a temp world + local state, running in google mode.

    ``_LOCAL_STATE`` is reset so the registry binds to the sandboxed project
    root; the session store and the emergency rate limiter are reset for
    per-test isolation.
    """
    mundos = tmp_path / "mundos"
    lore = mundos / "test_mundo" / "lore"
    lore.mkdir(parents=True)
    (lore / "00_inicio.md").write_text(
        "---\ntype: criatura\ntitle: Inicio\n---\n# Inicio\n", encoding="utf-8"
    )
    monkeypatch.setattr(api_server, "MUNDOS_DIR", mundos)
    monkeypatch.setattr(api_server, "PROJECT_ROOT", tmp_path)
    monkeypatch.setenv("DEMIURGOS_AUTH_MODE", "google")
    monkeypatch.setenv("GOOGLE_CLIENT_ID", GOOGLE_CLIENT_ID)
    api_server._graph_indices.clear()
    api_server._confirmation_store.clear()
    api_server._LOCAL_STATE = None
    with api_server._local_session_lock:
        api_server._sessions.clear()
    api_server._emergency_rate_limiter.reset()
    yield TestClient(api_server.app, client=("127.0.0.1", 50000))
    api_server._LOCAL_STATE = None
    api_server._emergency_rate_limiter.reset()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _install_emergency_key() -> None:
    """Persist an Argon2id hash for EMERGENCY_KEY in the sandboxed registry."""
    state = api_server._local_state().snapshot()
    state["capabilities"]["emergency_key_hash"] = emergency_key.hash_code(EMERGENCY_KEY)
    api_server._local_state().atomic_commit(state)


def _mock_google_verify(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace the Google id_token verifier with a deterministic fake.

    ``valid-token`` passes; ``bad-token`` and ``nonce-mismatch-token`` fail
    with the same ValueError the real module raises (S-GA1b).
    """

    def fake_verify(id_token: str, client_id: str, expected_nonce: str):
        if id_token == "bad-token":
            raise ValueError("id_token verification failed: forged signature")
        if id_token == "nonce-mismatch-token":
            raise ValueError("id_token nonce mismatch")
        return {
            "sub": GOOGLE_SUB,
            "email": GOOGLE_EMAIL,
            "nonce": expected_nonce,
        }

    monkeypatch.setattr(api_server, "google_auth_verify_id_token", fake_verify)


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


def _google_nonce(client: TestClient) -> str:
    """Issue a browser-bound nonce and force it into the http test jar."""
    response = client.get("/api/auth/google/nonce")
    assert response.status_code == 200
    nonce = response.json()["nonce"]
    _force_cookie(client, api_server._GOOGLE_NONCE_COOKIE, nonce)
    return nonce


def _start_google_session(
        client: TestClient, monkeypatch: pytest.MonkeyPatch, remember_me: bool = False
) -> str:
    """Complete google login and return the session token (forced into jar)."""
    _mock_google_verify(monkeypatch)
    _google_nonce(client)
    started = client.post(
        "/api/auth/google/session",
        json={"id_token": "valid-token", "remember_me": remember_me},
    )
    assert started.status_code == 200
    token = _session_token(started)
    _force_cookie(client, api_server._SESSION_COOKIE, token)
    return token


def _start_emergency_session(client: TestClient) -> str:
    """Complete emergency-key login and return the session token."""
    started = client.post(
        "/api/auth/emergency/session", json={"key": EMERGENCY_KEY})
    assert started.status_code == 200
    token = _session_token(started)
    _force_cookie(client, api_server._SESSION_COOKIE, token)
    return token


class _CookieOnlyRequest:
    """Minimal request stand-in exposing only the cookie jar.

    Google-vault resolution reads only ``request.cookies`` (never the socket
    peer, unlike local-dev), so this is sufficient for principal resolution.
    """

    def __init__(self, cookies: dict[str, str]):
        self.cookies = cookies


# ---------------------------------------------------------------------------
# 7.4 — POST /api/auth/google/session
# ---------------------------------------------------------------------------


def test_google_session_sets_httponly_lax_secure_cookie(
        google_client: TestClient, monkeypatch: pytest.MonkeyPatch):
    _mock_google_verify(monkeypatch)
    nonce = _google_nonce(google_client)
    assert nonce

    started = google_client.post(
        "/api/auth/google/session", json={"id_token": "valid-token"})
    assert started.status_code == 200
    body = started.json()
    assert body["authenticated"] is True
    assert body["provider"] == "google"
    assert body["label"] == GOOGLE_EMAIL

    cookie = _session_cookie(started)
    assert "httponly" in cookie
    assert "samesite=lax" in cookie
    assert "path=/" in cookie
    assert "secure" in cookie, "google mode must set the Secure flag"
    assert f"max-age={DEFAULT_TTL_SECONDS}" in cookie
    # The browser-bound nonce is consumed on success (single use): the
    # response clears the nonce cookie (Max-Age=0).
    nonce_cleared = [
        h for h in _set_cookies(started)
        if h.startswith(api_server._GOOGLE_NONCE_COOKIE + "=")
    ]
    assert nonce_cleared and "max-age=0" in nonce_cleared[0]

    _force_cookie(google_client, api_server._SESSION_COOKIE, _session_token(started))
    status = google_client.get("/api/auth/session/status").json()
    assert status["authenticated"] is True
    assert status["provider"] == "google"


def test_google_session_remember_me_extends_ttl_to_14_days(
        google_client: TestClient, monkeypatch: pytest.MonkeyPatch):
    _mock_google_verify(monkeypatch)
    _google_nonce(google_client)
    started = google_client.post(
        "/api/auth/google/session",
        json={"id_token": "valid-token", "remember_me": True},
    )
    assert started.status_code == 200
    assert f"max-age={REMEMBER_ME_TTL_SECONDS}" in _session_cookie(started)


def test_google_session_rejects_bad_token_with_401(
        google_client: TestClient, monkeypatch: pytest.MonkeyPatch):
    _mock_google_verify(monkeypatch)
    _google_nonce(google_client)
    rejected = google_client.post(
        "/api/auth/google/session", json={"id_token": "bad-token"})
    assert rejected.status_code == 401
    assert google_client.get(
        "/api/auth/session/status").json()["authenticated"] is False


def test_google_session_requires_browser_bound_nonce(
        google_client: TestClient, monkeypatch: pytest.MonkeyPatch):
    _mock_google_verify(monkeypatch)
    # No nonce was issued for this browser: the login must fail closed.
    missing = google_client.post(
        "/api/auth/google/session", json={"id_token": "valid-token"})
    assert missing.status_code == 401

    # A nonce claim that does not match the issued nonce also fails.
    _google_nonce(google_client)
    mismatched = google_client.post(
        "/api/auth/google/session", json={"id_token": "nonce-mismatch-token"})
    assert mismatched.status_code == 401


def test_google_endpoints_are_forbidden_outside_google_mode(
        google_client: TestClient, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DEMIURGOS_AUTH_MODE", "disabled")
    assert google_client.get("/api/auth/google/nonce").status_code == 403
    assert google_client.post(
        "/api/auth/google/session", json={"id_token": "x"}).status_code == 403


def test_cookie_secure_flag_is_mode_aware(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DEMIURGOS_AUTH_MODE", "google")
    assert api_server._cookie_secure() is True
    monkeypatch.setenv("DEMIURGOS_AUTH_MODE", "local-dev")
    assert api_server._cookie_secure() is False
    monkeypatch.setenv("DEMIURGOS_AUTH_MODE", "disabled")
    assert api_server._cookie_secure() is False


# ---------------------------------------------------------------------------
# 7.4 — POST /api/auth/emergency/session + rotation
# ---------------------------------------------------------------------------


def test_emergency_session_sets_cookie_and_provider(google_client: TestClient):
    _install_emergency_key()
    started = google_client.post(
        "/api/auth/emergency/session", json={"key": EMERGENCY_KEY})
    assert started.status_code == 200
    body = started.json()
    assert body["authenticated"] is True
    assert body["provider"] == "emergency"
    assert body["label"] == EMERGENCY_LABEL

    cookie = _session_cookie(started)
    assert "httponly" in cookie
    assert "samesite=lax" in cookie
    assert "secure" in cookie
    assert f"max-age={DEFAULT_TTL_SECONDS}" in cookie

    _force_cookie(google_client, api_server._SESSION_COOKIE, _session_token(started))
    status = google_client.get("/api/auth/session/status").json()
    assert status["provider"] == "emergency"


def test_emergency_session_rejects_wrong_key_and_rate_limits(
        google_client: TestClient):
    _install_emergency_key()
    for _ in range(5):
        rejected = google_client.post(
            "/api/auth/emergency/session", json={"key": "wrong key"})
        assert rejected.status_code == 401
    # The 6th attempt is blocked by the rate limiter (R-ERK3, S-ERK3c) even
    # with the correct key.
    blocked = google_client.post(
        "/api/auth/emergency/session", json={"key": EMERGENCY_KEY})
    assert blocked.status_code == 401
    assert api_server._emergency_rate_limiter.check() is False


def test_emergency_rotate_requires_an_active_session(google_client: TestClient):
    assert google_client.post("/api/auth/emergency/rotate").status_code == 401


def test_emergency_rotate_with_session_invalidates_old_key(
        google_client: TestClient):
    _install_emergency_key()
    _start_emergency_session(google_client)

    rotated = google_client.post("/api/auth/emergency/rotate")
    assert rotated.status_code == 200
    new_key = rotated.json()["new_key"]
    assert new_key and new_key != EMERGENCY_KEY

    stored = api_server._local_state().snapshot()["capabilities"]["emergency_key_hash"]
    assert emergency_key.verify(
        EMERGENCY_KEY, stored, api_server._emergency_rate_limiter) is False
    assert emergency_key.verify(
        new_key, stored, api_server._emergency_rate_limiter) is True


# ---------------------------------------------------------------------------
# 7.4 — unified status + logout
# ---------------------------------------------------------------------------


def test_unified_status_exposes_provider(
        google_client: TestClient, monkeypatch: pytest.MonkeyPatch):
    status = google_client.get("/api/auth/session/status")
    assert status.status_code == 200
    assert status.json() == {
        "mode": "google",
        "enabled": True,
        "authenticated": False,
        "label": None,
        "provider": None,
    }

    _start_google_session(google_client, monkeypatch)
    status = google_client.get("/api/auth/session/status").json()
    assert status["authenticated"] is True
    assert status["provider"] == "google"
    assert status["label"] == GOOGLE_EMAIL


def test_unified_logout_clears_google_session(
        google_client: TestClient, monkeypatch: pytest.MonkeyPatch):
    token = _start_google_session(google_client, monkeypatch)

    logged_out = google_client.delete("/api/auth/session")
    assert logged_out.status_code == 200
    assert logged_out.json()["authenticated"] is False
    assert google_client.get(
        "/api/auth/session/status").json()["authenticated"] is False
    # Server-side revocation: the session record is gone (R-GA3, S-GA3a).
    with api_server._local_session_lock:
        assert api_server._hash_token(token) not in api_server._sessions


# ---------------------------------------------------------------------------
# 7.5 — _resolve_principal with a google session
# ---------------------------------------------------------------------------


def test_resolve_principal_with_google_session_returns_edit_principal(
        google_client: TestClient, monkeypatch: pytest.MonkeyPatch):
    token = _start_google_session(google_client, monkeypatch)

    principal = api_server._resolve_principal(
        _CookieOnlyRequest({api_server._SESSION_COOKIE: token}))
    assert isinstance(principal, api_server.EditPrincipal)
    assert principal.id == GOOGLE_SUB
    assert principal.label == GOOGLE_EMAIL

    with api_server._local_session_lock:
        record = api_server._sessions[api_server._hash_token(token)]
    assert record["provider"] == "google"
    assert record["principal_id"] == GOOGLE_SUB
    assert record["label"] == GOOGLE_EMAIL

    # The seam integrates: a gated write accepts the google principal via the
    # browser cookie alone (R-GA4 — no per-request network needed).
    target = api_server.MUNDOS_DIR / "test_mundo" / "lore" / "00_inicio.md"
    base_rev = hashlib.sha256(target.read_bytes()).hexdigest()
    confirmation = google_client.post(
        "/api/test_mundo/lore/edit-confirmation?path=00_inicio.md",
        json={
            "edit_id": "e1",
            "base_revision": base_rev,
            "proposed_content": "# Edit\n",
        },
    )
    assert confirmation.status_code == 200


def test_resolve_principal_accepts_emergency_session(google_client: TestClient):
    _install_emergency_key()
    token = _start_emergency_session(google_client)

    principal = api_server._resolve_principal(
        _CookieOnlyRequest({api_server._SESSION_COOKIE: token}))
    assert isinstance(principal, api_server.EditPrincipal)
    assert principal.id.startswith("emergency-session-")
    assert principal.label == EMERGENCY_LABEL


def test_resolve_principal_fails_closed_without_google_session(
        google_client: TestClient):
    assert api_server._resolve_principal(_CookieOnlyRequest({})) is None