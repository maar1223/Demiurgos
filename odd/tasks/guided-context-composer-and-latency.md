# Guided context composer + service calls off the request path

Objective: size can never make a guided turn fail, and the bookkeeping calls (memory extraction, distillation) stop blocking the answer.
Branch: `master` (hotfix), tag `v0.4.7`. Delivery: PATCH; the Owner updates from Perfil → Actualizaciones.
Runners: `.venv/bin/python -m pytest src/tools/demiurgos-suite/wiki/tests/`; `cd frontend && npx vitest run`; `cd frontend && npm run typecheck`.

## Specs

- **S1 (size cannot fail a turn).** The server builds every guided request through ONE composer that clamps each bounded field to `GUIDED_CONTEXT_BUDGET`, so the request it builds can never fail its own `validate()` because of size. Context degrades fail-open (trimmed, marked); writes keep failing closed.
- **S2 (truncation is visible, never silent).** A trimmed fact list says how many facts were omitted (`… (+N facts omitted)`) instead of cutting mid-word.
- **S3 (no size failure is possible for ANY input).** A property test proves the invariant for an empty candidate, a 1M-character field, non-ASCII content and 10 000 observations: every validated field fits and `validate()` returns `None`.
- **S4 (bookkeeping never blocks the answer).** Memory extraction and the distilled refresh are scheduled as background tasks; the response is returned without awaiting them.
- **S5 (guided continuations skip the semantic gate).** An authenticated, revision-current guided turn goes straight to the guided provider: the gate's decision was discarded on that path (verified), so the extra run only added ~7 s.
- **S6 (service calls reason less).** The memory curator and the distilled refresh request `reasoning_effort: none`; the semantic gate requests `low`. The guided answer keeps the profile default so quality is unchanged.
- **S7 (cache-friendly prompt order).** Volatile ids (`request_id`, `session_id`) move to the END of the gate and guided prompts, so the stable prefix stays cacheable.
- **S8 (evidence + delivery).** RED before each rule; full backend and frontend suites; tag `v0.4.7`.

## Tasks

- [ ] T1 feature document + mirror. Route: inline.
- [ ] T2 composer + clamp + visible omission marker (S1/S2). Route: inline.
- [ ] T3 adversarial property test (S3). Route: inline.
- [ ] T4 background memory + distilled refresh (S4). Route: inline.
- [ ] T5 guided continuations skip the gate (S5). Route: inline.
- [ ] T6 `reasoning_effort` per service call (S6). Route: inline.
- [ ] T7 volatile ids last (S7). Route: inline.
- [ ] T8 suites + commit + publish `v0.4.7` (S8). Route: inline.

## Log

- **L1 (Owner decision, verbatim):** "hazlo segun tu recomendacion".
- **L2 (measured baseline):** guided turn = semantic gate p50 7.3 s + guided provider p50 8.7 s (up to 32 s) + memory extraction p50 9 s (max 32 s), plus a distill call of 8.4 s every 5 turns with a 1.16 MB prompt. The response is logged only after the memory extraction, so it blocks. 68% of generated tokens are reasoning.
- **L3 (the failure this prevents):** `known_state` = 4 000-char facts + 89-char plan = 4 090 > `context_budget` 4 000 → `invalid_input` 422 on every turn (v0.4.6 fixed the composition; this slice makes it impossible by construction).
