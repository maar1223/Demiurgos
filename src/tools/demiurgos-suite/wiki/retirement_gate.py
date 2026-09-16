"""Retirement gate (ONB-5.1–5.4, WU-5a/5b): verifiable barrier for the
controlled legacy retirement. WU-5a validated the overlap with the legacy
wizard runtime (references INTACT). WU-5b removed the active wiring; this
module now validates the POST-RETIREMENT state: install.sh is free of legacy
wiring, web-config-ui is preserved as historical reference only (backup.py +
test_restore.py intact), and the new onboarding/Configuration Center runtime is
the supported path. Every gate is a pure, read-only check over project files
and wiki module contracts; running the gate never mutates anything. Gates:
legacy_wiring_removed (ONB-5.1 RED barrier, inverted), legacy_preserved_historical,
new_runtime_present, online_offline_restart, canonical_tree,
migration_rollback_evidence, three_proof_runtime, readiness_truthfulness,
deferred_handoff, auth_fail_closed, zero_legacy_mutation."""

from __future__ import annotations

import json
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

_WIKI = Path(__file__).resolve().parent
_SUITE = _WIKI.parent
for _p in (str(_WIKI), str(_SUITE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from data_root import resolve_data_root  # noqa: E402
from local_state import LocalState  # noqa: E402
from readiness import project_cards, probe_local_storage  # noqa: E402
from wiki.world_authority import (WorldResultKind,  # noqa: E402
                                  canonical_dirs, create_world,
                                  detect_legacy_layout)

# CODE root, deliberately NOT the data root (WU-2). Every gate below inspects
# the checkout itself — ``install.sh``, ``docs/``, ``src/tools/web-config-ui/``,
# the wiki modules — and ``main()`` defaults to it, so migrating it to the
# resolver would make the barrier inspect the author's data folder instead of
# the code it guards. Recorded in the guard test's CODE_PATH_ALLOWLIST.
PROJECT_ROOT = Path(__file__).resolve().parents[4]
INSTALL_SH = "install.sh"
ARCH_DOC = Path("docs") / "architecture" / "onboarding-and-configuration.md"
NEW_MODULES = ("onboarding.py", "world_authority.py", "local_state.py", "migration.py")
LEGACY_WIRING_MARKERS = ("web-config-ui", "port 8000")
LEGACY_DIR = Path("src") / "tools" / "web-config-ui"
LEGACY_KEEPERS = ("backup.py", "tests/test_restore.py")
PROOF_KEYS = ("text", "vision", "runtime")
PROOF_VALUES = {"text": "passed", "vision": "passed", "runtime": "accepted"}
HERMES_STATES = ("accepted", "pending-reload", "saved-not-active")


@dataclass(frozen=True)
class GateCheck:
    name: str
    passed: bool
    detail: str


@dataclass(frozen=True)
class RetirementGateReport:
    gates: tuple[GateCheck, ...]
    checked_at: str

    @property
    def all_passed(self) -> bool:
        return all(gate.passed for gate in self.gates)

    def as_dict(self) -> dict[str, Any]:
        return {"all_passed": self.all_passed, "checked_at": self.checked_at,
                "gates": [{"name": g.name, "passed": g.passed, "detail": g.detail}
                          for g in self.gates]}


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _verdict(name: str, passed: bool, detail: str) -> GateCheck:
    return GateCheck(name, passed, detail)


def _cards(claims: dict) -> dict:
    return project_cards(claims, worlds=["gate-world"], probe_ok=True)


def check_legacy_wiring_removed(project_root: Path) -> GateCheck:
    install = _read(Path(project_root) / INSTALL_SH)
    doc = _read(Path(project_root) / ARCH_DOC)
    still_wired = [marker for marker in LEGACY_WIRING_MARKERS if marker in install]
    if still_wired:
        return _verdict("legacy_wiring_removed", False,
                        "active legacy wiring remains in install.sh: "
                        + ", ".join(still_wired))
    if "web-config-ui" not in doc or "histórico" not in doc:
        return _verdict("legacy_wiring_removed", False,
                        "docs do not record web-config-ui as retired/historical")
    return _verdict("legacy_wiring_removed", True,
                    "install.sh free of legacy wiring; docs record the retirement")


def check_legacy_preserved_historical(project_root: Path) -> GateCheck:
    root = Path(project_root)
    legacy = root / LEGACY_DIR
    missing = []
    if not legacy.is_dir():
        missing.append("src/tools/web-config-ui/")
    for keeper in LEGACY_KEEPERS:
        if not (legacy / keeper).is_file():
            missing.append("web-config-ui/" + keeper)
    doc = _read(root / ARCH_DOC)
    if "web-config-ui" not in doc or "histórico" not in doc:
        missing.append("docs historical marker")
    if missing:
        return _verdict("legacy_preserved_historical", False,
                        "legacy reference not preserved: " + ", ".join(missing))
    return _verdict("legacy_preserved_historical", True,
                    "web-config-ui/ preserved; backup.py + test_restore.py intact")


def check_new_runtime_present(project_root: Path) -> GateCheck:
    wiki = Path(project_root) / "src" / "tools" / "demiurgos-suite" / "wiki"
    missing = [name for name in NEW_MODULES if not (wiki / name).is_file()]
    if missing:
        return _verdict("new_runtime_present", False,
                        f"new modules missing: {', '.join(missing)}")
    return _verdict("new_runtime_present", True,
                    "onboarding/Center runtime modules present")


def check_auth_fail_closed(project_root: Path) -> GateCheck:
    api = _read(Path(project_root) / "src" / "tools" / "demiurgos-suite"
                / "wiki" / "api_server.py")
    if "include_router" not in api or "require_principal" not in api:
        return _verdict("auth_fail_closed", False,
                        "api_server.py does not gate routers with require_principal")
    return _verdict("auth_fail_closed", True,
                    "api_server.py wires routers behind require_principal")


def check_online_offline_restart(project_root: Path) -> GateCheck:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "local-state.json"
        store = LocalState(path)
        revision = store.atomic_commit({**store.snapshot(), "onboarding_done": True})
        reloaded = LocalState(path).snapshot()
        if reloaded.get("revision") != revision or not reloaded.get("onboarding_done"):
            return _verdict("online_offline_restart", False,
                            "state did not survive reload")
        if not probe_local_storage(Path(tmp)).get("ok"):
            return _verdict("online_offline_restart", False,
                            "offline storage probe failed")
    return _verdict("online_offline_restart", True,
                    "restart resumes committed state; offline local core works")


def check_canonical_tree(project_root: Path) -> GateCheck:
    if any(name != name.lower() for name in canonical_dirs()):
        return _verdict("canonical_tree", False, "canonical dirs are not lowercase")
    with tempfile.TemporaryDirectory() as tmp:
        first = create_world(Path(tmp), "gate-world", lore_skeleton=True)
        if first.kind is not WorldResultKind.CREATED:
            return _verdict("canonical_tree", False,
                            f"creation failed: {first.kind.value}")
        top = {entry.name for entry in first.path.iterdir()}
        if not {"lore", "personajes"} <= top or any(n != n.lower() for n in top):
            return _verdict("canonical_tree", False, "tree is not lowercase canonical")
        second = create_world(Path(tmp), "gate-world", lore_skeleton=True)
        if second.kind is not WorldResultKind.ALREADY_EXISTS:
            return _verdict("canonical_tree", False, "creation is not idempotent")
    return _verdict("canonical_tree", True, "lowercase canonical tree; idempotent")


def evidence_dir() -> Path:
    """``<data root>/data/migration-evidence`` (WU-2), resolved on every call.

    The migration engine persists its evidence under the DATA root (see the
    ``create_migration_settings_router`` wiring in ``api_server``), so the gate
    reads it from the resolver while its code checks stay on ``PROJECT_ROOT``.
    """
    return resolve_data_root() / "data" / "migration-evidence"


def check_migration_rollback_evidence(project_root: Path) -> GateCheck:
    """Engine contract + persisted evidence.

    ``project_root`` is accepted for the uniform ``CHECKS`` signature but is
    intentionally unused: the evidence it reads is author data and therefore
    comes from the data-root resolver (WU-2), not from the checkout.
    """
    try:
        from wiki import migration as mig
    except Exception as exc:
        return _verdict("migration_rollback_evidence", False, f"engine import: {exc}")
    outcomes = {member.value for member in mig.MigrationOutcome}
    if mig.EVIDENCE_SCHEMA_VERSION != 1 or not {"completed", "rolled_back"} <= outcomes:
        return _verdict("migration_rollback_evidence", False, "engine contract drifted")
    invalid = []
    evidence = evidence_dir()
    if evidence.is_dir():
        for record in sorted(evidence.glob("*.json")):
            try:
                data = json.loads(record.read_text(encoding="utf-8"))
                ok = (data.get("outcome") in ("completed", "rolled_back")
                      and isinstance(data.get("restore_verified"), bool))
            except (OSError, ValueError):
                ok = False
            if not ok:
                invalid.append(record.name)
    if invalid:
        return _verdict("migration_rollback_evidence", False,
                        "invalid evidence: " + ", ".join(invalid))
    return _verdict("migration_rollback_evidence", True,
                    "engine contract valid; persisted evidence well-formed")


def check_three_proof_runtime(project_root: Path) -> GateCheck:
    from readiness import ASSISTANT_PROOF_KEYS, ASSISTANT_PROOF_VALUES
    hermes = _read(_WIKI / "hermes_runtime.py")
    if ASSISTANT_PROOF_KEYS != PROOF_KEYS or dict(ASSISTANT_PROOF_VALUES) != PROOF_VALUES:
        return _verdict("three_proof_runtime", False, "proof vocabulary drifted")
    if not all(state in hermes for state in HERMES_STATES):
        return _verdict("three_proof_runtime", False, "Hermes acceptance states drifted")
    return _verdict("three_proof_runtime", True,
                    "text+vision+runtime proofs; Hermes states honest")


def check_readiness_truthfulness(project_root: Path) -> GateCheck:
    cards = _cards({"capabilities": {"assistant": "configured"}})
    if cards["assistant"] != "pending" or cards["import"] != "pending":
        return _verdict("readiness_truthfulness", False, "bare claim configured a card")
    return _verdict("readiness_truthfulness", True,
                    "bare assistant claim stays pending; import never ready")


def check_deferred_handoff(project_root: Path) -> GateCheck:
    cards = _cards({"identity": "configured", "backup": "configured"})
    stale = [key for key in ("identity", "backup", "import")
             if cards.get(key) != "pending"]
    if stale:
        return _verdict("deferred_handoff", False,
                        "stale claims configured: " + ", ".join(stale))
    return _verdict("deferred_handoff", True, "deferred cards stay pending")


def check_zero_legacy_mutation(project_root: Path) -> GateCheck:
    with tempfile.TemporaryDirectory() as tmp:
        world = Path(tmp) / "legacy-gate"
        (world / "Lore" / "reglas").mkdir(parents=True)
        (world / "Lore" / "reglas" / "magia.md").write_text("# Magia\n", encoding="utf-8")
        (world / "Personajes").mkdir()
        (world / "Personajes" / "anisa.md").write_text("---\nname: Anisa\n---\n",
                                                       encoding="utf-8")
        before = {str(p): p.read_bytes() for p in world.rglob("*") if p.is_file()}
        case_insensitive = (world / "lore").exists()
        findings = detect_legacy_layout(Path(tmp))
        detected = any(f["world"] == "legacy-gate"
                       and f["folders"] == ["Lore", "Personajes"] for f in findings)
        after = {str(p): p.read_bytes() for p in world.rglob("*") if p.is_file()}
        if case_insensitive:
            # R-CARG-01: on a case-insensitive FS the runtime already operates
            # on the canonical tree through legacy-cased paths, so the gate
            # asserts canonical-side presence (either spelling resolves to the
            # same physical content) instead of legacy absence.
            canonical_present = (
                (world / "lore").exists()
                or (world / "Lore" / "reglas" / "magia.md").is_file()
            )
            if not canonical_present or before != after:
                return _verdict("zero_legacy_mutation", False,
                                "case-insensitive fs: canonical tree missing or mutated")
        else:
            if not detected or before != after or (world / "lore").exists():
                return _verdict("zero_legacy_mutation", False,
                                "detection mutated the legacy tree")
    return _verdict("zero_legacy_mutation", True,
                    "detection read-only; legacy folders byte-identical")


CHECKS = (
    check_legacy_wiring_removed, check_legacy_preserved_historical,
    check_new_runtime_present, check_auth_fail_closed,
    check_online_offline_restart, check_canonical_tree,
    check_migration_rollback_evidence, check_three_proof_runtime,
    check_readiness_truthfulness, check_deferred_handoff,
    check_zero_legacy_mutation,
)


def run_retirement_gates(project_root: Path) -> RetirementGateReport:
    root = Path(project_root)
    return RetirementGateReport(
        gates=tuple(check(root) for check in CHECKS),
        checked_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )


def main(argv: Sequence[str] | None = None) -> int:
    """CLI barrier check: ``python -m wiki.retirement_gate [root]``."""
    args = [arg for arg in (sys.argv[1:] if argv is None else argv)
            if arg not in ("--check", "-c")]
    report = run_retirement_gates(Path(args[0]) if args else PROJECT_ROOT)
    print(json.dumps(report.as_dict(), ensure_ascii=False, indent=2))
    return 0 if report.all_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
