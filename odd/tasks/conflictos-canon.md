# Conflictos — canon governance panel (S1→S4)

Branch `feat/conflictos-canon` (base master `247c42e`). Delivery: work-unit commits, local merge, no PR.
Runner: `pytest src/tools/demiurgos-suite/wiki/tests/` · `cd frontend && npm test -- --run` · `cd frontend && npm run typecheck`.

## Specs

- **S1 — Scope.** The "Conflictos" tab of Relaciones y Canon, delivered in four slices in this order: S1 → S2 → S3 → S4. Each slice is one work unit with its own commit. The "Próximamente" placeholder is removed by S1.
- **S2 — S1 is deterministic and read-only.** No model call, no write, no file creation. Detection is computed on request from the graph index.
- **S3 — S1 conflict codes (closed set).** `identity`, `version`, `missing-minimum`, `unresolved-reference`, `ambiguous-reference`, `duplicate-id`, `dangling-relation`, `self-relation`, `canon-state-mismatch`.
- **S4 — Severity.** `error` = the world graph cannot be trusted (`identity`, `version`, `unresolved-reference`, `ambiguous-reference`, `duplicate-id`, `dangling-relation`, `self-relation`). `warning` = incomplete or incoherent but resolvable (`missing-minimum`, `canon-state-mismatch`).
- **S5 — Endpoint.** `GET /api/{mundo}/conflicts` returns `{ indexed, conflicts, summary }`. Unknown world returns `{ "indexed": false, "conflicts": [], "summary": <zeros> }`, the same soft-empty contract as `/graph/entities`. Each conflict: `id`, `code`, `severity`, `path`, `name`, `message`, `field`, `reference`, `decision` (`null` when undecided). Summary: `{ total, errors, warnings, known, muted, by_code }`; `muted` conflicts never appear in `conflicts`, and `intentional` ones are counted in `known` instead of `errors`/`warnings`.
- **S6 — Read source.** Reads only the graph index (constitution §4.3: the filesystem is forbidden for entity queries) and never writes.
- **S7 — Panel.** Lists conflicts grouped by severity, shows the ficha path and the message, and opens the ficha on click. Empty state states the world has no conflicts; a failed request shows a retryable error.
- **S8 — i18n.** Every new user-facing string exists in `es` and `en`.
- **S9 — Tests.** Backend: one unit test per code plus a clean-world zero case, and endpoint tests (populated world, unknown world). Frontend: panel renders items, empty state, error state.
- **S10 — S2 (W11).** Decisions and history. Closed decision set: `intentional` (known conflict, never an error), `muted` (hidden), `structural` (escalated rupture, stays an error). "Resolved" is not a decision: it is what happens when the data stops contradicting, and the record stays as history. Each decision is one Markdown record under `mundos/<mundo>/conflictos/<slug>-<hash8>.md` with YAML frontmatter (`conflict_id`, `code`, `decision`, `path`, `name`, `reference`, `field`, `decided_at`, `note`) and a readable body; records are not entities and never enter the graph. `POST /api/{mundo}/conflicts/decision` with `{conflict_id, decision, note?}` records or updates one decision (`decision: "clear"` removes it); the conflict must currently be computed (404 otherwise) and an unknown decision is 422. The panel never edits a ficha: it records the Author's decision and links to the ficha.
- **S11 — S3.** Semantic ficha-vs-ficha detector. One model call reviews ONE ficha against a bounded shortlist of related fichas (declared `relaciones`, resolved wikilinks, backlinks; max 8 targets, 4000/1500-char excerpts). The prompt asks only for contradictions of world truth (dates, statuses, names, relationships, membership) and forbids reporting perspectives, legends, beliefs and deliberate ambiguity. A claim survives only when it quotes a fragment that appears in the source body AND a fragment that appears in the target body (`quote_in_body`). Candidates are stored as `state: proposed` records with both quotes and the pair, and are re-verified against the current text on every read: a contradiction fixed by editing stops being shown and the record stays as history. `POST /api/{mundo}/conflicts/sweep` with `{size?}` (default 3, clamped 1..5) reviews one batch; `.conflicts/swept.json` remembers each ficha's body digest, so an unchanged ficha is never paid for twice; an outage marks nothing swept. `POST /api/{mundo}/conflicts/proposal/reject` marks a model mistake and remembers the pair so it is never proposed again. The panel never edits a ficha.
- **S13 — Review progress.** `GET /api/{mundo}/conflicts` and the decision/reject responses carry `summary.review = {total, reviewed, pending}`, computed from `.conflicts/swept.json` against the current body digests (editing a ficha puts it back in the queue). The panel shows `Por revisar: {pending} de {total}` and the sweep button reads `Revisar 3 fichas · quedan {pending}`, disabled with `Todo revisado` when nothing is left. The sweep response's `pending` was renamed to `proposals` because it counts proposals, not fichas.
- **S12 — S4.** Graph integration and the ficha indicator. The graph reads the same `GET /api/{mundo}/conflicts` as an overlay (a failed request never hides the graph), derives the conflicted node keys from `id || path`, paints a danger badge on both zoom tiers, and offers a "Solo con conflictos" switch next to the orphan switch. The entity page shows a banner with the open-conflict count for that ficha and a link to the Conflictos section. No new backend surface.

