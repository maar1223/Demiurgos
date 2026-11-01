# Relations — batch-safe proposal primitive

Objective: one shared, batch-independent relation proposal primitive for the sweep and the world importer: a model claim survives only when it quotes the source body; batch composition affects recall, never truth.
Branch: `feat/relations-batch-grounding` (base `master` 0b173e6).
Delivery: work-unit commits; PR at the end. Runner: `python3 -m pytest src/tools/demiurgos-suite/wiki/tests/ -q` + `cd frontend && npm test -- --run`.

## Specs

- **S1 — One truth criterion: the body.** A model claim becomes a candidate relation only
  when it supplies a quote that appears in the SOURCE body after the shared normalization
  (case, accents, whitespace). A claim that cannot be quoted from the body is dropped.
  Batch membership is never evidence.
- **S2 — Batch independence.** Sources are sent in batches; the target universe is the
  whole world catalog, not the batch. Each source is asked for its own independent claim.
  The resulting graph must be identical whether the same fichas are processed in one call
  or in N calls.
- **S3 — Coverage.** Every ficha is proposed as a source once per body digest. The sweep
  state distinguishes pending / swept / muted and reports how many remain.
- **S4 — Symmetry normalized.** The proposal queue and the evidence memory key the
  UNORDERED pair, so `A→B` and `B→A` collapse into one entry with a deterministic side.
- **S5 — Verified evidence persists.** `.relations/evidenced.json` stores
  `(pair, source_side, quote)`. The sync keeps a declared relation while the quote is
  still present in the source body, and drops it when the body no longer corroborates it.
- **S6 — The importer uses the same primitive.** The funnel's model `relationships` go
  through the same verification and feed the same evidence memory. Unverified model
  relations never reach `relaciones`; the deterministic extraction stays the base.
- **S7 — Sync composes the layers.** Declared = deterministic matcher ∪ currently
  verified evidence ∪ curated. Removals distinguish `redundant-folder` (the folder index
  already connects the pair) from `ungrounded` (no text backs it).
- **S8 — Batch UI.** The sweep processes a bounded batch (default 5) with visible
  progress and a summary, and states its cost as a number; no paragraph of instructions.
- **S9 — No regressions.** Backend and frontend suites stay green. No world lore in
  tests, fixtures, comments or commits.

## Tasks

| ID | Spec | Route | Status | Evidence |
|----|------|-------|--------|----------|
| T1 | S1, S2, S4 | inline | done | `relation_proposing.py` + 14 tests |
| T2 | S3, S5 | inline | done | `relation_evidence.py` + 10 tests |
| T3 | S2, S8 | delegated | done | `223e455`, `4ac3d95` — sweep batch + panel |
| T4 | S6 | delegated | done | `eb7c60f` — funnel verification + evidence at materialization |
| T5 | S7 | delegated | done | `958909d` — evidence union + removal reasons |
| T6 | S9 | inline | done | backend 4725 passed / 26 skipped; frontend 1667 passed; typecheck + build green |

## Log

- **L1** (verbatim, 2026-10-31): "ok, eso del barrido en lotes, y si hay relaciones entre
  lotes distintos? que pasa alli? te lo pregunto porque el importador que tenemos montado
  tiene exactamente ese problema y es la razon por la que está fallando el sistema de
  relaciones ahora mismo. La solucion que encontremos aqui tiene que resolver el problema
  tanto acá como en el importador. Si no vamos a estar tapando una fuga de agua con cinta
  aislante y no reparando el problema de manera definitiva"
- **L2** (verbatim, 2026-10-31): "haz el arreglo defitivo, tanto aqui como en el importador"
- **L3** (evidence, mapping): the importer's model `relationships` are NOT discarded —
  they persist in `enrichment_json` (`import_enrichment.py:1488-1526`, `import_service.py:600,631`),
  they just never influence `relaciones` (`_apply_grounded_relations` overwrites it,
  `:1597-1608`). The sweep's validator only checks target existence in the catalog
  (`validate_suggestions`, `:279-356`); no body check exists anywhere.
- **L4** (evidence, mapping): `relaciones` is written as YAML `- <canonical_id>` by
  `_set_frontmatter_relaciones` (`api_server.py:6384`), not as wikilinks. Accept path:
  `relations_proposal_accept` (`:6805-6840`). Curated pairs only protect from removal,
  they never add (`relation_reconcile.py:148`).
- **L5** (evidence, mapping): `_apply_grounded_relations` runs on `content_preview`, which
  is the full body (`import_router.py:1456`), not the 1500-char prompt window. The
  deterministic importer path is sound; the gap is the proposal layer.
- **L6** (decision): the importer's auto-verified claims need their own provenance, not
  `curated.json` (which means "the Owner explicitly wanted this"). Hence S5's
  self-invalidating evidence store.
- **L7** (T1 evidence): `relation_proposing.py` (Source/CatalogEntry/Claim,
  `pair_key`, `quote_in_body`, `build_proposal_prompt`, `verify_claims`,
  `propose_relations_outcome`) plus 15 tests. The K8 regression is pinned: eight
  sources with no mutual mentions and no quotes yield zero claims. Commits
  `dbd4834`, `a05b9fd`, `1c83361`.
- **L8** (T2 evidence): `relation_evidence.py` (record/record_many/forget/
  load_evidence/verified_ids) plus 10 tests, including self-invalidation when the
  quote disappears from the rewritten body. Commit `dbd4834`.
- **L9** (T3 evidence): `sweep_batch` processes `candidates[:size]` (default 5,
  clamp 1..10) through one `propose_relations_outcome` call, full body for
  evidence and a 4000-char prompt body, world-wide catalog, `known_pairs` from
  declared/rejected/evidenced stores, `mark_swept` only on `provider_ok`.
  Candidates now order by mention count. The queue keys the unordered pair.
  Focused relation suites 31 passed; ProposalsPanel 7 tests; typecheck clean.
  Commit `223e455`, UI in `4ac3d95`.
- **L10** (T4 evidence): the funnel runs the model's own `relationships` through
  `verify_claims` against the FULL `content_preview`, marks them
  `verified: true/false` in `enrichment_json` (unverified ones stay advisory and
  never reach `relaciones`), and materialization records the verified quotes in
  `.relations/evidenced.json` fail-open. Import subset 106 passed. Commit
  `eb7c60f`.
- **L11** (T5 evidence): `build_global_plan` unions `verified_ids` into
  `grounded` (rejected pairs still win) and classifies ungrounded removals as
  `redundant-folder` (same folder) or `ungrounded`. P4 suites 20 passed.
  Commit `958909d`.
- **L12** (T6 evidence): full wiki suite `4725 passed, 26 skipped`; frontend
  `134 files / 1667 tests passed`; `tsc --noEmit` clean; `npm run build` ok and
  the served asset matches (`assets/index-Dev5-ru-.js`).
- **L13** (real-world evidence, 2026-10-31): with the backend restarted, the live
  preview of the real world reports 68 fichas / 258 altas / 112 bajas classified
  as **110 `redundant-folder` + 2 `ungrounded`**. The two genuine ones are two
  folder indexes pointing at an unrelated document.
- **L14** (decision): receipt-driven development is unavailable in this workspace
  (the native review rejects the repository's FUSE/ntfs-3g git directory as
  unrepairable ownership), so verification ran under ordinary policy: full
  suites, typecheck, build and a live read-only check. No native review receipt
  exists for these commits.
- **L15** (gap): the sweep was NOT executed against the real world (it costs
  model calls and mutates `.relations/`); the first real batch and the sync
  application remain the Owner's decision.
