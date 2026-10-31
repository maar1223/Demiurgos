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
relations in its funnel.

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

## Tasks

- [x] T1 — `relation_service.py`: catalog projection, forward + reverse + folder
  index passes, additive idempotent merge, fail-open per ficha. (S1–S3, S5–S8)
  Route: inline. Evidence: `tests/test_relation_service.py` 7 passed.
- [x] T2 — Hook the service after a successful write in the editor save route,
  the guided/materialize create route, and restore; invalidate the cached graph
  index. (S4, S6) Route: inline. Evidence: `TestRelationsAfterSave` green; the
  hook is a single helper called from `save_file`, `save_file_via_save`,
  `create_file` and `restore_history`, after every digest check.
- [x] T3 — Tests: unit coverage of every pass, idempotency, additive merge,
  non-entity skip, malformed-file fail-open, plus one API-level save test.
  (S2, S5–S8) Route: inline. Evidence: full backend suite 4321 passed, 4
  launcher-rollback failures only while the local no-op browser stubs are
  absent (provisioned, then 12/12 green).
- [x] T4 — Ship `relation_service.py` in the runtime payload manifest
  (`scripts/derive_payload_manifest.py`), so the installer/PowerShell jobs keep
  passing. Route: inline. Evidence: manifest now lists
  `src/tools/demiurgos-suite/wiki/relation_service.py` (174 payload files).

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