## Tasks

| ID | Spec | Route | Status | Evidence |
|---|---|---|---|---|
| T1 | — | inline | done | this document + Engram mirror |
| T2 | S2, S3, S4, S6, S9 | inline | done | `conflict_detector.py`; 13 unit tests (RED: module missing) |
| T3 | S5, S9 | inline | done | `GET /api/{mundo}/conflicts`; 4 endpoint tests (RED: 404, then 4/4) |
| T4 | S7, S8, S9 | inline | done | `ConflictsPanel` + `api/conflicts.ts` + es/en; 5 panel tests |
| T5 | S1 | inline | done | 551 backend tests, 1688 frontend tests, `tsc` clean, 2 commits |
| T6 | S10 | inline | done | `conflict_decisions.py`; 9 unit tests; 6 endpoint tests (RED: 6/6 failed, then 12/12) |
| T9 | S10, S7, S8 | inline | done | panel actions + known/muted groups; 9 panel tests |
| T7 | S11 | inline | done | `conflict_proposing.py` + `conflict_sweep.py`; 18 + 11 unit tests; 6 endpoint tests |
| T10 | S11, S7, S8 | inline | done | sweep button (cost visible), proposed group with both quotes, reject; 4 panel tests |
| T8 | S12 | inline | done | graph badge + filter; entity banner; 1 + 3 tests |
| T11 | S13 | inline | done | review progress in the summary + button state; 3 + 2 tests |

## Log

**L1 (Owner, verbatim):** "vamos con la seccion de Conflictos que habiamos dejado para una nueva sesion. Que vamos a colocar y como funcioaria esa parte dentro de Demiurgos?"

**L2 (Owner, verbatim):** "vamos en el orden logico, de menos a mas. S1 - S2 - S3 - S4"

**L3 — Technical correction (evidence).** The approved S1 sketch listed "relaciones asimétricas" as a conflict. Verified against the code: `relaciones` is a directed declaration per ficha (`relation_reconcile.build_global_plan` computes `add` per source, and `relation_proposing` skips only `target_id == source_key`). A one-sided declaration is therefore normal, not an inconsistency. Replaced by two real defects: `dangling-relation` (entry points to a non-existent id — the reconcile plan already classifies it as `reason="unresolved"`) and `self-relation` (entry points to the entity itself). S3 updated accordingly.

**L4 — Evidence for the design.** Verified in code, not memory: the Conflictos tab is a placeholder (`frontend/src/pages/RelacionesCanon.tsx:198-206`); no HTTP endpoint exists for conflicts; W11 persistence does not exist (`conflictos/` and `propuestas/` only appear in `TRANSVERSAL_DIRS` as reserved folder names); the only detector is the MCP tool `lore_conflicts` (`graph_mcp_server.py:215` → `mcp_adapter.py:245`), which compares ficha claims against **Engram memory**, not against another ficha. The roadmap already flags the `_TEXT_SYSTEM_PROMPT` "extracts contradictions" claim as STALE.

**L5 — S1 design decisions.** Detection lives in a new pure module `conflict_detector.py` over the entity dicts the graph index already caches (`content`, `id`, `status`, `canon_state`, `relaciones`, `path`, `name`), so it needs no disk read and no second parser. Reference resolution reuses `okf_contract.validate(..., resolve=...)` with `EntityGraphIndex._resolve_link_candidates`; relation entries reuse `import_relations.relaciones_entry_key`. `canon-state-mismatch` flags only the two hard contradictions of the same axis: `status: draft` + `canon_state: canon`, and `status: stable` + `canon_state: propuesta`. Other canon states (`creencia`, `leyenda`, `hipotesis`, `perdido`, `prohibido`) are orthogonal to draft/stable and are not flagged.

**L6 — Working tree note.** The branch carries the Owner's uncommitted graph-label/fullscreen work (`GraphView.tsx`, `graphLabels.ts`, `messages.ts`, two tests). Those files are excluded from this feature's commits; only the new conflict keys are committed in `messages.ts`.

**L7 — S1 verification (observed).** Backend: `pytest test_conflict_detector.py` 13/13 (RED observed first: `ModuleNotFoundError: conflict_detector`); `pytest test_api_server.py -k TestWorldConflictsEndpoint` 4/4 after observing RED (3 failed against the route-less server, 1 trivially passing read-only test); full `test_api_server.py` + `test_conflict_detector.py` 551/551. Frontend: `vitest run` 1688/1688 across 136 files; `tsc --noEmit` clean.

