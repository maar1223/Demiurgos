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
| T3 | S2, S8 | delegated | pending | — |
| T4 | S6 | delegated | pending | — |
| T5 | S7 | delegated | pending | — |
| T6 | S9 | inline | pending | — |

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
