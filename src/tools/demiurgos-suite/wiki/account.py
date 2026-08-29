"""Local account lifecycle for credentials-mode auth (auth-vault-credentials).

Wraps the offline emergency_key primitives (EFF word generation, Argon2id
hashing, rate-limited verification) for the account slot stored in the local
state registry: ``capabilities.account = {username, password_hash,
words_hash}``.

The recovery words are ALWAYS generated at account creation and only their
Argon2id hash is stored; they are the ownership + recovery key. ``password_hash``
is null for passwordless accounts. Every write goes through
``LocalState.atomic_commit`` so the slot stays single-source-of-truth.
"""

from __future__ import annotations

from typing import Any

from emergency_key import RateLimiter, generate_code, hash_code, verify
from local_state import LocalState


def create_account(
    local_state: LocalState,
    username: str,
    password: str | None,
) -> tuple[str, str]:
    """Create the local account (R-AC-01); returns (words_plaintext, words_hash).

    Words are generated unconditionally and shown to the user exactly once;
    only their Argon2id hash is stored. ``password_hash`` is the Argon2id hash
    of the optional password, or null for a passwordless account. The account
    slot is committed atomically.
    """
    words = generate_code()
    words_hash = hash_code(words)
    password_hash = hash_code(password) if password else None
    snapshot = local_state.snapshot()
    capabilities = snapshot.setdefault("capabilities", {})
    capabilities["account"] = {
        "username": username,
        "password_hash": password_hash,
        "words_hash": words_hash,
    }
    local_state.atomic_commit(snapshot)
    return words, words_hash


def verify_password(
    password: str,
    stored_hash: str | None,
    rate_limiter: RateLimiter,
) -> bool:
    """Verify a password against its Argon2id hash (R-AC-02), rate-limited."""
    return verify(password, stored_hash, rate_limiter)


def verify_words(
    words: str,
    stored_hash: str | None,
    rate_limiter: RateLimiter,
) -> bool:
    """Verify recovery words against their Argon2id hash, rate-limited."""
    return verify(words, stored_hash, rate_limiter)


def update_account(
    local_state: LocalState,
    new_username: str | None = None,
    new_password: str | None = None,
    remove_password: bool = False,
) -> None:
    """Update username and/or password (R-AC-05), committing atomically.

    ``remove_password=True`` clears the password (back to passwordless) and
    takes precedence over ``new_password``. The words hash is preserved.
    """
    snapshot = local_state.snapshot()
    account = snapshot.get("capabilities", {}).get("account", {})
    if new_username:
        account["username"] = new_username
    if remove_password:
        account["password_hash"] = None
    elif new_password is not None:
        account["password_hash"] = hash_code(new_password)
    snapshot.setdefault("capabilities", {})["account"] = account
    local_state.atomic_commit(snapshot)


def rotate_words(local_state: LocalState) -> tuple[str, str]:
    """Generate new recovery words and persist their hash (R-ERK-01).

    Returns ``(words_plaintext, words_hash)``. The plaintext is displayed once;
    the old words are invalidated by the atomic commit of the new hash.
    """
    words = generate_code()
    words_hash = hash_code(words)
    snapshot = local_state.snapshot()
    account = snapshot.setdefault("capabilities", {}).setdefault("account", {})
    account["words_hash"] = words_hash
    local_state.atomic_commit(snapshot)
    return words, words_hash


def get_account(local_state: LocalState) -> dict[str, Any] | None:
    """Read the account slot; None when no account has been created.

    The slot always exists in the registry (``default_state`` seeds it with
    nulls); an account counts as created once it carries a username and a
    words hash.
    """
    account = local_state.snapshot().get("capabilities", {}).get("account")
    if not isinstance(account, dict):
        return None
    if not account.get("username") and not account.get("words_hash"):
        return None
    return account