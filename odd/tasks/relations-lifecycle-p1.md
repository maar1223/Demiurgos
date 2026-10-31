# Relations lifecycle — P1: deterministic service + save hook

Objective: relations grow organically inside Demiurgos. Every ficha save (manual
editor, Assistant-guided create, idea materialization) recomputes the
deterministic relations a ficha's own body justifies, and the fiches that name
it, without the Author running scripts outside the app.
Branch: `feat/relations-lifecycle-p1` (from `master`). Delivery: work-unit
commits; push/PR are the Owner's decision.
Tests: `.venv/bin/python -m pytest src/tools/demiurgos-suite/wiki/tests/ -q`
(from the repo root) · `PYTHONPATH=src/tools/demiurgos-suite:src/tools/demiurgos-suite/wiki`
when collecting a single module.

## Specs

S1 — Phase scope. Quoted from the Owner's design (Engram `roadmap/relations-lifecycle`):
"P1 servicio + hook al guardado (automático)". P1 ships the reconciliation
service and its automatic hook. Rejection memory (P2), semantic proposals (P3),
global reconciliation with backup (P4) and the per-save quality report (P5) are
out of scope.

S2 — Four passes. Quoted from the design: "(a) forward — menciones del cuerpo
contra el catálogo del mundo; (b) reverse — fichas existentes que nombran la
ficha nueva; (c) índice de carpeta derivado del path; (d) idempotencia y
procedencia."
Acceptance: a ficha body naming another ficha gains the relation; an existing
ficha naming a newly created one gains it; a ficha gains its folder index and
the folder index gains its members; running the service twice writes nothing the
second time.

S3 — Deterministic layer only. Quoted from the design: "Capa determinística =
automática y silenciosa (nombre completo, alias, stem, ordinal, índice)." The
model never decides which pairs exist in P1. Evidence kinds reuse
`import_relations.grounded_relations` unchanged.

S4 — Triggers. Quoted from the design: "Disparadores: importación de mundo (ya
existe), guardado de ficha del Asistente, materialización desde ideas, guardado
manual del editor". P1 hooks the three save flows; the importer already grounds
relations in its funnel. Restore is deliberately NOT a trigger: a restore must
hand back exactly the snapshot the Author chose, so it stays byte-exact and the
next normal save grows relations again.

S5 — Incremental and bounded. Quoted from the design: "Incremental: al guardar
solo se tocan la ficha cambiada, sus menciones y las fichas que la mencionan
(índice inverso nombre→paths); O(k), no O(mundo)."
Acceptance: no disk read scales with world size for the reverse pass; the
catalog and bodies come from the already-parsed graph index, and only the
changed fiches are re-read from disk.

S6 — Fail-open. A relation failure must never turn a durable save into an error.
Quoted from the codebase pattern: post-write metadata failures are logged and the
save still succeeds.

S7 — Non-entities are skipped. Quoted from the importer contract: a ficha with
`graph: false` opts out of the graph. P1 neither reads relations from it nor adds
relations to it.

S8 — Additive merge (decision). Existing `relaciones` entries are never removed
by P1; the service only adds grounded relations that are missing, deduped by the
same key `_set_frontmatter_relaciones` uses. Rationale: a save-time replace would
erase hand-edited and Hermes-authored relations (no provenance field exists in
the ficha format yet), and destructive cleanup is explicitly P4's job
("reconciliación global con backup"). Documented as an assumption; revisit when
P2 persists provenance.

S9 — Structural relations are uncapped (Owner decision, L5). Folder membership
(`folder-index` evidence) is exact truth bounded by the folder itself, so it
never consumes the textual `MAX_RELATIONS` budget: an index page with 20 members
keeps 20 relations and a member keeps its one belonging edge. Membership is
tracked as its own id set (`import_relations.structural_relations`), never by the
evidence string that won the match: an index page that lists its members in the
body matches them by full name too, and they must still stay outside the cap.
The cap applies only to inferred evidence (name/alias/stem/ordinal), where a hub
ficha stays at 12. `MAX_RELATIONS` was a size limit for the importer's LLM
response; that reason does not exist at save time, and silently truncating the
hierarchy loses part of the map.

S10 — Ambiguous identity keys are not evidence (Owner decision, L5). When two
entities share a normalized title, an alias segment or a filename stem, that key
is dropped instead of linking every owner: the body names one entity, not all of
them. `import_relations._ambiguous_identity_keys` owns the rule, and the quality
report uses the same guard.

## Tasks

- [x] T1 — `relation_service.py`: catalog projection, forward + reverse + folder
  index passes, additive idempotent merge, fail-open per ficha. (S1–S3, S5–S8)
  Route: inline. Evidence: `tests/test_relation_service.py` 7 passed.
- [x] T2 — Hook the service after a successful write in the editor save route
  and the guided/materialize create route (restore is excluded, S4); invalidate
  the cached graph index only when the plan actually wrote. (S4, S6) Route:
  inline. Evidence: `TestRelationsAfterSave` green; the hook is a single helper
  called from `save_file`, `save_file_via_save` and `create_file`, after every
  digest check.
