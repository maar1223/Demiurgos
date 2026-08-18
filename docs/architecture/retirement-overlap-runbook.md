# Retirement Overlap Runbook — Controlled Overlap Validation (ONB-5.1/5.2)

**Status:** WU-5a — gate + validation only. No legacy reference is removed, no
port moves, no badge/endpoint changes. Retirement implementation is WU-5b and
MUST NOT start until every gate here passes.

## What the gate is

`src/tools/demiurgos-suite/wiki/retirement_gate.py` is a verifiable barrier: it
proves the new onboarding and Configuration Center coexist with the legacy
wizard runtime. Every gate is a pure, read-only check over project files and
wiki module contracts. Running the gate never mutates legacy folders and never
changes wiring — legacy stays fully reversible until the barrier verdict passes.

## The overlap gates

| Gate | Proves |
|---|---|
| `legacy_references_intact` | ONB-5.1 RED barrier — `install.sh` keeps the legacy wizard refs (line 257 requirements.txt, line 265 ui_dir, line 267 port 8000) and docs §13.1 records WU-5 retention. Removing any reference FAILS this gate before retirement. |
| `coexistence` | New onboarding/Center modules (`onboarding.py`, `world_authority.py`, `local_state.py`, `migration.py`) live alongside the legacy wiring. |
| `online_offline_restart` | Local state survives commit → reload (restart resumes completed steps); the storage probe round-trips (offline local core works). |
| `canonical_tree` | New worlds are created with the lowercase canonical tree (`lore/ personajes/ sagas/`), idempotently — in a sandbox, never the real `mundos/`. |
| `migration_rollback_evidence` | The migration engine contract (evidence schema, `completed`/`rolled_back` outcomes, `restore_verified`) plus any persisted evidence records are well-formed. |
| `three_proof_runtime` | The assistant still requires text + vision + runtime proofs, and the Hermes acceptance vocabulary (`accepted`/`pending-reload`/`saved-not-active`) stays honest. |
| `readiness_truthfulness` | A bare registry claim never configures the assistant card; the import card never claims ready (no fake completion). |
| `deferred_handoff` | identity/backup/import never become `configured` from local evidence — deferred handoffs stay pending. |
| `auth_fail_closed` | `api_server.py` wires every router behind `require_principal`; unauthenticated access stays 401. |
| `zero_legacy_mutation` | Legacy detection is read-only: a sandboxed legacy world is detected and left byte-identical (no lowercase rename, no content change). |

## How to run

```bash
# Gate suite (RED-first tests, includes the negative barrier cases):
.venv/bin/python -m pytest src/tools/demiurgos-suite/wiki/tests/test_retirement_gate.py -q

# Barrier verdict as one command (JSON report; exit 0 only when ALL gates pass):
cd src/tools/demiurgos-suite && ../../..//.venv/bin/python -m wiki.retirement_gate
```

## Reading the verdict

`all_passed: true` → overlap is validated and retirement may be planned
(WU-5b). Any `passed: false` gate blocks retirement: fix the underlying
violation (or stop removing references) and re-run. A failed
`legacy_references_intact` means someone removed a legacy reference before the
gates passed — restore it and re-check.

## Controlled overlap scenario (sandbox, no real legacy touched)

1. Create a legacy world in a temp dir: `mundos/legacy-x/{Lore,Personajes,sagas}`.
2. Run the new onboarding/world authority against the same root (creation is
   canonical lowercase; detection reports the legacy world read-only).
3. Run the gate suite: coexistence, canonical tree, zero legacy mutation and
   migration-rollback checks all pass; the legacy folders stay byte-identical.

## Rollback boundary

Three new files, no wiring touched: `wiki/retirement_gate.py`,
`wiki/tests/test_retirement_gate.py`, this runbook. Deleting them restores the
pre-WU-5a state exactly. `install.sh`, `api_server.py`, `docs/architecture/
onboarding-and-configuration.md` §13.1 and port 8000 ownership are untouched.

## WU-5b handoff (after all gates pass)

WU-5b may then remove the active legacy wiring (`install.sh` 257/265/267),
mark `web-config-ui` historical, and finalize docs — keeping `backup.py` as a
pattern reference. Until the barrier passes, overlap remains reversible and
legacy stays on the supported path.
