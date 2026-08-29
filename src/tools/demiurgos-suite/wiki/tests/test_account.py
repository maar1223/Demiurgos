"""R-AC-01..R-AC-05 + R-ERK-01 — local account lifecycle (auth-vault-credentials).

Unit tests for the account module wrapping emergency_key primitives:

- create_account: with/without password, words ALWAYS generated + hashed,
  Argon2id password_hash, atomic commit survives reload.
- verify_password / verify_words: correct value passes and resets the limiter;
  a wrong value counts a failure; a blocked limiter rejects even the correct
  value. Password and words verification use SEPARATE RateLimiter instances
  (R-ERK-02, S-ERK-02a/b).
- update_account: username change, password change, password removal.
- rotate_words: new words persisted, old words invalidated, other account
  fields preserved.
- get_account: None before creation, slot after.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_WIKI = Path(__file__).resolve().parents[1]
if str(_WIKI) not in sys.path:
    sys.path.insert(0, str(_WIKI))

from account import (  # noqa: E402
    create_account,
    get_account,
    rotate_words,
    update_account,
    verify_password,
    verify_words,
)
from emergency_key import RateLimiter, verify  # noqa: E402
from local_state import LocalState  # noqa: E402


@pytest.fixture()
def state_file(tmp_path: Path) -> Path:
    return tmp_path / "data" / "local-state.json"


# ---------------------------------------------------------------------------
# R-AC-01 — create_account
# ---------------------------------------------------------------------------


def test_create_account_with_password_stores_hashes(state_file: Path) -> None:
    state = LocalState(state_file)
    words, words_hash = create_account(state, "ada", "correct horse")

    assert len(words.split()) in range(8, 11), "words must be 8-10 EFF words"
    account = state.snapshot()["capabilities"]["account"]
    assert account["username"] == "ada"
    assert account["words_hash"] == words_hash
    assert account["password_hash"].startswith("$argon2id$")

    limiter = RateLimiter()
    assert verify(words, words_hash, limiter) is True
    assert verify("correct horse", account["password_hash"], limiter) is True


def test_create_account_passwordless_keeps_null_password(state_file: Path) -> None:
    state = LocalState(state_file)
    words, words_hash = create_account(state, "ada", None)

    assert words, "words are ALWAYS generated (ownership + recovery, S-AC-01b)"
    account = state.snapshot()["capabilities"]["account"]
    assert account["username"] == "ada"
    assert account["password_hash"] is None
    assert account["words_hash"] == words_hash


def test_create_account_commits_atomically_and_survives_reload(state_file: Path) -> None:
    state = LocalState(state_file)
    create_account(state, "ada", "secret")

    reloaded = LocalState(state_file).snapshot()
    assert reloaded["capabilities"]["account"]["username"] == "ada"
    assert reloaded["capabilities"]["account"]["password_hash"].startswith("$argon2id$")
    assert reloaded["revision"] == 1


# ---------------------------------------------------------------------------
# R-AC-02 — verify_password (rate-limited)
# ---------------------------------------------------------------------------


def test_verify_password_accepts_correct_and_resets_limiter(state_file: Path) -> None:
    state = LocalState(state_file)
    create_account(state, "ada", "correct horse")
    limiter = RateLimiter()
    account = get_account(state)
    assert account is not None

    assert verify_password("wrong", account["password_hash"], limiter) is False
    assert limiter.failures() == 1
    assert verify_password("correct horse", account["password_hash"], limiter) is True
    assert limiter.failures() == 0, "success must reset the limiter"


def test_verify_password_blocks_after_max_attempts(state_file: Path) -> None:
    state = LocalState(state_file)
    create_account(state, "ada", "correct horse")
    limiter = RateLimiter(max_attempts=5)
    account = get_account(state)

    for _ in range(5):
        assert verify_password("wrong", account["password_hash"], limiter) is False
    assert limiter.check() is False
    # Even the correct password is rejected while blocked (S-AC-02c).
    assert verify_password("correct horse", account["password_hash"], limiter) is False


def test_verify_password_fails_when_no_password_set(state_file: Path) -> None:
    state = LocalState(state_file)
    create_account(state, "ada", None)
    limiter = RateLimiter()

    assert verify_password("anything", None, limiter) is False
    assert limiter.failures() == 1


# ---------------------------------------------------------------------------
# R-AC-02 + R-ERK-02 — verify_words (rate-limited, independent limiter)
# ---------------------------------------------------------------------------


def test_verify_words_accepts_correct_and_resets_limiter(state_file: Path) -> None:
    state = LocalState(state_file)
    words, _ = create_account(state, "ada", "correct horse")
    limiter = RateLimiter()
    account = get_account(state)

    assert verify_words("not the words", account["words_hash"], limiter) is False
    assert limiter.failures() == 1
    assert verify_words(words, account["words_hash"], limiter) is True
    assert limiter.failures() == 0


def test_words_rate_limit_is_independent_from_password(state_file: Path) -> None:
    """S-ERK-02a — exhausting the password limiter must not block words."""
    state = LocalState(state_file)
    words, _ = create_account(state, "ada", "correct horse")
    account = get_account(state)
    password_limiter = RateLimiter(max_attempts=5)
    words_limiter = RateLimiter(max_attempts=5)

    for _ in range(5):
        assert verify_password(
            "wrong", account["password_hash"], password_limiter) is False
    assert password_limiter.check() is False

    # Words verification runs on its own limiter: still allowed.
    assert verify_words(words, account["words_hash"], words_limiter) is True
    assert words_limiter.check() is True


# ---------------------------------------------------------------------------
# R-AC-05 — update_account
# ---------------------------------------------------------------------------


def test_update_account_changes_username(state_file: Path) -> None:
    state = LocalState(state_file)
    create_account(state, "ada", "correct horse")
    update_account(state, new_username="ada lovelace")

    account = get_account(state)
    assert account["username"] == "ada lovelace"
    assert account["words_hash"], "words hash must be preserved"


def test_update_account_changes_password_and_invalidates_old(state_file: Path) -> None:
    state = LocalState(state_file)
    create_account(state, "ada", "old password")
    update_account(state, new_password="new password")

    account = get_account(state)
    limiter = RateLimiter()
    assert verify_password("old password", account["password_hash"], limiter) is False
    assert verify_password("new password", account["password_hash"], limiter) is True


def test_update_account_removes_password(state_file: Path) -> None:
    state = LocalState(state_file)
    create_account(state, "ada", "correct horse")
    update_account(state, remove_password=True)

    assert get_account(state)["password_hash"] is None


def test_update_account_remove_password_takes_precedence(state_file: Path) -> None:
    state = LocalState(state_file)
    create_account(state, "ada", "correct horse")
    update_account(state, new_password="ignored", remove_password=True)

    assert get_account(state)["password_hash"] is None


# ---------------------------------------------------------------------------
# R-ERK-01 — rotate_words
# ---------------------------------------------------------------------------


def test_rotate_words_persists_new_hash_and_invalidates_old(state_file: Path) -> None:
    state = LocalState(state_file)
    old_words, old_hash = create_account(state, "ada", "correct horse")

    new_words, new_hash = rotate_words(state)
    assert new_words != old_words
    assert new_hash != old_hash

    account = get_account(state)
    assert account["words_hash"] == new_hash
    assert account["username"] == "ada"
    assert account["password_hash"], "rotation must not touch the password"

    limiter = RateLimiter()
    assert verify(old_words, new_hash, limiter) is False
    assert verify(new_words, new_hash, limiter) is True


# ---------------------------------------------------------------------------
# get_account
# ---------------------------------------------------------------------------


def test_get_account_returns_none_before_creation(state_file: Path) -> None:
    state = LocalState(state_file)
    assert get_account(state) is None


def test_get_account_returns_slot_after_creation(state_file: Path) -> None:
    state = LocalState(state_file)
    create_account(state, "ada", "correct horse")

    account = get_account(state)
    assert account is not None
    assert set(account) == {"username", "password_hash", "words_hash"}
    assert account["username"] == "ada"
    assert account["password_hash"].startswith("$argon2id$")