"""Hand-rolled SemVer 2.0.0 precedence for the in-app updater.

This module implements version parsing and precedence per
`Semantic Versioning 2.0.0 <https://semver.org/spec/v2.0.0.html>`_ §11. It is a
small, dependency-free library so the update-check path can order a running
version against a channel pointer without pulling in any packaging dependency.

Design constraints (hard, from the change spec):

- Build metadata (``+build``) is parsed off and discarded; it NEVER affects
  precedence.
- A prerelease is lower than its associated release
  (``0.2.0-beta.1 < 0.2.0``).
- Prerelease identifiers compare identifier by identifier: numeric identifiers
  compare numerically, a numeric identifier is lower than an alphanumeric one,
  alphanumeric identifiers compare ASCII-lexicographically, and a longer
  identifier list wins when all shared identifiers are equal
  (``1.0.0-alpha < 1.0.0-alpha.1``).
- This module MUST NOT import ``packaging`` nor reuse
  ``methodology_library._version_key()``; the latter dot-splits the whole
  version and therefore sorts ``0.2.0-beta.1`` ABOVE ``0.2.0``.
"""

from __future__ import annotations

__all__ = ["SemVerError", "parse_version", "is_prerelease", "compare"]


class SemVerError(ValueError):
    """Raised when a value is not a parseable SemVer version."""


def _strip_prefix(value: str) -> str:
    """Drop a single leading ``v``/``V`` (tolerated installer/tag prefix)."""
    if value[:1] in ("v", "V"):
        return value[1:]
    return value


def parse_version(value: str) -> tuple[int, int, int, tuple[str, ...]]:
    """Parse *value* into ``(major, minor, patch, prerelease)``.

    The leading ``v`` is stripped and ``+build`` metadata is discarded (it never
    affects precedence). The remainder is split at the first ``-`` into the core
    version and the prerelease; the core must be exactly three integer
    identifiers, and the prerelease is a tuple of dot-split identifiers
    (empty when the version is a release).

    Raises ``SemVerError`` for anything that does not conform.
    """
    if not isinstance(value, str):
        raise SemVerError(f"version must be a string, got {type(value).__name__}")

    text = _strip_prefix(value.strip())

    # Build metadata is ignored for precedence: drop everything from the first '+'.
    text = text.partition("+")[0]

    core_text, separator, prerelease_text = text.partition("-")

    core_parts = core_text.split(".")
    if len(core_parts) != 3:
        raise SemVerError(
            f"core version must be 'major.minor.patch', got {core_text!r}"
        )

    numbers: list[int] = []
    for field, part in zip(("major", "minor", "patch"), core_parts):
        try:
            numbers.append(int(part))
        except ValueError:
            raise SemVerError(
                f"{field} identifier is not an integer: {part!r}"
            ) from None

    prerelease: tuple[str, ...] = ()
    if separator:
        identifiers = prerelease_text.split(".")
        if any(identifier == "" for identifier in identifiers):
            raise SemVerError(
                f"prerelease identifiers must not be empty: {prerelease_text!r}"
            )
        prerelease = tuple(identifiers)

    return (numbers[0], numbers[1], numbers[2], prerelease)


def is_prerelease(value: str) -> bool:
    """Return ``True`` when *value* carries a prerelease identifier list."""
    return bool(parse_version(value)[3])


def _compare_prerelease(a: tuple[str, ...], b: tuple[str, ...]) -> int:
    """Order two non-empty prerelease identifier tuples per SemVer §11."""
    for left, right in zip(a, b):
        if left == right:
            continue
        left_numeric = left.isdigit()
        right_numeric = right.isdigit()
        if left_numeric and right_numeric:
            left_int, right_int = int(left), int(right)
            if left_int == right_int:
                continue
            return -1 if left_int < right_int else 1
        if left_numeric:  # numeric identifiers are always lower than alphanumeric
            return -1
        if right_numeric:
            return 1
        return -1 if left < right else 1  # ASCII lexicographic (str compare)

    # All shared identifiers are equal: the longer list wins.
    if len(a) == len(b):
        return 0
    return -1 if len(a) < len(b) else 1


def compare(a: str, b: str) -> int:
    """Compare two versions, returning ``-1``, ``0`` or ``1``.

    Implements SemVer 2.0.0 §11 precedence: major, then minor, then patch, then
    prerelease. Build metadata never affects the result. Raises ``SemVerError``
    when either operand cannot be parsed.
    """
    parsed_a = parse_version(a)
    parsed_b = parse_version(b)

    core_a = parsed_a[:3]
    core_b = parsed_b[:3]
    if core_a != core_b:
        return -1 if core_a < core_b else 1

    pre_a, pre_b = parsed_a[3], parsed_b[3]
    if not pre_a and not pre_b:
        return 0
    if not pre_a:  # a is a release, b is a prerelease -> a is higher
        return 1
    if not pre_b:
        return -1
    return _compare_prerelease(pre_a, pre_b)
