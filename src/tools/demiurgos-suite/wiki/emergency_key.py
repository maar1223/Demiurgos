"""Offline emergency recovery key for vault cold-start (auth-vault-credentials).

R-ERK1..R-ERK4: generated recovery code (EFF long wordlist, 8-10 words),
stored ONLY as an Argon2id hash, verified 100% offline with in-memory rate
limiting and exponential backoff, and rotated by atomically replacing the
hash in ``local_state.json``.

ZERO-HTTP-IMPORT GUARANTEE (R-ERK2): this module must never import an HTTP
client (``requests``, ``httpx``, ``urllib``, ``urllib3``) — enforced by the
unit tests via ``sys.modules`` inspection. Verification is pure local:
rate-limit check + Argon2id comparison, no network calls.

The EFF long wordlist (``wordlists/eff_large_wordlist.txt``) is the standard
diceware list published by the Electronic Frontier Foundation (CC-BY 3.0 US):
7776 words, ~13 bits of entropy per word; 8-10 words ≈ 104-130 bits.
"""

from __future__ import annotations

import os
import secrets
from typing import TYPE_CHECKING, Any

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

if TYPE_CHECKING:
    from local_state import LocalState

# EFF long wordlist: <5-digit index>\t<word> per line.
# NOTE: uses os.path (not pathlib) — Python 3.12's pathlib imports
# urllib.parse transitively, which would break the zero-HTTP sys.modules
# assertion (R-ERK2). os.path stays free of any urllib import.
_WORDLIST_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "wordlists", "eff_large_wordlist.txt"
)
_MIN_WORDS = 8
_MAX_WORDS = 10

_HASHER = PasswordHasher()


class RateLimiter:
    """In-memory rate limiter with exponential backoff (R-ERK3).

    Kill-switch property: counters live in memory per instance and reset on
    process restart — acceptable because filesystem access means the vault is
    already compromised (design decision). ``max_attempts`` failures are
    allowed; further attempts are blocked until the limiter is reset (success)
    or the process restarts. The backoff duration grows exponentially as
    ``2 ** failures`` seconds.
    """

    def __init__(self, max_attempts: int = 5) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")
        self.max_attempts = max_attempts
        self._failures: dict[str, int] = {}

    def _key(self, subject: str | None) -> str:
        return subject or "default"

    def check(self, subject: str | None = None) -> bool:
        """True if an attempt is allowed now; False if blocked."""
        return self._failures.get(self._key(subject), 0) < self.max_attempts

    def failures(self, subject: str | None = None) -> int:
        """Current consecutive-failure count for the subject."""
        return self._failures.get(self._key(subject), 0)

    def backoff_seconds(self, subject: str | None = None) -> int:
        """Exponential backoff for the subject: ``2 ** failures`` seconds."""
        return 2 ** self.failures(subject)

    def record_failure(self, subject: str | None = None) -> None:
        """Increment the failure counter for the subject."""
        key = self._key(subject)
        self._failures[key] = self._failures.get(key, 0) + 1

    def reset(self, subject: str | None = None) -> None:
        """Clear the failure counter (called on successful verification)."""
        self._failures.pop(self._key(subject), None)


def _load_wordlist() -> tuple[str, ...]:
    """Load the EFF long wordlist into an immutable tuple.

    Parses the ``<index>\\t<word>`` format; any malformed line is skipped.
    Raises ``RuntimeError`` when the wordlist is missing or unusable so the
    failure is loud at generation time, never silent.
    """
    words: list[str] = []
    try:
        with open(_WORDLIST_PATH, encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    except OSError as exc:
        raise RuntimeError(f"EFF wordlist unreadable at {_WORDLIST_PATH}: {exc}") from exc
    for line in lines:
        line = line.strip()
        if not line:
            continue
        parts = line.split("\t")
        if len(parts) == 2 and parts[1]:
            words.append(parts[1])
        elif len(parts) == 1 and parts[0].isalpha():
            words.append(parts[0])
    if len(words) < 100:
        raise RuntimeError(f"EFF wordlist unusable: only {len(words)} words loaded")
    return tuple(words)


_WORDS: tuple[str, ...] | None = None


def _words() -> tuple[str, ...]:
    global _WORDS
    if _WORDS is None:
        _WORDS = _load_wordlist()
    return _WORDS


def generate_code() -> str:
    """Generate a high-entropy recovery code (EFF long wordlist, 8-10 words).

    Word count is chosen cryptographically from 8-10 and each word via
    ``secrets.choice`` — ~104-130 bits of entropy. Returns the plaintext code
    to be displayed ONCE to the user; only the hash is ever stored.
    """
    count = secrets.randbelow(_MAX_WORDS - _MIN_WORDS + 1) + _MIN_WORDS
    words = [secrets.choice(_words()) for _ in range(count)]
    return " ".join(words)


def hash_code(plaintext: str) -> str:
    """Hash a recovery code with Argon2id (argon2-cffi reference implementation).

    Returns the encoded hash string (salt + parameters embedded); the
    plaintext is never stored.
    """
    return _HASHER.hash(plaintext)


def verify(submitted: str, stored_hash: str | None, rate_limiter: RateLimiter) -> bool:
    """Verify a submitted code against the stored Argon2id hash, 100% offline.

    Order of checks:
    1. Rate-limit gate: a blocked subject is rejected WITHOUT touching the
       hash (no work for an attacker, S-ERK3c).
    2. No stored hash (key never generated): counted as a failure.
    3. Argon2id comparison: mismatch is counted as a failure (S-ERK3b); a
       match resets the limiter (S-ERK3a) and returns True.

    Raises nothing on verification outcomes — always returns bool.
    """
    if not rate_limiter.check():
        return False
    if not stored_hash:
        rate_limiter.record_failure()
        return False
    try:
        _HASHER.verify(stored_hash, submitted)
    except (VerificationError, InvalidHashError):
        rate_limiter.record_failure()
        return False
    rate_limiter.reset()
    return True


def rotate(local_state: LocalState) -> tuple[str, str]:
    """Generate a new recovery code and persist its hash atomically (R-ERK4).

    Reads the current registry snapshot, replaces ``capabilities.
    emergency_key_hash`` with the new Argon2id hash (invalidating the old
    key), and commits atomically via ``LocalState.atomic_commit``.

    Returns ``(new_plaintext, new_hash)`` — the plaintext is displayed once;
    the hash is what gets stored.
    """
    plaintext = generate_code()
    new_hash = hash_code(plaintext)
    snapshot: dict[str, Any] = local_state.snapshot()
    capabilities = snapshot.setdefault("capabilities", {})
    capabilities["emergency_key_hash"] = new_hash
    local_state.atomic_commit(snapshot)
    return plaintext, new_hash