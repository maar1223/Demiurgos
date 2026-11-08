# Legacy /ai/ask fallback leaks the semantic interpretation

Objective: never show the semantic gate's internal interpretation as the Assistant's answer. When the streaming activity path fails, the fallback must produce a real answer or the safe unavailable copy, never an English meta-note about what the author wants.
Status: backlog for the next release batch. Not implemented.
Runners: `.venv/bin/python -m pytest src/tools/demiurgos-suite/wiki/tests/ -q`; `cd frontend && npx vitest run`; `cd frontend && npm run typecheck`.

## Specs

- **S1 (leak).** `POST /api/{mundo}/ai/ask/activity` returned 503; the client fell back to `POST /api/{mundo}/ai/ask`; the semantic gate returned `state: allow` and the endpoint returned the gate's `response`, which the client maps to the answer text. That field is defined by `semantic_intent.py` as "a single concise sentence under 240 characters stating the interpretation — not an explanation of world lore". The visible result was the English note "Author wants to continue developing Ganic, the time-stopping character already in canon, rather than start a new guided entity."
  Acceptance: an `allow`/`clarify` decision never surfaces the gate's `response` as the assistant answer on any path.
- **S2 (fallback behavior).** When activity is unavailable, the fallback either (a) generates the real answer through the same `_build_ai_ask_prompt` contract (one bounded run), or (b) shows the safe unavailable copy with a retry. It never returns meta text, and it never pretends the turn succeeded.
  Acceptance: the fallback outcome is explicit and test-covered for `allow`, `clarify` and blocked states.
- **S3 (503 cause).** Determine why `/ai/ask/activity` returns 503. Candidates observed: the `guided_handoff` pre-flight (a guided id in the body) and `_activity_unavailable()` (unknown context or capability probe). Log the reason code on the frontend (`AssistantActivityUnavailable.reasonCode`) and on the server so the fallback decision is diagnosable.
  Acceptance: the 503 reason is observable in logs without reproducing, and the fallback branch is chosen from it.
- **S4 (evidence).** RED before each behavior rule; backend router/semantic tests; frontend `useAIAssistantSessions` fallback tests; one live turn with a forced activity failure.

## Tasks

- [ ] T1 server: `ai_ask_endpoint` never returns the gate interpretation as the answer; generate or fail safe (S1, S2).
- [ ] T2 503 reason observability + fallback branch (S3).
- [ ] T3 frontend fallback tests (S2).
- [ ] T4 full verification and a forced-failure live probe (S4).

## Log

- **L1 (Owner report, verbatim):** "y ahora que pasó?" — with a screenshot of the assistant bubble containing "Author wants to continue developing Ganic, the time-stopping character already in canon, rather than start a new guided entity."
- **L2 (evidence, 2026-11-07):** API log: `POST /api/Vibrantes/ai/ask/activity → 503`, then `ai_ask: semantic state=allow attempts=1`, then `POST /api/Vibrantes/ai/ask → 200`. The same log shows other activity 503s interleaved with 200s. `frontend/src/lib/semanticIntent.ts` maps `state: allow` to `{kind: "answer", text: response}`; `frontend/src/hooks/useAIAssistantSessions.ts` falls back to `legacyRequest()` (`askAssistant`) only when `AssistantActivityUnavailable` and the turn was not accepted.
- **L3 (code evidence):** `semantic_intent._build_prompt` defines `response` as the interpretation, not an answer. The activity path ignores it for the answer (it uses the streamed `answer` event); the legacy path has no generated answer and returns it.
