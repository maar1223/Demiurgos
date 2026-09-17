# -*- coding: utf-8 -*-
"""ONB-5.1–5.4 — Retirement gate RED tests (WU-5a overlap + WU-5b retirement).

The retirement gate is a verifiable barrier. In WU-5a it proved the new
onboarding and Configuration Center coexisted with the legacy wizard runtime
(references INTACT). WU-5b removed the active legacy wiring and finalized the
docs; this file now validates the POST-RETIREMENT state: install.sh is free of
legacy wiring, web-config-ui is preserved as historical reference only
(backup.py + test_restore.py intact), and the new runtime is the supported
path. RED first — these tests fail against the WU-5a gate module (missing
gates, inverted barrier semantics) until `wiki/retirement_gate.py` is updated.
The barrier semantic (ONB-5.1) is preserved: retirement without the full
retirement contract (docs record + preservation) FAILS; negatives run on
sandboxed roots, never on the real files.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from unittest import mock

_SRC_DIR = Path(__file__).resolve().parent.parent.parent  # demiurgos-suite/
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from wiki import retirement_gate as gate  # noqa: E402

PROJECT_ROOT = gate.PROJECT_ROOT

EXPECTED_GATES = {"legacy_wiring_removed", "legacy_preserved_historical",
                  "new_runtime_present", "auth_fail_closed",
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


def test_legacy_wiring_removed_passes_on_real_root():
    assert gate.check_legacy_wiring_removed(PROJECT_ROOT).passed


def test_partial_retirement_without_docs_record_fails():
    """ONB-5.1 barrier, post-retirement: removing wiring WITHOUT the docs
    retirement record FAILS the gate (retirement must be complete)."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "install.sh").write_text(
            "#!/usr/bin/env bash\n# clean install\n", encoding="utf-8"
        )
        docs = root / "docs" / "architecture"
        docs.mkdir(parents=True)
        (docs / "onboarding-and-configuration.md").write_text(
            "# Onboarding\n", encoding="utf-8"
        )
        check = gate.check_legacy_wiring_removed(root)
        assert not check.passed
        assert "docs" in check.detail


def test_legacy_wiring_removed_fails_when_wiring_remains():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "install.sh").write_text(
            "launch web-config-ui\nuvicorn main:app --port 8000\n",
            encoding="utf-8",
        )
        assert not gate.check_legacy_wiring_removed(root).passed


def test_legacy_preserved_historical_passes_on_real_root():
    assert gate.check_legacy_preserved_historical(PROJECT_ROOT).passed


def test_legacy_preserved_historical_fails_when_dir_deleted():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        docs = root / "docs" / "architecture"
        docs.mkdir(parents=True)
        (docs / "onboarding-and-configuration.md").write_text(
            "web-config-ui histórico\n", encoding="utf-8"
        )
        assert not gate.check_legacy_preserved_historical(root).passed


def test_new_runtime_present_passes_on_real_root():
    assert gate.check_new_runtime_present(PROJECT_ROOT).passed


def test_new_runtime_present_fails_when_module_missing():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        wiki = root / "src" / "tools" / "demiurgos-suite" / "wiki"
        wiki.mkdir(parents=True)
        assert not gate.check_new_runtime_present(root).passed


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


def test_migration_rollback_evidence_fails_on_invalid_record(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        # The evidence is author data: it lives under the DATA root, so the
        # check reads it from the resolver (WU-2), not from ``project_root``.
        monkeypatch.setenv("DEMIURGOS_DATA_ROOT", tmp)
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


def test_deferred_handoff_bare_backup_claim_stays_pending():
    """SC-CC-3.1 (forward) — a bare ``backup: configured`` claim never configures."""
    cards = gate._cards({"identity": "configured", "backup": "configured"})
    assert cards["backup"] == "pending"
    assert cards["identity"] == "pending"
    # The gate reports the bare claim as honest while the claim stays pending.
    assert gate.check_deferred_handoff(PROJECT_ROOT).passed


def test_deferred_handoff_evidenced_backup_configures():
    """SC-CC-3.1 (reverse) — a genuinely evidenced backup card configures it."""
    cards = gate._cards(
        {"identity": "configured", "backup": "configured"},
        backup_state="configured",
    )
    assert cards["backup"] == "configured"
    # The gate must not fail the real evidence, only the bare claim.
    assert gate.check_deferred_handoff(PROJECT_ROOT).passed


def test_deferred_handoff_fails_when_evidenced_backup_cannot_configure(monkeypatch):
    """The gate's failure branch: if the dedicated contract cannot configure,
    the gate must fail instead of silently ignoring the evidence."""
    real = gate.project_cards

    def broken(state, worlds, probe_ok, telegram_state=None, backup_state=None):
        cards = real(state, worlds, probe_ok,
                     telegram_state=telegram_state, backup_state=backup_state)
        cards["backup"] = "pending"
        return cards

    monkeypatch.setattr(gate, "project_cards", broken)
    check = gate.check_deferred_handoff(PROJECT_ROOT)
    assert not check.passed
    assert "evidenced backup" in check.detail


def test_zero_legacy_mutation_passes():
    assert gate.check_zero_legacy_mutation(PROJECT_ROOT).passed


def test_zero_legacy_mutation_passes_on_case_insensitive_fs():
    """R-CARG-01/R-CARG-04 — the zero-legacy-mutation gate passes whether the
    FS is case-insensitive (macOS/Windows, where `lore` resolves to `Lore`) or
    case-sensitive (Linux): detection is read-only in both branches, so the
    gate never reports a mutation."""
    with tempfile.TemporaryDirectory() as tmp:
        check = gate.check_zero_legacy_mutation(Path(tmp))
    assert check.passed
    assert "read-only" in check.detail or "byte-identical" in check.detail


def test_cli_reports_all_passed_with_exit_zero():
    assert gate.main(["--check", str(PROJECT_ROOT)]) == 0
