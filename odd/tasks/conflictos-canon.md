# Conflictos — canon governance panel (S1→S4)

Branch `feat/conflictos-canon` (base master `247c42e`). Delivery: work-unit commits, local merge, no PR.
Runner: `pytest src/tools/demiurgos-suite/wiki/tests/` · `cd frontend && npm test -- --run` · `cd frontend && npm run typecheck`.

## Specs

- **S1 — Scope.** The "Conflictos" tab of Relaciones y Canon, delivered in four slices in this order: S1 → S2 → S3 → S4. Each slice is one work unit with its own commit. The "Próximamente" placeholder is removed by S1.
- **S2 — S1 is deterministic and read-only.** No model call, no write, no file creation. Detection is computed on request from the graph index.
- **S3 — S1 conflict codes (closed set).** `identity`, `version`, `missing-minimum`, `unresolved-reference`, `ambiguous-reference`, `duplicate-id`, `dangling-relation`, `self-relation`, `canon-state-mismatch`.
- **S4 — Severity.** `error` = the world graph cannot be trusted (`identity`, `version`, `unresolved-reference`, `ambiguous-reference`, `duplicate-id`, `dangling-relation`, `self-relation`). `warning` = incomplete or incoherent but resolvable (`missing-minimum`, `canon-state-mismatch`).
- **S5 — Endpoint.** `GET /api/{mundo}/conflicts` returns `{ indexed, conflicts, summary }`. Unknown world returns `{ "indexed": false, "conflicts": [], "summary": <zeros> }`, the same soft-empty contract as `/graph/entities`. Each conflict: `id`, `code`, `severity`, `path`, `name`, `message`, `field`, `reference`.
- **S6 — Read source.** Reads only the graph index (constitution §4.3: the filesystem is forbidden for entity queries) and never writes.
- **S7 — Panel.** Lists conflicts grouped by severity, shows the ficha path and the message, and opens the ficha on click. Empty state states the world has no conflicts; a failed request shows a retryable error.
- **S8 — i18n.** Every new user-facing string exists in `es` and `en`.
- **S9 — Tests.** Backend: one unit test per code plus a clean-world zero case, and endpoint tests (populated world, unknown world). Frontend: panel renders items, empty state, error state.
- **S10 — S2 (W11).** Decisions and history: `resolver` (gated ficha write), `intencional` (known conflict, not an error), `silenciar`, `ruptura estructural`. Records live under `mundos/<mundo>/conflictos/` as Markdown with YAML frontmatter plus a readable body; they are not entities and never enter the graph. Detailed specs are added when S2 starts.
- **S11 — S3.** Semantic ficha-vs-ficha detector with textual evidence from both fichas, on demand and in a bounded batch with its cost visible. Never writes. Detailed specs are added when S3 starts.
- **S12 — S4.** Graph integration: badge on conflicted nodes, focus, filter, and a ficha indicator. Detailed specs are added when S4 starts.

## Tasks

| ID | Spec | Route | Status | Evidence |
|---|---|---|---|---|
| T1 | — | inline | done | this document + Engram mirror |
| T2 | S2, S3, S4, S6, S9 | inline | done | `conflict_detector.py`; 13 unit tests (RED: module missing) |
| T3 | S5, S9 | inline | done | `GET /api/{mundo}/conflicts`; 4 endpoint tests (RED: 404, then 4/4) |
| T4 | S7, S8, S9 | inline | done | `ConflictsPanel` + `api/conflicts.ts` + es/en; 5 panel tests |
| T5 | S1 | inline | done | 551 backend tests, 1688 frontend tests, `tsc` clean, 2 commits |
| T6 | S10 | pending | pending | S2 |
| T7 | S11 | pending | pending | S3 |
| T8 | S12 | pending | pending | S4 |

## Log

**L1 (Owner, verbatim):** "vamos con la seccion de Conflictos que habiamos dejado para una nueva sesion. Que vamos a colocar y como funcioaria esa parte dentro de Demiurgos?"

**L2 (Owner, verbatim):** "vamos en el orden logico, de menos a mas. S1 - S2 - S3 - S4"

**L3 — Technical correction (evidence).** The approved S1 sketch listed "relaciones asimétricas" as a conflict. Verified against the code: `relaciones` is a directed declaration per ficha (`relation_reconcile.build_global_plan` computes `add` per source, and `relation_proposing` skips only `target_id == source_key`). A one-sided declaration is therefore normal, not an inconsistency. Replaced by two real defects: `dangling-relation` (entry points to a non-existent id — the reconcile plan already classifies it as `reason="unresolved"`) and `self-relation` (entry points to the entity itself). S3 updated accordingly.

**L4 — Evidence for the design.** Verified in code, not memory: the Conflictos tab is a placeholder (`frontend/src/pages/RelacionesCanon.tsx:198-206`); no HTTP endpoint exists for conflicts; W11 persistence does not exist (`conflictos/` and `propuestas/` only appear in `TRANSVERSAL_DIRS` as reserved folder names); the only detector is the MCP tool `lore_conflicts` (`graph_mcp_server.py:215` → `mcp_adapter.py:245`), which compares ficha claims against **Engram memory**, not against another ficha. The roadmap already flags the `_TEXT_SYSTEM_PROMPT` "extracts contradictions" claim as STALE.

**L5 — S1 design decisions.** Detection lives in a new pure module `conflict_detector.py` over the entity dicts the graph index already caches (`content`, `id`, `status`, `canon_state`, `relaciones`, `path`, `name`), so it needs no disk read and no second parser. Reference resolution reuses `okf_contract.validate(..., resolve=...)` with `EntityGraphIndex._resolve_link_candidates`; relation entries reuse `import_relations.relaciones_entry_key`. `canon-state-mismatch` flags only the two hard contradictions of the same axis: `status: draft` + `canon_state: canon`, and `status: stable` + `canon_state: propuesta`. Other canon states (`creencia`, `leyenda`, `hipotesis`, `perdido`, `prohibido`) are orthogonal to draft/stable and are not flagged.

**L6 — Working tree note.** The branch carries the Owner's uncommitted graph-label/fullscreen work (`GraphView.tsx`, `graphLabels.ts`, `messages.ts`, two tests). Those files are excluded from this feature's commits; only the new conflict keys are committed in `messages.ts`.

**L7 — S1 verification (observed).** Backend: `pytest test_conflict_detector.py` 13/13 (RED observed first: `ModuleNotFoundError: conflict_detector`); `pytest test_api_server.py -k TestWorldConflictsEndpoint` 4/4 after observing RED (3 failed against the route-less server, 1 trivially passing read-only test); full `test_api_server.py` + `test_conflict_detector.py` 551/551. Frontend: `vitest run` 1688/1688 across 136 files; `tsc --noEmit` clean.

**L8 — Isolation (working tree).** A concurrent OpenCode session was editing the main working tree (`RelacionesCanon.tsx`, `messages.ts`, graph files) and running its own vitest while S1 was being written. To avoid racing, S1 was moved to the sibling worktree `../demiurgos-worktrees/conflictos-canon` (branch `feat/conflictos-canon`, `frontend/node_modules` symlinked to the main checkout). The main tree was restored to master with none of this feature's changes. Expect a trivial conflict on `RelacionesCanon.tsx` (tab order) when merging, and none on `messages.ts` (different regions).
