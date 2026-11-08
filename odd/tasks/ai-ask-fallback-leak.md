# Legacy /ai/ask fallback leaks the semantic interpretation

Objective: never show the semantic gate's internal interpretation as the Assistant's answer. When the streaming activity path fails, the fallback must produce a real answer or the safe unavailable copy, never an English meta-note about what the author wants.
Status: backlog for the next release batch. Not implemented.
Runners: `.venv/bin/python -m pytest src/tools/demiurgos-suite/wiki/tests/ -q`; `cd frontend && npx vitest run`; `cd frontend && npm run typecheck`.

## Specs

- **S1 (leak).** `POST /api/{mundo}/ai/ask/activity` returned 503; the client fell back to `POST /api/{mundo}/ai/ask`; the semantic gate returned `state: allow` and the endpoint returned the gate's `response`, which the client maps to the answer text. That field was defined by `semantic_intent.py` as "a single concise sentence stating the interpretation". The visible result was the English note "Author wants to continue developing Ganic, the time-stopping character already in canon, rather than start a new guided entity."
  Acceptance: `response` is the author-facing reply in the author's language, and any residual meta interpretation is replaced by the safe copy before it can reach the Author.
- **S2 (fallback behavior).** When activity is unavailable, the fallback either (a) generates the real answer through the same `_build_ai_ask_prompt` contract (one bounded run), or (b) shows the safe unavailable copy with a retry. It never returns meta text, and it never pretends the turn succeeded.
  Acceptance: the fallback outcome is explicit and test-covered for `allow`, `clarify` and blocked states.
- **S3 (503 cause).** Determine why `/ai/ask/activity` returns 503. Candidates observed: the `guided_handoff` pre-flight (a guided id in the body) and `_activity_unavailable()` (unknown context or capability probe). Log the reason code on the frontend (`AssistantActivityUnavailable.reasonCode`) and on the server so the fallback decision is diagnosable.
  Acceptance: the 503 reason is observable in logs without reproducing, and the fallback branch is chosen from it.
- **S4 (evidence).** RED before each behavior rule; backend router/semantic tests; frontend `useAIAssistantSessions` fallback tests; one live turn with a forced activity failure.

## Tasks

- [x] T1 server: the gate prompt asks for an author-facing reply, and `_author_facing_response` replaces a residual meta interpretation with the safe copy (S1, S2). Evidence: `semantic_intent._build_prompt`; `api_server._author_facing_response`; tests `test_provider_prompt_requests_a_user_facing_answer_not_a_meta_note`, `test_ai_ask_never_returns_a_meta_interpretation`, `test_ai_ask_keeps_a_normal_author_facing_answer`.
- [x] T2 503 reason observability (S3). Evidence: `ai_ask_activity: 503 guided_handoff` and `ai_ask_activity: 503 context unknown` log lines; the 503 body already carries `reason_code`, and the frontend stores it in `availabilityReason`.
- [x] T3 frontend fallback (S2). The fallback text is now server-owned; `semanticIntent` keeps mapping `allow` to `response` and the existing `useAIAssistantSessions` fallback tests stay green. No client code change was needed.
- [ ] T4 full verification and a forced-failure live probe (S4). Evidence: full backend suite 5059 passed / 20 skipped / 6 deselected (the live E2E class, environment-dependent) and frontend 1755 passed with a clean typecheck. The forced-failure live probe is pending: it needs a logged-in session against the installed build, and this batch is not published.

## Log

- **L1 (Owner report, verbatim):** "y ahora que pasó?" — with a screenshot of the assistant bubble containing "Author wants to continue developing Ganic, the time-stopping character already in canon, rather than start a new guided entity."
- **L2 (evidence, 2026-11-07):** API log: `POST /api/Vibrantes/ai/ask/activity → 503`, then `ai_ask: semantic state=allow attempts=1`, then `POST /api/Vibrantes/ai/ask → 200`. The same log shows other activity 503s interleaved with 200s. `frontend/src/lib/semanticIntent.ts` maps `state: allow` to `{kind: "answer", text: response}`; `frontend/src/hooks/useAIAssistantSessions.ts` falls back to `legacyRequest()` (`askAssistant`) only when `AssistantActivityUnavailable` and the turn was not accepted.
- **L3 (code evidence):** `semantic_intent._build_prompt` defines `response` as the interpretation, not an answer. The activity path ignores it for the answer (it uses the streamed `answer` event); the legacy path has no generated answer and returns it.
- **L4 (implementation evidence, 2026-11-07):** `semantic_intent._build_prompt` now asks for "the author-facing reply … in the same language as the author's input" and forbids "the author wants"/"the user asks"/"the assistant should". `api_server._author_facing_response` is a fail-safe that swaps a residual meta sentence for `unavailable_copy()` and logs a warning. Full BE suite green; FE 1755 passed; typecheck clean.
