# Feature: materialize-graph-grounding

## Status
- Route: delegated direct (ODD) — no SDD selected.
- TDD: OFF (no project TDD config; not requested).
- Delivery strategy: `single-pr` (inferred).
- Review (RDD): OFF (`clone_local`). No native review lifecycle.
- Base: `feat/materialize-preview-ux` @ `7ca1e24`.

## Objective
Give the materialization AI the **right** slice of the world: the entities the idea actually talks about, plus their graph neighbours. Today it receives an arbitrary slice chosen by file order.

## Problem (measured, user-reported)
The user materialized an idea about Chaae, a region that exists in the world, and the preview said "Relaciones propuestas: Ninguna". Investigation:

- The world has **70 entities**; only **13** reached the AI (3 919 of the 4 000-char budget).
- The 13 were **all from `Áyagars | Reptiles Vibrantes`** — the first folder in the file walk, and also the world's **hubs** (most connected). So the bias is systematic, not bad luck.
- **Chaae was never sent to the model**, which therefore correctly returned `relations: []`. "Descartadas: Ninguna" is consistent: nothing was proposed, so nothing was discarded.
- The graph already knows the answer: `chaae.md` declares `relaciones: [[…Pannj]]`, `pannj.md` links back, and **60 of the world's fichas carry relations**.
- Measured alternative (title → BM25 seeds → 1-hop neighbours): **4 entities / 1 121 chars**, with **Chaae first (score 15.06)** and its neighbour Pannj included.

The genuine defect is **the selection rule**, not the AI and not the world.

## Decisions (user-approved)
1. The 4 000-char budget stops being a TARGET and becomes only a **guard**. Filling it is actively harmful: it caused this bug, it distracts the model, and it costs tokens.
2. The candidate set is the **graph neighbourhood**, not the whole world.
3. Seed selection is a **HYBRID**:
   - the **best score sets the bar** (keep hits close to the best),
   - the **best always enters** (the list is never empty when there is at least one hit),
   - a **small ceiling** (3–5 seeds),
   - **hubs only when nothing matches at all**.
4. Seeds are **expanded one hop** through the graph (forward links + backlinks). One bad seed multiplies, so the seed step must stay conservative.
5. Tags are **not** used to seed: measured as the noisy signal (they dragged in 12 of 16 Dvex entries).

## Authorized scope
- `src/tools/demiurgos-suite/wiki/idea_materialization_domain.py` (`build_grounding_candidates`)
- `src/tools/demiurgos-suite/wiki/api_server.py` (the reader seam + the call site)
- their tests under `src/tools/demiurgos-suite/wiki/tests/`
- `odd/tasks/materialize-graph-grounding.md` (this document)

## Out of scope
- The AI prompt, the model, the envelope validation and the relation validator (unchanged).
- `validate_relations` keeps validating against ALL existing world ids (not just the candidates).
- The preview UX, the naming rule, the image carry and the H1 rule.

## Contract

### Reader seam
`build_grounding_candidates` needs the graph, not just a list. The reader must expose:
- `search(query) -> list[dict]` (hits carry a `score`),
- `entities() -> list[dict]`,
- **NEW** `neighbors(path) -> list[dict]` — the entity's forward links plus its backlinks,
- **NEW** `hubs() -> list[dict]` — the most connected entities.
`_GuidedGraphReader` implements the two new methods over `EntityGraphIndex.get_links` and the index's backlinks accessor; prefer a public surface and document any private accessor used.

