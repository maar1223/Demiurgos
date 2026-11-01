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
- **S10 — Import reads the text.** The importer's relationship pass sends each
  source's bounded body, not only its summary, so the model can quote what it
  read. The quote is verified against the FULL body; the excerpt bounds cost only.
- **S11 — Importing is reviewing.** A ficha whose text pass actually answered is
  recorded as reviewed at its written digest, so the sweep does not read the same
  text twice. A provider outage marks `error` and leaves the ficha for the sweep.
- **S12 — A word that names many fichas identifies none.** Filename-stem and
  ordinal evidence are admissible only when the word names exactly one entity in
  the world (title + filename + folder). A family word (shared by several names)
  is never evidence for a member: the folder index carries the belonging.
- **S13 — "This link is wrong" acts on the pair.** Breaking a relation records
  the rejection in BOTH directions and removes the declared entry from both
  fichas, so the edge disappears at once; creating clears both directions. The
  inspector offers the action on each relation row.
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
| T7 | S10 | inline | done | `aee83c5` — body in the relationship prompt + harness discriminators |
| T8 | S11 | inline | done | `f141448` — reviewed marking, `error` on outage, sweep-skip test |
| T9 | S9 | inline | done | `d7cfcb1` — explicit suite paths; 4730 passed / 26 skipped |

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
- **L16** (verbatim, 2026-10-31): "deberia hacerse de una vez, porque seria mejor
  hacer doble trabajo y doble gasto?"
- **L17** (verbatim, 2026-10-31): "ok pero el importador no hace barrido tambien?"
- **L18** (T7/T8 evidence): the relationship prompt now carries
  `_RELATIONSHIP_BODY_BUDGET` (4000) chars of each source's body and demands the
  quote come from `body`, never the summary; the request stays one independent
  read per ficha. The chunk budget is unchanged (8 fichas / 40k chars of body, so
  the excerpt fits). Materialization marks a ficha swept at
  `body_digest(_body_after_frontmatter(document))` only when the enrichment
  status is `ok`/`no_suggestions`; `error` and `disabled` never mark. New tests:
  prompt carries the body; reviewed ficha is not a sweep candidate; an unanswered
  pass stays a candidate (verified through the file on disk split the same way the
  indexer splits it). Commits `aee83c5`, `f141448`.
- **L19** (test-infra evidence): the wiki suite depended on whichever module had
  inserted `src/tools` and the suite root into `sys.path` first, so an isolated
  run of `test_import_lifecycle` failed on a lazy `sync_lore` import. The conftest
  now inserts both explicitly. Full suite 4730 passed / 26 skipped. Commit
  `d7cfcb1`.
- **L20** (bugfix evidence, 2026-11-01): applying the sync on the real world left
  `Sincronizar · 3 cambios` forever and reported `Sincronizadas 0 fichas`. Cause:
  the frontmatter writer emitted bare scalars, and a canonical id containing
  `": "` (`Eneatipo 8: El Desafiante`) is valid YAML as a MAPPING, so the entry
  was parsed as a dict and dropped by every `isinstance(entry, str)` filter; the
  plan re-added it, the writer saw the text already present and changed nothing.
  9 of 72 ids in the world are affected. Fix: `_yaml_relation_scalar` quotes only
  values that do not round-trip as the same string (simple ids keep their bytes).
  4 corrupted entries repaired in 3 files (backup
  `/tmp/opencode/relations-yaml-repair-backup`); the preview converges to
  0/0/0 after an index reload. Suite 4732 passed / 26 skipped.
- **L21** (finding, 2026-11-01, open): 133 of 326 directed edges (41%) come from
  `stem` evidence, and only 41 from a full name. `Planeta Vibral | Naturaleza y
  Biodiversidad` has 36 edges because its FILENAME contains `vibral` (24 fichas),
  `naturaleza` (12), `planeta` (10) and `biodiversidad` (6); the matches are the
  common noun ("refleja la naturaleza empática de su vibrante"). The stem rule
  takes any word longer than three characters from the filename, so a long
  descriptive title becomes a magnet. This is what makes the graph a hairball,
  not the sync.
- **L22** (S12 evidence, 2026-11-01): `_ambiguous_identity_keys` now counts
  title and folder words, not only filenames, and the ordinal noun must also be
  distinctive. Real-world effect: 326 directed edges -> 207 (unique pairs 263 ->
  166, average degree 8.12 -> 5.75). `stem` 133 -> 63; `ordinal` 49 -> 0 (every
  ordinal match was cross-family); `full-name` 41 and `folder-index` 103
  untouched. The cleanup sync applied 59 files / 119 removals (118 of them added
  by the previous sync; the single pre-existing link was preserved in
  `.relations/curated.json`), backup `.relations/preimages/20261101T044737784768Z`,
  and the preview converges to 0/0/0 with zero malformed entries. Suite 4735
  passed / 26 skipped.
- **L23** (open, not applied): of the 63 surviving `stem` edges, 37 match only a
  lowercase occurrence (`eneatipo`, `historia`, `religion`, `niveles`, `estados`,
  `origen`). Requiring a capitalized occurrence would cut them, but it would also
  drop lowercase family references, so it stays a decision, not a default.
- **L24** (S13 evidence, 2026-11-01): the graph already had a break flow on an
  edge, and it recorded only the directed pair, so the reverse ficha kept the
  edge alive until a sync. Break now records both directions, mirrors the removal
  on the target ficha and unpins both curated sides; create clears both. The
  inspector renders a per-relation action (`data-testid="remove-relation"`) only
  when a handler is provided and the entry resolves to a node key, wired to the
  existing `breakRelation` (no duplicate endpoint). Tests: backend bidirectional
  break + P2 expectations updated to the pair semantics; inspector action test.
  Suite 4736 passed / 26 skipped; frontend 1669 passed.
