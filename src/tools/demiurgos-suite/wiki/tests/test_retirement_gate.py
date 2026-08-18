# -*- coding: utf-8 -*-
"""ONB-5.1/5.2 — Retirement overlap gate RED tests (WU-5a).

The retirement gate is a verifiable barrier: it proves the new onboarding and
Configuration Center coexist with the legacy wizard runtime BEFORE any legacy
retirement. RED first — these tests fail until `wiki/retirement_gate.py`
exists and every gate passes on the real project root. The barrier semantic
(ONB-5.1) is covered too: removing a legacy reference makes the gate FAIL
(premature retirement is blocked); negatives run on sandboxed roots, never on
the real files. No retirement happens in this unit — that is WU-5b.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

_SRC_DIR = Path(__file__).resolve().parent.parent.parent  # demiurgos-suite/
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from wiki import retirement_gate as gate  # noqa: E402

PROJECT_ROOT = gate.PROJECT_ROOT

EXPECTED_GATES = {"legacy_references_intact", "coexistence", "auth_fail_closed",
                  "online_offline_restart", "canonical_tree",
                  "migration_rollback_evidence", "three_proof_runtime",
                  "readiness_truthfulness", "deferred_handoff",
                  "zero_legacy_mutation"}


def test_report_shape_and_gate_names():
    report = gate.run_retirement_gates(PROJECT_ROOT)
    assert {item.name for item in report.gates} == EXPECTED_GATES
    assert isinstance(report, gate.RetirementGateReport)
    assert isinstance(report.gates[0], gate.GateCheck)
    payload = report.as_dict()
    assert payload["all_passed"] is report.all_passed
    assert payload["checked_at"]
    assert len(payload["gates"]) == len(EXPECTED_GATES)


def test_all_gates_pass_on_real_root():
    report = gate.run_retirement_gates(PROJECT_ROOT)
    assert report.all_passed
    assert [item.name for item in report.gates if not item.passed] == []


def test_legacy_references_intact_passes_on_real_root():
    assert gate.check_legacy_references_intact(PROJECT_ROOT).passed


def test_premature_reference_removal_fails_the_barrier():
    """ONB-5.1 RED barrier: removing a legacy ref before gates pass FAILS."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "install.sh").write_text(
            "#!/usr/bin/env bash\n# port moved to the wiki API\n", encoding="utf-8"
        )
        docs = root / "docs" / "architecture"
        docs.mkdir(parents=True)
        (docs / "onboarding-and-configuration.md").write_text(
            "# Onboarding\n", encoding="utf-8"
        )
        check = gate.check_legacy_references_intact(root)
        assert not check.passed
        assert "port 8000" in check.detail and "web-config-ui" in check.detail


def test_coexistence_passes_on_real_root():
    assert gate.check_coexistence(PROJECT_ROOT).passed


def test_coexistence_fails_when_new_module_missing():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "install.sh").write_text("web-config-ui\n", encoding="utf-8")
        assert not gate.check_coexistence(root).passed


def test_auth_fail_closed_passes_on_real_root():
    assert gate.check_auth_fail_closed(PROJECT_ROOT).passed


def test_auth_fail_closed_fails_without_principal_gate():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        wiki = root / "src" / "tools" / "demiurgos-suite" / "wiki"
        wiki.mkdir(parents=True)
        (wiki / "api_server.py").write_text(
            "app.include_router(router)\n", encoding="utf-8"
        )
        assert not gate.check_auth_fail_closed(root).passed


def test_online_offline_restart_passes():
    assert gate.check_online_offline_restart(PROJECT_ROOT).passed


def test_canonical_tree_passes():
    assert gate.check_canonical_tree(PROJECT_ROOT).passed


def test_migration_rollback_evidence_passes_on_real_root():
    assert gate.check_migration_rollback_evidence(PROJECT_ROOT).passed


def test_migration_rollback_evidence_fails_on_invalid_record():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        evidence = root / "data" / "migration-evidence"
        evidence.mkdir(parents=True)
        (evidence / "bad.json").write_text(
            json.dumps({"outcome": "migrated", "restore_verified": "yes"}),
            encoding="utf-8",
        )
        assert not gate.check_migration_rollback_evidence(root).passed


def test_three_proof_runtime_passes_on_real_root():
    assert gate.check_three_proof_runtime(PROJECT_ROOT).passed


def test_readiness_truthfulness_passes_with_bare_claim():
    assert gate.check_readiness_truthfulness(PROJECT_ROOT).passed


def test_deferred_handoff_passes_with_stale_claims():
    assert gate.check_deferred_handoff(PROJECT_ROOT).passed


def test_zero_legacy_mutation_passes():
    assert gate.check_zero_legacy_mutation(PROJECT_ROOT).passed


def test_cli_reports_all_passed_with_exit_zero():
    assert gate.main(["--check", str(PROJECT_ROOT)]) == 0
