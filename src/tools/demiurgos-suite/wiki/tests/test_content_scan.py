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
* (f) CONTENT POLICY: the app's content-bearing log fields (``preview=``) are
  replaced by a placeholder while the surrounding metadata survives (S6).
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
    CONTENT_PREVIEW_PLACEHOLDER,
    REPORT_RULE_NAMES,
    REPORT_RULE_PATTERNS,
    SECRET_RULE_NAMES,
    SECRET_RULE_PATTERNS,
    count_content_previews,
    redact_content_previews,
    redact_secrets,
    scan_secret_lines,
    scrub_all,
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
# (c2) scrub_all covers BOTH rule sets (shared secrets + report PII).
# ---------------------------------------------------------------------------


def test_scrub_all_covers_shared_and_report_rules() -> None:
    text = (
        "key " + SHARED_FIXTURES["openai-key"]
        + " leaked at /var/log/demiurgos/api.log"
    )
    out, count = scrub_all(text)
    assert count == 2
    assert SHARED_FIXTURES["openai-key"] not in out
    assert "/var/log/demiurgos/api.log" not in out
    assert "<secret>" in out
    assert "<path>" in out


def test_scrub_all_keeps_scrub_pii_contract_intact() -> None:
    # scrub_all must not change scrub_pii's own contract: a text with NO shared
    # hits yields exactly what scrub_pii yields.
    text = "repro: run /var/log/demiurgos/api.log then retry"
    assert scrub_all(text) == scrub_pii(text)


def test_scrub_all_noop_on_plain_text() -> None:
    assert scrub_all("plain reproduction text") == ("plain reproduction text", 0)
    assert scrub_all("") == ("", 0)


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


# ---------------------------------------------------------------------------
# (f) Content policy — the app's own content-bearing log fields (S6).
#
# The ONLY writers that put author content into a log line are the assistant
# gateway records, and both declare the payload with ``preview=``:
#
#   Hermes GW START len=97 session=- preview='Aldric cruza el puente de Ceniza'
#   Hermes GW DONE 3.4s len=240 preview='...'
#
# ``len=`` is metadata and must survive; the payload is content.
# ---------------------------------------------------------------------------

_AUTHOR_TEXT = "Aldric cruza el puente de Ceniza"
_START_LINE = (
    "2026-01-01 12:00:00 INFO Hermes GW START len=%d session=- preview=%r"
    % (len(_AUTHOR_TEXT), _AUTHOR_TEXT)
)
_DONE_LINE = (
    "2026-01-01 12:00:03 INFO Hermes GW DONE 3.4s len=%d preview=%r"
    % (len(_AUTHOR_TEXT), _AUTHOR_TEXT)
)


def test_redact_content_previews_removes_the_payload() -> None:
    scrubbed, count = redact_content_previews(_START_LINE)
    assert count == 1
    assert _AUTHOR_TEXT not in scrubbed
    assert CONTENT_PREVIEW_PLACEHOLDER in scrubbed
    # The metadata that makes the record diagnosable survives.
    assert "Hermes GW START" in scrubbed
    assert "len=%d" % len(_AUTHOR_TEXT) in scrubbed


def test_redact_content_previews_covers_both_gateway_records() -> None:
    scrubbed, count = redact_content_previews(_START_LINE + "\n" + _DONE_LINE)
    assert count == 2
    assert _AUTHOR_TEXT not in scrubbed
    assert scrubbed.count(CONTENT_PREVIEW_PLACEHOLDER) == 2
    assert "Hermes GW DONE" in scrubbed


def test_redact_content_previews_leaves_metadata_lines_alone() -> None:
    text = "server started\nlistening on http://localhost:8001\ngateway ready"
    scrubbed, count = redact_content_previews(text)
    assert count == 0
    assert scrubbed == text


def test_redact_content_previews_ignores_a_plain_preview_variable() -> None:
    """``preview = obs.get(...)`` (source, space before ``=``) is not a field."""
    text = 'preview = obs.get("preview", obs.get("content", ""))'
    scrubbed, count = redact_content_previews(text)
    assert count == 0
    assert scrubbed == text


def test_redact_content_previews_is_idempotent() -> None:
    once, first = redact_content_previews(_START_LINE)
    twice, second = redact_content_previews(once)
    assert first == 1
    assert second == 0
    assert twice == once


def test_redact_content_previews_handles_empty_input() -> None:
    assert redact_content_previews("") == ("", 0)


def test_count_content_previews_sees_what_would_be_removed() -> None:
    text = _START_LINE + "\nserver started\n" + _DONE_LINE
    assert count_content_previews(text) == 2
    assert count_content_previews("server started") == 0
    assert count_content_previews("") == 0
    # Counting an already-scrubbed payload finds nothing left to include.
    assert count_content_previews(redact_content_previews(text)[0]) == 0
