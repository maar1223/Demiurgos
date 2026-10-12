# -*- coding: utf-8 -*-
"""Content scan — secret + PII rules for the bug-report bundle (S1a).

This module owns two rule sets:

* ``SECRET_RULE_*`` — a Python port of the deny patterns declared in
  ``scripts/secret_scan.sh`` (the repository's SINGLE source of truth).
  ``tests/test_content_scan.py`` parses the shell ``RULES_SRC`` heredoc out of
  that script and asserts these names and pattern strings are byte-identical,
  so ``secret_scan.sh`` stays authoritative and any divergence fails CI.

* ``REPORT_RULE_*`` — report-specific deny patterns, deliberately NOT part of
  the shared secret-scan rule set. They cover the additional privacy classes a
  public issue body / log bundle must not expose: local file paths, usernames,
  hostnames, private network addresses, e-mail addresses, and secrets beyond
  the four shared rules. They are reviewed as a distinct rule set.

The functions never retain a matched value: :func:`scan_secret_lines` reports
only ``(line, rule)``; :func:`redact_secrets` replaces the whole matching line
with ``[redacted: <rule>]``; :func:`scrub_pii` replaces each finding with a
neutral placeholder while preserving the surrounding reproduction structure.
"""

from __future__ import annotations

import re
from typing import Dict, List, Tuple

# ---------------------------------------------------------------------------
# Shared rule set — byte-identical to the ``RULES_SRC`` heredoc in
# scripts/secret_scan.sh. Keep this block in lockstep with that heredoc; the
# parity test in tests/test_content_scan.py enforces it.
# ---------------------------------------------------------------------------
SECRET_RULE_NAMES: Tuple[str, ...] = (
    "bot-token",
    "openai-key",
    "google-api-key",
    "author-path",
)

SECRET_RULE_PATTERNS: Dict[str, str] = {
    "bot-token": r"[0-9]{8,10}:[A-Za-z0-9_-]{35}",
    "openai-key": r"sk-[A-Za-z0-9_-]{20,}",
    "google-api-key": r"AIza[0-9A-Za-z_-]{35}",
    "author-path": r"H:\\|/home/|C:\\Users|spreadsheetId",
}

# ---------------------------------------------------------------------------
# Report-specific rule set (NOT part of the shared secret-scan rules).
# These are privacy findings for a public issue body / log bundle.
# ---------------------------------------------------------------------------
REPORT_RULE_NAMES: Tuple[str, ...] = (
    "local-path",
    "username",
    "hostname",
    "private-ip",
    "email",
    "extra-secret",
)

REPORT_RULE_PATTERNS: Dict[str, str] = {
    # Absolute OS paths (POSIX + Windows drive) outside the home directories,
    # e.g. /var/log/api.log, /opt/app, D:\builds\out.
    "local-path": (
        r"(?:[A-Za-z]:\\|/)(?:var|tmp|etc|opt|root|mnt|media|srv|private"
        r"|Applications|usr|bin)(?:[/\\][^\s\"'<>|]+)*"
    ),
    # Local account usernames in the common home-directory forms.
    "username": (
        r"(?<=/home/)[A-Za-z0-9][A-Za-z0-9._-]*"
        r"|(?<=/Users/)[A-Za-z0-9][A-Za-z0-9._-]*"
        r"|(?<=C:\\Users\\)[A-Za-z0-9][A-Za-z0-9._-]*"
    ),
    # Machine hostnames: an explicit host/hostname field, or a <name>.local/
    # .lan-style host. Deliberately excludes the public repo host the report
    # links to (github.com).
    "hostname": (
        r"\bhost(?:name)?\s*[:=]\s*[A-Za-z0-9][A-Za-z0-9.-]*"
        r"|\b[A-Za-z0-9][A-Za-z0-9-]*\.(?:local|lan|internal|home|corp)\b"
    ),
    # Private network addresses (RFC1918) + loopback.
    "private-ip": (
        r"\b(?:10\.\d{1,3}\.\d{1,3}\.\d{1,3}"
        r"|192\.168\.\d{1,3}\.\d{1,3}"
        r"|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}"
        r"|127\.\d{1,3}\.\d{1,3}\.\d{1,3})\b"
    ),
    # E-mail addresses.
    "email": r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b",
    # Secrets beyond the four shared rules: common well-known token shapes.
    "extra-secret": (
        r"\b(?:gh[pousr]_[A-Za-z0-9]{36,}"
        r"|github_pat_[A-Za-z0-9_]{20,}"
        r"|AKIA[0-9A-Z]{16}"
        r"|xox[baprs]-[A-Za-z0-9-]{10,}"
        r"|eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,})\b"
    ),
}

# Neutral placeholders used by scrub_pii, one per report-specific rule.
_PLACEHOLDERS: Dict[str, str] = {
    "local-path": "<path>",
    "username": "<username>",
    "hostname": "<hostname>",
    "private-ip": "<private-ip>",
    "email": "<email>",
    "extra-secret": "<secret>",
}

# Combined lookup — shared rules first, then report-specific rules.
ALL_RULE_NAMES: Tuple[str, ...] = SECRET_RULE_NAMES + REPORT_RULE_NAMES
_ALL_RULE_PATTERNS: Dict[str, str] = {**SECRET_RULE_PATTERNS, **REPORT_RULE_PATTERNS}
_ALL_RULE_REGEX: Dict[str, "re.Pattern[str]"] = {
    name: re.compile(pattern) for name, pattern in _ALL_RULE_PATTERNS.items()
}


def scan_secret_lines(text: str) -> List[Tuple[int, str]]:
    """Return 1-based ``(line, rule)`` for every deny-rule hit in ``text``.

    Scans the shared AND report rule sets. A line matching several rules yields
    one entry per matching rule, in rule declaration order. The matched value is
    never returned — only its line number and rule name.
    """
    hits: List[Tuple[int, str]] = []
    if not text:
        return hits
    for lineno, line in enumerate(text.splitlines(), start=1):
        for name in ALL_RULE_NAMES:
            if _ALL_RULE_REGEX[name].search(line):
                hits.append((lineno, name))
    return hits


def redact_secrets(text: str) -> Tuple[str, int]:
    """Replace each deny-rule line with ``[redacted: <rule>]``.

    Returns ``(redacted_text, redacted_line_count)``. When a line matches more
    than one rule, the first declared rule names the placeholder. The raw
    matched value is never retained.
    """
    if not text:
        return text, 0
    out_lines: List[str] = []
    redacted = 0
    for line in text.split("\n"):
        matched = None
        for name in ALL_RULE_NAMES:
            if _ALL_RULE_REGEX[name].search(line):
                matched = name
                break
        if matched is None:
            out_lines.append(line)
        else:
            out_lines.append("[redacted: %s]" % matched)
            redacted += 1
    return "\n".join(out_lines), redacted


def scrub_pii(text: str) -> Tuple[str, int]:
    """Replace report-specific PII findings with neutral placeholders.

    Covers local paths, usernames, hostnames, private network addresses,
    e-mail addresses, and extra secrets, preserving the surrounding
    reproduction structure. Returns ``(scrubbed_text, replacement_count)``.
    """
    if not text:
        return text, 0
    scrubbed = text
    count = 0
    for name in REPORT_RULE_NAMES:
        scrubbed, replaced = _ALL_RULE_REGEX[name].subn(_PLACEHOLDERS[name], scrubbed)
        count += replaced
    return scrubbed, count
