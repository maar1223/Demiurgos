# Assistant citations (Fuentes footer)

Branch: `feat/assistant-runtime-evolution` (worktree `demiurgos-worktrees/assistant-runtime-evolution`). Delivery: work-unit commits; push/PR/merge stay the Owner's. Runners: `.venv/bin/python -m pytest src/tools/demiurgos-suite/wiki/tests/ -q`; golden set: `python3 scripts/eval_assistant.py --gateway http://127.0.0.1:8642/v1 --corpus odd/evidence/assistant-golden/.local/worlds --world vibrantes`.

## Specs

**S1 — World facts must carry their source.** Owner, verbatim: *"lo de la cita me parece bien importante, es algo similar a lo que pasa cuando le pides las referencias a la IA de donde sacó los datos que está explicando al usuario. Asi que en este caso me parece que tiene sentido hacer algo asi"*. The level-C acceptance (`docs/architecture/ASSISTANT_WORLD_READING.md` §5) already requires citing the ficha path; today the assistant cites loosely (world name, sometimes the sheet) or not at all.

**S2 — Format A: a `Fuentes:` footer.** Owner, verbatim: *"si, me gusta la A"*. End the answer with a single line `Fuentes:` followed by the ficha path(s), comma-separated and backticked (`Fuentes: `lore/.../x.md``). English answers use `Sources:`.

**S3 — Only real, actually-read fichas.** The path is exactly the value returned by `graph_search`/`graph_read` (relative to the world root), never an invented path; omit the line when no ficha was used.

**S4 — Real-world context only.** The world-agnostic `ideas-global` assistant has no graph tools and must not emit a Fuentes/Sources line.

**S5 — Verified by the golden set.** After the change, the citation rate rises from the T2.3 baseline (5/16) while world-reading (facts, 14/16) holds.

## Tasks

| ID | Task | Specs | Route | Status | Commit |
|---|---|---|---|---|---|
| T1 | Add the per-language citation clause as the last instruction for real worlds | S1-S4 | inline | done | see L3 |
| T2 | Tests: es/en clause present for real worlds, absent for global, last before the author prompt | S2-S4 | inline | done | see L3 |
| T3 | Re-run the golden set live and record the citation rate vs 5/16 | S5 | inline | done (product-path baseline 15/16, citation 16/16; see L4) | — |

## Log

**L1 (Owner request, verbatim, 2026-11-25):** *"lo de la cita me parece bien importante, es algo similar a lo que pasa cuando le pides las referencias a la IA de donde sacó los datos que está explicando al usuario. Asi que en este caso me parece que tiene sentido hacer algo asi"*

**L2 (Owner decision, verbatim, 2026-11-25):** *"si, me gusta la A"* (format A: a `Fuentes:` footer).

**L3 (T1/T2 done, T3 blocked by the runner path, 2026-11-25):** added `_CITATION_GUIDANCE` (es `Fuentes:`, en `Sources:`) and appended it after `_RESPONSE_STYLE_GUIDANCE` for real worlds only (`_build_ai_ask_prompt`); the world-agnostic `ideas-global` context never receives it. Tests authored first (RED 4 failures) then GREEN: `test_assistant_citation.py` (4); focused prompt/assistant batch 71 passed / 8 skipped; global-context 6 passed.

- **Product-path probe (the real proof):** with a loopback local-dev session, `POST /api/Vibrantes/ai/ask/activity` for the Chaart-zones question answered correctly and ended with `Fuentes: `lore/politica-distribucion-y-territorios/chaart.md`` — format A, exact path, and it named the world. So the clause works on the path the Owner actually uses.
- **Discovery — the golden-set runner measures the wrong path:** `scripts/eval_assistant.py` talks to the gateway `/v1/runs` with the raw question, so it never runs `_build_ai_ask_prompt` (identity, tool guidance, graph context, style, citations). The T2.3 baseline (5/16) therefore measured the gateway's *default agent*, not the product assistant. Re-measuring the product-path citation rate requires pointing the runner at `/api/{mundo}/ai/ask/activity` (local-dev session + parse the SSE `answer` events) — a runner fix that is its own reviewed unit. T3 is blocked on that.

**L4 (T3 done — product-path baseline, 2026-11-25):** the golden-set runner now measures the product, not the raw gateway.

- `scripts/eval_assistant.py`: removed the gateway transport; added `open_local_session` (loopback `POST /api/auth/local-dev/session` cookie), `ask_product` (`POST /api/{mundo}/ai/ask/activity`), `consume_api_events` (cumulative `answer` → last; `activity.operation`/`path`; `terminal`), and a per-line deadline in `iter_sse` (also closes advisory R3-001). CLI: `--api` (default `http://127.0.0.1:8000`) and `--mundo` (exact app world name, default the slug); `--gateway`/`--key` removed.
- Tests updated: `test_eval_assistant.py` 20 passed (API event folding, cumulative answer, a fake-opener `ask_product` stream, and an HTTP 503 recorded as `http_503`, not a crash).
- **Product-path baseline: 15/16 pass, citation 16/16** (vs the raw-gateway 5/16). Every answer cited its ficha path. The one failure (`vibrantes-02-atherr-cuevas`) is a corpus-authoring issue: the question asks where the water Stal are, the answer named the Cuevas de Cristal and cited the ficha, but the case also required `Lumnar` (the Bosques) — over-specified; refine that case before the next baseline.
- Report kept local: `odd/evidence/assistant-golden/.local/report-2026-11-25-7d0b517-product.md` (gitignored: world canon).

**L5 (native review escalated, 2026-11-25):** the Owner granted the candidate consent; lineage `review-c14a7977c2567757`, target `sha256:3daa6af4…`, range `ab29b87..HEAD` (7 paths / 524 lines), lenses `review-risk` + `review-reliability`. `review-risk` admitted (`completed`). The reliability lens raised one severe finding, `R3-timeout-abort`, with `cause: unknown_causality`, so the lineage closed **escalated** — no approval receipt, no correction transition, "maintainer action is informational".

- Maintainer judgment (with the base visible to us): on the per-case deadline `iter_sse` raises `TimeoutError`; `ask_product` does not catch it, so it propagates to `evaluate_world`, which catches it per case and records an `error` verdict. The run survives; a timed-out case is reported as `error`, not a crash. That is the intended behavior of enforcing the documented `--timeout` (it also closes advisory R3-001); the old gateway `_bounded` stopped silently. Not a defect of this candidate.
- Follow-up (not fixed here; it would be a new candidate): catch `TimeoutError`/`URLError` in `ask_product` and return a typed `timeout`/`transport_error` status (like `http_503`) so the report is consistent and no raw exception string is echoed. Fold it into the next runner unit.
- The reviewed boundary does not advance; it stays at `ab29b87`. No receipt; delivery remains ordinary repository policy.

**L6 (runner hardening + case refine, 2026-11-25):** `ask_product` now catches `TimeoutError` (→ `timeout`) and `URLError`/`OSError` (→ `transport_error`), returning typed statuses like `http_503` instead of letting the deadline exception escape (addresses the escalated `R3-timeout-abort`). Tests: 22 passed (added `timeout` + `transport_error`). Refined `vibrantes-02-atherr-cuevas` (dropped the over-specified `Lumnar` fact; local digest `0f337afc0e8fc91a`). T2.4 closed: the golden-set command is in `docs/RELEASING.md`.
