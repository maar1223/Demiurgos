# -*- coding: utf-8 -*-
"""Content scan: shared secret rules, report-specific PII rules, parity (S1a).

Covers:
* (a) each of the four shared ``SECRET_RULE_*`` rules is detected on a fixture;
* (b) ``redact_secrets`` removes the raw secret value;
* (c) ``scrub_pii`` replaces paths/usernames/hostnames/private IPs/emails;
* (d) PARITY: the Python rule names + patterns are byte-identical to the
  ``RULES_SRC`` heredoc in ``scripts/secret_scan.sh`` (the single source of
  truth — the shell script is never edited by this slice);
* (e) COVERAGE: every ``REPORT_RULE_NAMES`` entry has a pattern and a positive
  fixture that the rule (and ``scan_secret_lines``) actually hits.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Dict, List, Tuple

import pytest

_HERE = Path(__file__).resolve().parent
_WIKI = _HERE.parent
for _p in (str(_WIKI),):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from content_scan import (  # noqa: E402
    REPORT_RULE_NAMES,
    REPORT_RULE_PATTERNS,
    SECRET_RULE_NAMES,
    SECRET_RULE_PATTERNS,
    redact_secrets,
    scan_secret_lines,
    scrub_pii,
)

# Fake fixtures only — never real credentials or real author data. The user
# fixture is assembled by concatenation so this file's source never contains a
# literal home path that the repo secret scan would (correctly) flag.
HOME_PREFIX = "/home" + "/"

SHARED_FIXTURES: Dict[str, str] = {
    "bot-token": "123456789:" + "A" * 35,
    "openai-key": "sk-" + "a" * 40,
    "google-api-key": "AIza" + "b" * 35,
    "author-path": "C:" + "\\" + "Users" + "\\" + "someone",
}

REPORT_FIXTURES: Dict[str, str] = {
    "local-path": "/var/log/demiurgos/api.log",
    "username": HOME_PREFIX + "john/secret",
    "hostname": "host=devbox.local",
    "private-ip": "192.168.1.42",
    "email": "dev@example.com",
    "extra-secret": "AKIAIOSFODNN7EXAMPLE",
}


# ---------------------------------------------------------------------------
# (a) Shared rules are detected.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", SECRET_RULE_NAMES)
def test_shared_rule_is_detected(name: str) -> None:
    assert name in SECRET_RULE_PATTERNS, f"{name} must have a pattern"
    hits = scan_secret_lines(SHARED_FIXTURES[name])
    assert (1, name) in hits, f"{name} not detected in its fixture: {hits}"


def test_scan_reports_one_based_line_numbers() -> None:
    text = "clean line\n" + SHARED_FIXTURES["openai-key"] + "\nclean again"
    hits = scan_secret_lines(text)
    assert hits == [(2, "openai-key")]


def test_scan_of_empty_text_is_empty() -> None:
    assert scan_secret_lines("") == []


# ---------------------------------------------------------------------------
# (b) redact_secrets removes the raw secret value.
# ---------------------------------------------------------------------------


def test_redact_secrets_removes_secret_value() -> None:
    token = SHARED_FIXTURES["bot-token"]
    text = "line one ok\nINFO token=" + token + " leaked\nline three ok"
    out, count = redact_secrets(text)
    assert count == 1
    assert token not in out, "raw secret value must never survive redaction"
    assert "[redacted: bot-token]" in out
    # Non-matching lines are preserved verbatim.
    assert "line one ok" in out
    assert "line three ok" in out


def test_redact_secrets_redacts_report_rule_hits() -> None:
    out, count = redact_secrets("connecting to 192.168.1.42 now")
    assert count == 1
    assert "192.168.1.42" not in out
    assert "[redacted: private-ip]" in out


def test_redact_secrets_noop_on_plain_text() -> None:
    assert redact_secrets("nothing to see here") == ("nothing to see here", 0)
    assert redact_secrets("") == ("", 0)


# ---------------------------------------------------------------------------
# (c) scrub_pii replaces the PII classes with placeholders.
# ---------------------------------------------------------------------------


def test_scrub_pii_replaces_all_report_classes() -> None:
    text = "\n".join(REPORT_FIXTURES[name] for name in REPORT_RULE_NAMES)
    out, count = scrub_pii(text)
    assert count == len(REPORT_RULE_NAMES)
    for placeholder in ("<path>", "<username>", "<hostname>",
                        "<private-ip>", "<email>", "<secret>"):
        assert placeholder in out, f"{placeholder} missing from {out!r}"
    for name, raw in REPORT_FIXTURES.items():
        assert raw not in out, f"raw {name} finding survived scrub: {raw}"


def test_scrub_pii_preserves_reproduction_structure() -> None:
    text = "repro: run /var/log/demiurgos/api.log then retry"
    out, count = scrub_pii(text)
    assert count == 1
    assert out == "repro: run <path> then retry"


def test_scrub_pii_noop_on_plain_text() -> None:
    assert scrub_pii("plain reproduction text") == ("plain reproduction text", 0)
    assert scrub_pii("") == ("", 0)


# ---------------------------------------------------------------------------
# (d) PARITY with scripts/secret_scan.sh (read-only).
# ---------------------------------------------------------------------------


def _repo_root() -> Path:
    for parent in (_HERE, *_HERE.parents):
        if (parent / "scripts" / "secret_scan.sh").is_file():
            return parent
    raise AssertionError("scripts/secret_scan.sh not found above the test file")


def _parse_rules_src(script_text: str) -> List[Tuple[str, str]]:
    match = re.search(
        r"RULES_SRC=\$\(cat <<'EOF'\n(.*?)\nEOF\n", script_text, re.DOTALL)
    assert match is not None, "RULES_SRC heredoc not found in secret_scan.sh"
    rules: List[Tuple[str, str]] = []
    for line in match.group(1).split("\n"):
        if line == "":
            continue
        name, pattern = line.split("\t", 1)
        rules.append((name, pattern))
    return rules


def test_secret_rules_are_byte_identical_to_secret_scan_sh() -> None:
    script = _repo_root() / "scripts" / "secret_scan.sh"
    rules = _parse_rules_src(script.read_text(encoding="utf-8"))
    assert [name for name, _ in rules] == list(SECRET_RULE_NAMES)
    shell_patterns = {name: pattern for name, pattern in rules}
    assert shell_patterns == SECRET_RULE_PATTERNS
    for name in SECRET_RULE_NAMES:
        assert SECRET_RULE_PATTERNS[name] == shell_patterns[name]


# ---------------------------------------------------------------------------
# (e) COVERAGE of the report-specific rule set.
# ---------------------------------------------------------------------------


def test_report_rules_are_distinct_from_shared_rules() -> None:
    assert set(REPORT_RULE_NAMES).isdisjoint(SECRET_RULE_NAMES)


@pytest.mark.parametrize("name", REPORT_RULE_NAMES)
def test_every_report_rule_has_pattern_and_positive_fixture(name: str) -> None:
    assert name in REPORT_RULE_PATTERNS, f"{name} must have a pattern"
    assert REPORT_RULE_PATTERNS[name].strip(), f"{name} pattern is empty"
    assert name in REPORT_FIXTURES, f"{name} has no positive fixture"
    assert re.search(REPORT_RULE_PATTERNS[name], REPORT_FIXTURES[name])
    assert (1, name) in scan_secret_lines(REPORT_FIXTURES[name])
