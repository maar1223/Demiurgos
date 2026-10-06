# Retirement Validation Runbook — Post-Retirement Gate (ONB-5.1–5.4)

**Status:** WU-5a (overlap gate) + WU-5b (retirement) COMPLETE. The active
legacy wiring is removed from `install.sh`; `web-config-ui` is preserved as
historical reference only. This runbook validates the FINAL post-retirement
state — the barrier must pass WITH the retirement applied.

> **Scope note:** the ONB-5 retirement above is a *different* subsystem. The
> Hermes methodology channel documented next is in a **dormant/overlap** phase
> — native opt-in, legacy overlap intact — and is NOT retired.

---

## Hermes methodology channel — dormant/overlap phase (Etapa 3, WU-3.4)

**Status: DORMANT / OVERLAP — NOT retired.** The legacy methodology channel
(`skill_router` + `contract_projection`) stays present in-tree but dormant: it is
exercised only by the flag-OFF path. The native Hermes channel is **opt-in per
world** and **default OFF**; the legacy modules are not deleted and no import is
rewired in Etapa 3 (D3). The removal is a separate later change after a
≥1-release grace window.

### Dormant surface

- `src/tools/demiurgos-suite/wiki/skill_router.py` and
  `contract_projection.py`: present, importable, dormant.
- `convergence_injection.py:16` (`from contract_projection import
  _estimate_tokens`) stays intact — a naive deletion breaks this import.
- Presence is enforced by `wiki/tests/test_dormant_legacy_guard.py`, which FAILS
  if either module is removed or the cross-module import is rewired, blocking an
  early deletion.

### Rollback boundary

Flip the per-world channel flag OFF ⇒ `_active_channel_state()` returns
`"legacy"` and the legacy projection is restored **while the modules remain
present**. Promotion is reversible by repromotion; the `skills` toolset is a
revertible config value in the dedicated profile; there is **no module deletion,
no import rewire, and no test mass-inversion** in Etapa 3. Worst case for the
change is flag-OFF degradation, never lost capability.

### Migration evidence (Etapa 3)

| Evidence | Result |
|---|---|
| Pre-flight probe (WU-3.0) | Both gateway hooks live (`pre_tool_call` `skill_manage` veto + `pre_llm_call` cache clear); in-process cache clear works; `skill_manage` veto is fail-closed; behavior-neutral (flag-OFF prompt/toolset byte-identical). |
| **Q1 — toolset flip restart** | **NO gateway restart required.** `platform_toolsets.api_server` is resolved per agent turn and the gateway config is re-read when its `(mtime_ns, size)` changes, so adding `skills` lands on the next turn. Pinned by `test_native_channel_probe.py::test_q1_toolset_flip_takes_effect_without_gateway_restart` (`Q1_GATEWAY_RESTART_REQUIRED = False`). The live-gateway model-level step stays pending a dedicated test profile (`DEMIURGOS_PROBE_LIVE=1`). |
| Toolset reconcile (WU-3.1/3.2) | `ensure_skills_toolset` writes only the dedicated profile; zero-ON ⇒ config byte-identical; personal `~/.hermes` never touched. |
| Epoch activation — D4 (WU-3.1/3.2) | `SessionEpochRegistry.observe(world, revision)` allocates a fresh epoch when a promotion advances the revision; the run session id is epoch-suffixed only in the healthy `native` state — process restart is not the mechanism. |
| Promotion (WU-3.1) | `SkillPromoter` swaps a fresh generation tree in with a guarded two-rename; the revision is deterministic; orphan GC preserves sentinels; no-op on an unchanged revision. |
| Default-OFF byte-identical | `test_cross_cutting_invariant.py` + `test_native_channel_suppression.py` guards stay green with zero worlds opted in. |
| Dormant-legacy guard (WU-3.4) | `test_dormant_legacy_guard.py` green; fails on a simulated removed module / rewired import. |

---

## What the gate is

`src/tools/demiurgos-suite/wiki/retirement_gate.py` is a verifiable barrier.
In WU-5a it proved the new onboarding and Configuration Center coexisted with
the legacy wizard runtime (references INTACT). After WU-5b the gate validates
the retired state: no active legacy wiring remains, the legacy runtime is
preserved as historical reference (`backup.py` + `test_restore.py` intact), and
the new runtime is the only supported path. Every gate is a pure, read-only
check; running the gate never mutates anything.

## The retirement gates

| Gate | Proves |
|---|---|
| `legacy_wiring_removed` | ONB-5.1 RED barrier (post-retirement): `install.sh` no longer references `web-config-ui` nor binds port 8000 (Stage 6/`launch_web_ui` removed); the retirement docs record the wizard as historical. Removing wiring WITHOUT the docs record FAILS this gate. |
| `legacy_preserved_historical` | `src/tools/web-config-ui/` is preserved with `backup.py` and `tests/test_restore.py` intact; the docs mark it historical. |
| `new_runtime_present` | The onboarding/Center runtime modules (`onboarding.py`, `world_authority.py`, `local_state.py`, `migration.py`) are present as the supported path. |
| `online_offline_restart` | Local state survives commit → reload (restart resumes completed steps); the storage probe round-trips (offline local core works). |
| `canonical_tree` | New worlds are created with the lowercase canonical tree (`lore/ personajes/`), idempotently — in a sandbox, never the real `mundos/`. |
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

`all_passed: true` → the retirement state is consistent and the supported path
is fully modern. Any `passed: false` gate blocks closure: a failed
`legacy_wiring_removed` means active wiring survives or the docs do not record
the retirement; a failed `legacy_preserved_historical` means the historical
reference was deleted — restore `src/tools/web-config-ui/` (with `backup.py`
and `tests/test_restore.py`) and re-check.

## Final state checklist (post-retirement)

1. `install.sh` has no `web-config-ui` reference and no legacy port-8000
   binder; Stage 6/`launch_web_ui` and its call are gone.
2. `src/tools/web-config-ui/` still exists with `backup.py` and
   `tests/test_restore.py` intact — historical reference, not runtime.
3. Docs: the constitution (sections 2.1, 4, 8.1, decision G8) and
   `onboarding-and-configuration.md` §13 mark the wizard historical.
4. Gate suite green on the real root; CLI exit 0.

## Rollback boundary

WU-5b touched: `install.sh` (Stage 6 + call removed), `wiki/retirement_gate.py`,
`wiki/tests/test_retirement_gate.py`, this runbook,
`docs/architecture/onboarding-and-configuration.md` §13 and
`docs/architecture/demiurgos-platform.md` (historical references). Restoring
`install.sh` Stage 6 + the WU-5a gate expectations reverts the retirement;
foreign worktree changes are untouched.

## Historical record

WU-5a (2026-08-18, commit `b776650`) built the overlap gate with
`legacy_references_intact`/`coexistence` (references INTACT). WU-5b removed the
active wiring and inverted the barrier to the post-retirement semantics above,
keeping `backup.py` as a pattern reference.
