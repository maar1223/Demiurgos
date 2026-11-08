# Guided context budget + a named failure reason

Objective: a guided turn can no longer fail because the context it composes exceeds the budget its own request validates, and the chat always names the reason instead of the generic blocked copy.
Branch: `master` (hotfix), tag `v0.4.6`. Delivery: hotfix PATCH; the Owner updates from Perfil → Actualizaciones.
Runners: `.venv/bin/python -m pytest src/tools/demiurgos-suite/wiki/tests/`; `cd frontend && npx vitest run`; `cd frontend && npm run typecheck`.

## Specs

- **S1 (the report).** L1 verbatim: "volvio a suceder y nuevamente me sigue sin decir por que pasa eso de forma especifica, nunca me dice el error, solo que no se puede completar la solicitud".
- **S2 (no self-inflicted 422).** Acceptance: the `known_state` a guided turn sends is composed (plan line + collected facts) inside `GUIDED_CONTEXT_BUDGET` and can never exceed `GuidedRequest.context_budget`, so `validate()` cannot reject the server's own input.
- **S3 (the reason is always visible).** Acceptance: every failed assistant turn names a specific, safe reason; a Demiurgos-owned error code with no dedicated sentence is shown verbatim in parentheses (never provider/gateway text). Deterministic causes (`invalid_input`, `internal`) do not offer a retry.
- **S4 (evidence + delivery).** RED before each rule; full backend and frontend suites; tag `v0.4.6`; the Owner retests the same Vibrantes session.

## Tasks

- [x] T1 diagnosis (log + live session measurements). Route: inline.
- [x] T2 `_guided_turn_known_state` shares one budget + `validate()` names the field (S2). Route: inline.
- [x] T3 specific failure copy + code fallback + retry split (S3). Route: inline.
- [x] T4 full suites + commit. Route: inline.
- [ ] T5 publish `v0.4.6` + Owner updates the app (S4). Route: inline.

## Log

- **L1 (Owner report, verbatim):** "volvio a suceder y nuevamente me sigue sin decir por que pasa eso de forma especifica, nunca me dice el error, solo que no se puede completar la solicitud".
- **L2 (root cause, 2026-11-08):** `demiurgos-api.log` → `WARNING guided turn failed: code=invalid_input retryable=False`, `POST /api/Vibrantes/ai/ask 422`. Live session `guided-f74775b2529e4fe4924ceaaa2a39a288` rev 16: 61 observations, `_guided_known_state(candidate, budget=4000)` = 4 000 chars, the plan line (89 chars) was prefixed AFTER that budget was applied → composed `known_state` = 4 090 > `context_budget` 4 000 → `GuidedRequest.validate()` returns `invalid_input` on every attempt. `world_context` measured 3 613 (inside budget). The v0.4.5 fix preserved demoted deltas in `observations`, which filled the 4 000-char fact budget and made this latent double-budget bug fire.
- **L3 (why the reason never appeared):** the frontend maps only `timeout`/`provider_unavailable`/`malformed_output` (and 502/503/504) to specific copy; `invalid_input` (422) fell through to `assistant.blocked`, the generic sentence. The server message never reached the chat.
- **L4 (scope note):** the uncommitted `assistant-response-style` T7 hunks in `guided_character_protocol.py` stay out of this hotfix; only the `validate()` hunk was staged.