### Signature
`build_grounding_candidates(reader, *, idea_title: str, idea_body: str = "") -> list[dict[str, str]]` (drop `section_filter`; the call site passes the idea's title and a BOUNDED body excerpt).

### Selection (deterministic, in this order)
1. **Stage 1 — precise:** `hits = reader.search(idea_title)` when the title is non-empty.
2. **Stage 2 — broaden:** only if stage 1 produced no hits, retry with `f"{idea_title} {body_excerpt}"` (excerpt bounded, e.g. first 400 chars, whitespace-collapsed).
3. **Stage 3 — blind map:** only if there are still no hits, use `reader.hubs()` as the candidate set.
4. Otherwise, from the hits: `best = max(score)`; keep hits with `score >= SEED_RATIO * best` (SEED_RATIO ≈ 0.9), ordered by score desc (ties by id asc), **capped at SEED_LIMIT ≈ 5**, and **the best always included**.
5. **Expand one hop:** for each kept seed (in order), append `reader.neighbors(seed_path)`, deduped by id, neighbours sorted by (how many seeds connect to them desc, id asc).
6. **Guard, not target:** stop at `MAX_CANDIDATES` or `MAX_CANDIDATE_PAYLOAD_CHARS`, dropping from the TAIL — never a seed.
7. Skip entities without a non-empty canonical `id` (unchanged rule).

### Candidate shape (unchanged)
`{"id", "title", "type", "summary"}` — `summary` bounded by `MAX_CANDIDATE_SUMMARY_CHARS`.

## Tasks
- [x] **MG-1 — Backend: graph-aware grounding** (delegated writer)
  - Implement the seam, the signature, the hybrid selection and the one-hop expansion exactly as specified.
  - Keep `MAX_CANDIDATES` / `MAX_CANDIDATE_PAYLOAD_CHARS` as guards; the natural set is expected to be far smaller.
  - Tests with deterministic FAKE readers (no real index): the relative bar keeps only near-best hits; the best always survives a flat/weak score distribution; the ceiling caps the seeds; neighbours are added and deduped; a neighbour shared by several seeds ranks above a single-seed one; no hits at all falls back to hubs; an empty title falls to the body stage; ordering is stable; the guard drops the tail and never a seed; entities without a canonical id are skipped.
  - Integration: the real call site passes the idea title (+ bounded body) and the preview still works; assert Chaae's id reaches the candidate list for the Silpah-shaped fixture (a fake reader whose search ranks Chaae first).
- [x] **MG-2 — Verify, build, restart, commit** (parent, bounded actions)

## Constraints
- The AI prompt, the model, the envelope validation and `validate_relations` stay untouched.
- No new dependency. Deterministic output for a given input (no random ordering).
- Guard-vs-target wording must hold: a full budget must never be the goal.
- Technical artifacts in English; comments must explain WHY the graph is used and why the budget is only a guard.

## Progress log
- 2026-09-27: Document created after the user approved the hybrid. MG-1..MG-2 queued.

## Verification evidence
- PARENT MEASUREMENT against the user's REAL world and the REAL idea (`2026-08-28-524e8b9c9770`, title "Silpah — Lince Relámpago de Chaae", 70 entities):
  - Before (file order): 13 candidates / 3 919 chars, **no Chaae**.
  - After (graph): **2 candidates / 517 chars — `Política | Distribución Y Territorios::Chaae` and `Política | Distibución Y Territorios::Pannj`** (both `lugar`).
  - `neighbors(chaae)` resolves to `[Pannj]` through the real index.
  - Intermediate check at `SEED_RATIO = 0.90` produced 10 candidates including 8 Eneatipos (noise from one bad seed) — the evidence behind the tuning.
- Backend: `pytest tests/ -q` → **3232 passed, 1 failed, 1 skipped**. The failure is the known pre-existing live-gateway test `tests/test_semantic_e2e.py::TestLiveHermesFirstE2E::test_live_guided_start_semantic_first`, reproduced identically on the base with the changes stashed. Focused (domain + api) → 574 passed.
- Runtime: backend restarted (pid 118539); `/api/config` 200, `materialize-preview` 401 (auth gate).
- Independent verification: NOT yet run for this change (the parent will note it).
- Could NOT verify: the live AI output with the new candidate set (needs a real generation), and the world's remaining ideas beyond the title sweep.

## Next step
Delegate MG-1, then MG-2.