**L8 — Isolation (working tree).** A concurrent OpenCode session was editing the main working tree (`RelacionesCanon.tsx`, `messages.ts`, graph files) and running its own vitest while S1 was being written. To avoid racing, S1 was moved to the sibling worktree `../demiurgos-worktrees/conflictos-canon` (branch `feat/conflictos-canon`, `frontend/node_modules` symlinked to the main checkout). The main tree was restored to master with none of this feature's changes. Expect a trivial conflict on `RelacionesCanon.tsx` (tab order) when merging, and none on `messages.ts` (different regions).

**L9 — Spec change (S5/S10).** S2 extends the payload: each conflict carries `decision`, and the summary adds `known` and `muted`. The three S1 endpoint tests were updated to the new shape. Rationale: a decided conflict must stay visible as known (W5) or disappear when muted, and the header has to say how many of each.

**L10 — S2 backend verification (observed).** RED first: with `api_server.py` and `conflict_detector.py` reverted to S1, all 6 new decision tests failed. GREEN after the change: `test_api_server.py -k Conflict` 12/12; full `test_api_server.py` + both conflict test modules 566/566.

**L11 — Spec revision (S5, second pass).** `muted` conflicts stay in the payload with `decision: "muted"` instead of disappearing. Reason: hiding them from the payload left no way to undo a mute from the UI (the Author would have to delete the record file). The panel renders them in a collapsed "Silenciados" group with "Quitar decisión", the same pattern the proposals panel already uses for muted candidates. `total` counts every computed conflict; `errors`/`warnings` exclude `intentional` and `muted`.

**L12 — S2 verification (observed).** Backend: 9 decision unit tests (RED: `ModuleNotFoundError`), 6 endpoint tests (RED: 6/6 failed with the S1 server), full touched suite 566/566. Frontend: panel 9/9 (RED: 5 failed against the S1 component), `RelacionesCanon` 8/8, full suite 1692/1692 across 136 files, `tsc --noEmit` clean.

**L13 — Spec revision (S5, third pass).** Every conflict now carries `state` (`computed|proposed|decided`) and `origin` (`deterministic|semantic`), plus `evidence_a`/`evidence_b`/`source_a`/`source_b` (null for deterministic ones). The summary adds `proposed`; proposed items are counted apart and never as errors. The closed code set grows by `semantic-contradiction`. Rationale: the panel must distinguish "the structure contradicts itself" from "the model suggests a contradiction", and the two have different lifecycles.

**L14 — S3 verification (observed).** Backend: 18 proposing unit tests (RED: `ModuleNotFoundError`), 11 sweep unit tests (RED: `ModuleNotFoundError`), 6 endpoint tests, full touched suite 607/607. Frontend: panel 13/13 (RED: the 4 S3 tests failed against the S2 component), `RelacionesCanon` 9/9, full suite 1697/1697 across 136 files, `tsc --noEmit` clean.

**L15 — S4 implementation.** The graph overlay is one extra parallel request in the existing `load()`; conflicts are matched to nodes through the entity `path`, then rendered by the node key (`id || path`), so legacy fichas without a canonical id still light up. The filter reuses the same derived key set as the badge, so the two can never disagree. The entity banner matches by ficha `name` (the entity route is name-based) and fails silent.

**L16 — S4 verification (observed).** GraphView 50/50 (the new badge + filter test passes; RED would be the missing `graph-node-conflict` test id), EntityPage 3/3, full frontend suite 1701/1701 across 137 files, `tsc --noEmit` clean. Backend untouched by S4.

**L17 — Review-progress follow-up (Owner request).** The Owner asked how to know when to start, finish or whether the review was complete; the panel only answered after clicking. Added `summary.review` (deterministic, free) and made the button carry its state. Also renamed the sweep response's misleading `pending` (it counted proposals) to `proposals`; the relations sweep endpoint keeps its own `pending`, which is correct there.

**L18 — Verification (observed).** Backend 610/610 on the touched modules (3 new `review_progress` unit tests); frontend 1709/1709 across 137 files; `tsc --noEmit` clean. Bundle rebuilt and the served asset matches `dist`.

**L19 — Fail-safe review progress (observed defect).** The first live load showed "Por revisar: 0 de 0 / Todo revisado" on a world nobody had reviewed. Cause: the API process had booted at 14:51, before the review-progress commit, so its payload had no `summary.review`; the panel defaulted a missing block to zeros and claimed completion. Two fixes: the backend was restarted with the current code (the launcher has no auto-reload), and `review` is now optional in the client type — when absent the panel shows the counts without the review segment and leaves the sweep enabled, never "Todo revisado". Live API now reports `review: {total: 70, reviewed: 0, pending: 70}` for Vibrantes.

**L20 — Sweep timeout (observed defect).** The first live sweep reported "No se pudo guardar la decisión." while the server kept working: the sweep is synchronous (one model call per ficha, 8-20s each) and the client's 5s default aborted it. Fixed exactly like the relations sweep: `sweepConflicts` sends `timeout: 180_000`, and the panel distinguishes `network.timeout` from a real failure ("el proveedor sigue trabajando…"). The 3 fichas of that aborted call were reviewed server-side, so the counter moved from 70 to 67 without proposals.