- [x] T3 — Tests: unit coverage of every pass, idempotency, additive merge,
  non-entity skip, malformed-file fail-open, plus one API-level save test.
  (S2, S5–S8) Route: inline. Evidence: full backend suite 4321 passed, 4
  launcher-rollback failures only while the local no-op browser stubs are
  absent (provisioned, then 12/12 green).
- [x] T4 — Ship `relation_service.py` in the runtime payload manifest
  (`scripts/derive_payload_manifest.py`), so the installer/PowerShell jobs keep
  passing. Route: inline. Evidence: manifest now lists
  `src/tools/demiurgos-suite/wiki/relation_service.py` (174 payload files).
- [x] T5 — Close the three risks found while reviewing P1: structural relations
  uncapped (S9), ambiguous identity keys dropped (S10), restore left byte-exact
  (S4). Route: inline. Evidence: unit tests for a 20-member index, the 12-cap on
  a hub and the ambiguous-name skip; API tests for a 13-member index through the
  save route and a byte-exact restore; full backend suite 4343 passed.

## Log

L1 (verbatim Owner request): "Retomamos desde el checkpoint. Revisá el CI de #60 y #61; si están verdes, mergealos y después arrancamos con P1"

L2 Evidence: PR #60 failed CI with `ModuleNotFoundError: No module named
'import_relations'` because the runtime payload manifest was not regenerated;
fixed in `ce6ffe1` and merged. PR #61 merged; only the `macos-14` jobs were
cancelled by GitHub's scheduled runner-image brownout (not code).

L3 Decision: additive merge (S8) instead of recompute-and-replace, because P1
has no provenance field to tell auto from manual relations; destructive
reconciliation stays in P4.

L4 Verification (independent, commit `301c8f3` vs base `44dd7d2`): every S#
passed, no blockers. Evidence: service 7 passed; save/create routes 5 passed;
whole `test_api_server.py` 531 passed; payload/installer 188 passed; 13
durable probes added as `tests/test_relations_after_save_p1.py`. Advisories
recorded as follow-ups, not blockers:
1. `payload_manifest.json` `source_commit` drifts after every commit; the same
   drift exists at the baseline, so it is pre-existing provenance noise.
2. A guided create whose first reindex returns `dirty`/`pending` records the
   pre-hook digest, so a later `/guided/index/retry` would see a changed file.
   Narrow (build normally returns `indexed`); refresh the recorded digest after
   the hook when the retry path is touched.
3. The reverse pass scans the in-memory index (O(world) CPU, no disk), and the
   first save per process builds the index once; the quoted "O(k)" holds for
   disk reads, not for the in-memory body scan.
4. A legacy `[[Display Name]]` wikilink plus the new canonical id shows two
   entries for the same target; consistent with the stated dedupe key.

L5 (verbatim Owner request): "aplica los 3 y re verifica"

L6 Evidence for L5:
- The 12-relation cap truncated a folder index silently: a 20-member folder
  proposed only 12, and the additive applier then refused every later member
  because `room` counted the structural entries. Fixed by S9 (structural ids
  bypass the textual budget, in both `grounded_relations` and the applier).
- A folder index with an empty body was skipped by the reverse pass (`not
  ficha.body`); membership comes from the path, not the text. Fixed and pinned.
- Two fichas sharing a title or stem were both linked from one mention. Fixed by
  S10.
- `restore_history` no longer reconciles, so a restore is byte-exact.

L7 Re-verification (independent, `eb84f9e` vs `44dd7d2`) found one blocker, now
fixed: S9 was incomplete because `grounded_relations` classified membership by
the evidence string that won. An index page whose body lists its members matched
them by `full-name`, so 13 members were capped to 12 through the real save
route, and a member could lose its belonging edge when its body named the index
plus 12 others. Membership now comes from `structural_relations` (an independent
id set) in both the extraction split and the applier budget. Ten verifier probes
are committed as `tests/test_relations_lifecycle_p1_verifier.py`.
Also fixed: the cached graph index is dropped only when the plan actually wrote,
so an identical re-save never pays a rebuild. Residual advisory: after a real
change the next save rebuilds the index from disk (O(world)); a cheaper
incremental invalidation is a follow-up, not a correctness issue.
Final evidence: relation tests 35 passed; full backend suite 4353 passed,
8 skipped; importer default output unchanged on non-ambiguous inputs.

L8 Scoped recheck of L7 (blocker closed) found one regression introduced by the
cache optimization, now fixed: dropping the cached graph index only when the
plan wrote left the PRE-save body in memory, so a later create's reverse pass
missed an entity the edited body already named. The hook now drops the cached
index after every successful save (the rebuild stays lazy). The recheck's probes
are committed as `tests/test_relations_lifecycle_p1_recheck.py`; the failing
probe now passes. Final evidence: 40 relation tests passed; full backend suite
4358 passed, 8 skipped.
