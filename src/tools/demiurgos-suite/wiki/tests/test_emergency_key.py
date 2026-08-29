"""R-ERK1..R-ERK4 — offline emergency recovery key (auth-vault-credentials).

Unit tests covering:
- 7.2: word count 8-10 + entropy, Argon2id hash/verify round-trip,
  rate-limit blocks after 5 failures, and the ZERO-HTTP-IMPORT guarantee
  (``sys.modules`` inspection in a fresh subprocess).
- 7.3: ``RateLimiter`` exponential backoff (``2 ** failures``) and reset.
- R-ERK4: ``rotate`` atomically persists a new hash and invalidates the old.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

_WIKI = Path(__file__).resolve().parents[1]
if str(_WIKI) not in sys.path:
    sys.path.insert(0, str(_WIKI))

import emergency_key  # noqa: E402
from emergency_key import RateLimiter, generate_code, hash_code, rotate, verify  # noqa: E402
from local_state import LocalState  # noqa: E402

BANNED_HTTP_MODULES = ("requests", "httpx", "urllib", "urllib3")


# ---------------------------------------------------------------------------
# 7.2 — generation, hashing, verification, rate limiting, zero HTTP imports
# ---------------------------------------------------------------------------


def test_generated_code_has_8_to_10_words() -> None:
    for _ in range(30):
        code = generate_code()
        words = code.split()
        assert len(words) in range(8, 11), f"word count {len(words)} outside 8-10"
        # The EFF list legitimately contains hyphenated words (drop-down,
        # yo-yo, ...): "plain" means ASCII letters with optional hyphens.
        assert all(
            all(ch.isalpha() or ch == "-" for ch in word) for word in words
        ), "every word must be plain alpha (hyphens allowed)"


def test_generated_codes_are_unique_and_high_entropy() -> None:
    codes = {generate_code() for _ in range(50)}
    assert len(codes) == 50, "50 generated codes must be distinct (entropy sanity)"


def test_hash_is_argon2id_and_verify_round_trips() -> None:
    limiter = RateLimiter()
    plaintext = generate_code()
    stored = hash_code(plaintext)
    assert stored.startswith("$argon2id$"), "hash must use Argon2id"
    assert plaintext not in stored, "plaintext must never appear in the hash"
    assert verify(plaintext, stored, limiter) is True
    assert limiter.failures() == 0, "limiter must be reset on success"


def test_verify_rejects_wrong_code_and_counts_failure() -> None:
    limiter = RateLimiter()
    stored = hash_code("right-code")
    assert verify("wrong-code", stored, limiter) is False
    assert limiter.failures() == 1
    assert verify("wrong-code", stored, limiter) is False
    assert limiter.failures() == 2


def test_verify_blocks_after_five_failures() -> None:
    limiter = RateLimiter(max_attempts=5)
    stored = hash_code("right-code")
    for _ in range(5):
        assert verify("wrong-code", stored, limiter) is False
    assert limiter.check() is False, "limiter must block after max_attempts"
    # Even the CORRECT code is rejected while blocked (S-ERK3c).
    assert verify("right-code", stored, limiter) is False


def test_verify_without_stored_hash_is_failure() -> None:
    limiter = RateLimiter()
    assert verify("any-code", None, limiter) is False
    assert limiter.failures() == 1


def test_verify_with_corrupt_hash_is_failure() -> None:
    limiter = RateLimiter()
    assert verify("any-code", "not-a-valid-argon2-hash", limiter) is False
    assert limiter.failures() == 1


def test_rotate_persists_new_hash_and_invalidates_old(tmp_path: Path) -> None:
    state = LocalState(tmp_path / "data" / "local-state.json")
    # Seed an existing emergency key so rotation has something to replace.
    old_plaintext, old_hash = rotate(state)
    assert state.snapshot()["capabilities"]["emergency_key_hash"] == old_hash

    new_plaintext, new_hash = rotate(state)
    assert new_hash != old_hash, "rotation must invalidate the old hash"
    assert new_plaintext != old_plaintext

    reloaded = LocalState(tmp_path / "data" / "local-state.json").snapshot()
    assert reloaded["capabilities"]["emergency_key_hash"] == new_hash
    # Old code rejected, new code accepted against the persisted hash.
    limiter = RateLimiter()
    assert verify(old_plaintext, new_hash, limiter) is False
    assert verify(new_plaintext, new_hash, limiter) is True


def test_module_has_zero_http_imports() -> None:
    """R-ERK2 — verification path must be 100% offline.

    Import the module in a FRESH subprocess (the pytest parent process may
    legitimately hold HTTP clients from other test modules) and assert that
    no banned HTTP module appears in ``sys.modules``.
    """
    probe = (
        "import sys; "
        "import emergency_key; "
        "found = sorted(m for m in sys.modules if m.split('.')[0] in %r); "
        "print(found)" % (BANNED_HTTP_MODULES,)
    )
    result = subprocess.run(
        [sys.executable, "-c", probe],
        capture_output=True,
        text=True,
        cwd=str(_WIKI),
        timeout=30,
    )
    assert result.returncode == 0, f"import failed: {result.stderr}"
    assert result.stdout.strip() == "[]", (
        f"HTTP imports leaked into emergency_key: {result.stdout.strip()}"
    )


# ---------------------------------------------------------------------------
# 7.3 — RateLimiter exponential backoff + reset
# ---------------------------------------------------------------------------


def test_rate_limiter_exponential_backoff() -> None:
    limiter = RateLimiter(max_attempts=5)
    assert limiter.check() is True
    assert limiter.backoff_seconds() == 2**0
    for failures in range(1, 6):
        limiter.record_failure()
        assert limiter.backoff_seconds() == 2**failures, (
            f"backoff must be 2**{failures} after {failures} failures"
        )
    assert limiter.failures() == 5
    assert limiter.check() is False, "blocked once failures reach max_attempts"


def test_rate_limiter_reset_clears_failures() -> None:
    limiter = RateLimiter(max_attempts=5)
    for _ in range(5):
        limiter.record_failure()
    assert limiter.check() is False
    limiter.reset()
    assert limiter.check() is True
    assert limiter.failures() == 0
    assert limiter.backoff_seconds() == 1


def test_rate_limiter_rejects_bad_max_attempts() -> None:
    with pytest.raises(ValueError):
        RateLimiter(max_attempts=0)