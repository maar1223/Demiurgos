# -*- coding: utf-8 -*-
"""Bug-report log assembly: the newest diagnostic window, never all-or-nothing.

Phase 1 (S5), task T1.2. Before this, the assembler read every ``*.log`` whole
and dropped the entire set once the redacted text passed 64 KiB, so the report
of a long-running install carried no logs at all — the opposite of what the
Owner asked for. The assembly is now a deterministic newest-first window with a
per-file and a total byte budget, reading the rotated ``<log>.N`` archives too.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

_HERE = Path(__file__).resolve().parent
_WIKI = _HERE.parent
if str(_WIKI) not in sys.path:
    sys.path.insert(0, str(_WIKI))

from bug_report import _LOGS_MAX_BYTES  # noqa: E402
from test_bug_report_router import _make_app  # noqa: E402


def _write_logs(install_root: Path, files: dict[str, bytes]) -> Path:
    logs = install_root / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        (logs / name).write_bytes(content)
    return logs


def _assemble(install_root: Path) -> dict:
    """The assembled bundle's ``logs`` field, through the public endpoint."""
    client = TestClient(_make_app(install_root=install_root))
    resp = client.get("/api/bugreport/assemble")
    assert resp.status_code == 200, resp.text
    return resp.json()["logs"]


def _line(index: int, prefix: str = "line") -> bytes:
    return f"{prefix}-{index:06d} marker\n".encode()


def test_a_log_over_the_cap_keeps_the_newest_window_instead_of_dropping_it(tmp_path):
    _write_logs(
        tmp_path,
        {"demiurgos-api.log": b"".join(_line(index) for index in range(20000))},
    )

    logs = _assemble(tmp_path)

    assert logs["included"] is True
    assert logs["reason"] == ""
    encoded = logs["content"].encode("utf-8")
    assert 0 < len(encoded) <= _LOGS_MAX_BYTES
    # The newest bytes survive; the oldest are the ones the window drops.
    assert "line-019999 marker" in logs["content"]
    assert "line-000000 marker" not in logs["content"]
    # The window starts on a record boundary, never mid-line.
    first_line = logs["content"].splitlines()[0]
    assert re.fullmatch(r"line-\d{6} marker", first_line), first_line


def test_archives_are_read_immediately_after_their_live_log(tmp_path):
    _write_logs(
        tmp_path,
        {
            "demiurgos-gateway.log": b"live-newest\n",
            "demiurgos-gateway.log.1": b"archive-first\n",
            "demiurgos-gateway.log.2": b"archive-second\n",
        },
    )

    content = _assemble(tmp_path)["content"]

    assert (
        content.index("live-newest")
        < content.index("archive-first")
        < content.index("archive-second")
    )


def test_the_total_budget_stops_adding_older_sources(tmp_path):
    # Eight families of ~20 KiB: the 64 KiB budget cannot hold them all, so the
    # later (older) ones fall outside the window deterministically.
    _write_logs(
        tmp_path,
        {
            f"familia-{index:02d}.log": _line(0, prefix=f"old-{index:02d}") * 1400
            for index in range(8)
        },
    )

    logs = _assemble(tmp_path)
    encoded = logs["content"].encode("utf-8")

    assert logs["included"] is True
    assert len(encoded) <= _LOGS_MAX_BYTES
    assert "old-00" in logs["content"]
    assert "old-07" not in logs["content"]


def test_a_small_log_is_still_carried_whole(tmp_path):
    _write_logs(tmp_path, {"launcher.log": b"server started\nready\n"})

    logs = _assemble(tmp_path)

    assert logs["included"] is True
    assert logs["content"] == "server started\nready\n"


def test_no_logs_is_reported_as_absent_not_as_an_empty_payload(tmp_path):
    (tmp_path / "logs").mkdir()

    logs = _assemble(tmp_path)

    assert logs["included"] is False
    assert logs["reason"] == "no logs available"
    assert logs["content"] == ""


def test_the_redaction_still_applies_inside_the_tail_window(tmp_path):
    secret = "sk-" + "a" * 40
    body = b"".join(_line(index) for index in range(5000))
    _write_logs(
        tmp_path,
        {"demiurgos-api.log": body + f"last line {secret}\n".encode()},
    )

    logs = _assemble(tmp_path)

    assert logs["included"] is True
    assert secret not in logs["content"]
    assert "[redacted:" in logs["content"]
    assert logs["redacted_lines"] >= 1


def test_two_assemblies_of_the_same_logs_are_identical(tmp_path):
    _write_logs(
        tmp_path,
        {
            "demiurgos-api.log": b"".join(_line(index) for index in range(6000)),
            "demiurgos-gateway.log.1": b"".join(_line(index) for index in range(6000)),
        },
    )

    first = _assemble(tmp_path)["content"]
    second = _assemble(tmp_path)["content"]

    assert first == second
    assert first != ""


@pytest.mark.parametrize("archive_name", ["launcher.log.1", "launcher.log.12"])
def test_an_archive_beyond_the_live_log_is_read_by_its_numeric_order(
    tmp_path, archive_name
):
    # A renamed/foreign archive is not one of the three launcher logs, but if it
    # sits in the directory the assembler still walks the family in numeric
    # order rather than crashing on the name.
    _write_logs(
        tmp_path,
        {"launcher.log": b"live\n", archive_name: b"archived\n"},
    )

    content = _assemble(tmp_path)["content"]

    assert content.index("live") < content.index("archived")


def test_redacted_lines_counts_only_the_shipped_placeholders(tmp_path):
    """Review R3-001: a placeholder the window trimmed away is not counted."""
    secret = "sk-" + "a" * 40
    body = f"oldest line {secret}\n".encode() + b"".join(
        _line(index) for index in range(20000)
    )
    _write_logs(tmp_path, {"demiurgos-api.log": body})

    logs = _assemble(tmp_path)

    assert logs["included"] is True
    assert "[redacted:" not in logs["content"]
    assert logs["redacted_lines"] == 0


def test_a_staging_leftover_is_not_read_as_an_archive(tmp_path):
    """Review R3-003: the ``.rotating`` name this change introduces is skipped."""
    _write_logs(
        tmp_path,
        {"launcher.log": b"live-line\n", "launcher.log.rotating": b"staged-line\n"},
    )

    content = _assemble(tmp_path)["content"]

    assert "live-line" in content
    assert "staged-line" not in content


def test_a_symlinked_archive_is_not_read(tmp_path):
    """Review R3-003: an archive that is a symlink stays out of the bundle."""
    logs = _write_logs(tmp_path, {"launcher.log": b"live-line\n"})
    outside = tmp_path / "outside.txt"
    outside.write_bytes(b"outside-line\n")
    (logs / "launcher.log.1").symlink_to(outside)

    content = _assemble(tmp_path)["content"]

    assert "live-line" in content
    assert "outside-line" not in content
