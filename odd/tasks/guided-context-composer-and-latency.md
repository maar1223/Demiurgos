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

- [x] T1 feature document + mirror. Route: inline.
- [x] T2 composer + clamp + visible omission marker (S1/S2). Route: inline.
- [x] T3 adversarial property test (S3). Route: inline.
- [x] T4 background memory + distilled refresh (S4). Route: inline.
- [x] T5 guided continuations skip the gate (S5). Route: inline.
- [x] T6 `reasoning_effort` per service call (S6). Route: inline.
- [x] T7 volatile ids last (S7). Route: inline.
- [x] T8 suites + commit + publish `v0.4.7` (S8). Route: inline.

## Log

- **L1 (Owner decision, verbatim):** "hazlo segun tu recomendacion".
- **L2 (measured baseline):** guided turn = semantic gate p50 7.3 s + guided provider p50 8.7 s (up to 32 s) + memory extraction p50 9 s (max 32 s), plus a distill call of 8.4 s every 5 turns with a 1.16 MB prompt. The response is logged only after the memory extraction, so it blocks. 68% of generated tokens are reasoning.
- **L3 (the failure this prevents):** `known_state` = 4 000-char facts + 89-char plan = 4 090 > `context_budget` 4 000 → `invalid_input` 422 on every turn (v0.4.6 fixed the composition; this slice makes it impossible by construction).

## Evidence

- **T2–T3 (2026-11-08):** RED first (the composer did not exist; the old test showed the 4 090 overflow). `_compose_guided_request` + `_clamp_context_block` + the marker in `_guided_known_state`. Nine adversarial cases pass: empty, 1 MB field, 10 000 facts, non-ASCII, nested values — every bounded field fits and `validate()` is `None`.
- **T4:** `_schedule_background` / `_schedule_turn_memory` / `_schedule_distilled_refresh`; the distill digest caps each turn at 2 000 chars and the whole digest at 8 000.
- **T5:** `ai_ask_endpoint` returns through `_internal_guided_turn` before the gate for an authorized, revision-current continuation. Five tests that pinned the old "gate first on continuations" contract were updated; the REST `/guided/turn` route keeps the gate (no mounted client uses it).
- **T6:** `HermesActivityRequest.model_options` reached the gateway payload; curator and distillation send `reasoning_effort: none`, the gate sends `low`, the guided answer keeps the default. Unit-tested; the end-to-end effect is pending because the local stack was stopped during verification.
- **T7:** both prompts now place the volatile ids after `Author input`, and a test pins the order.
- **T8:** commit `1440fa6` (+ `8a5d2b4` for the guided markdown slice). BE 5085 passed / 26 skipped; FE 1764 passed; typecheck clean; manifest fresh. Tag `v0.4.7`; release run 42501541391 green on every job; `latest` = 0.4.7.
- **Known limitation:** when the context is trimmed the marker is neutral about ranking (insertion order); recency-first ordering and a token-based allocation remain the next step.
