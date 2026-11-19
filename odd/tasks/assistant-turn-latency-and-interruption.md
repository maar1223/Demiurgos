# Assistant turn latency and silent interruption

Branch: `feat/assistant-turn-latency`, based on `master` (`v0.11.1`).
Delivery: work-unit commits on the feature branch; no push/PR/release unless the Owner asks.
Runners: `.venv/bin/python -m pytest src/tools/demiurgos-suite/wiki/tests/`; `cd frontend && npx vitest run`; `cd frontend && npm run typecheck`.

## Specs

- **S1** The Owner report, verbatim: "2 [Image 2] aqui no me mostró nada y no entiendo por qué. Como contexto apagué la pc y volvi horas mas tarde a continuar con la conversacion".
  Acceptance: a turn whose activity stream ends **without** an `answer` event never renders the generic fail-closed copy (`assistant.blocked`). It renders a specific, localized, retryable copy and offers "Reintentar". The server logs exactly one WARNING for that close carrying: request id, run id, elapsed seconds, the terminal status, and whether any answer text was produced. Today the path is silent on both sides.
- **S2** The Owner question, verbatim: "lo que no entiendo es porque puede durar tanto. Eso me sorprende. Es el LLM que no responde con rapidez o que es lo que pasa?"
  Acceptance: the per-event silence ceiling is at least 120 s (it was 30.0 s, which is inside the normal first-token latency of a long session), and the stream keeps a separate bounded total budget so it can never hang forever. A stream closed by ceiling, cancellation, or provider interruption is distinguishable in the log from a policy block.
- **S3** The Owner authorization, verbatim: "arranca con los 2 frentes y veamos como se comporta luego el Asistente".
  Acceptance: for a turn with a real session, skill routing starts **concurrently** with the semantic gate instead of after it. It keeps its `ROUTING_AWAIT_TIMEOUT_SECONDS` cap, its fail-open timeout behaviour, and exactly one routing decision per turn (the close-time reuse of the same task stays).
- **S4** The Owner context, verbatim: "apagué la pc y volvi horas mas tarde".
  Acceptance: the entity graph index for the worlds served by the API is warmed in the background at startup, so the first assistant turn after a reboot does not pay `EntityGraphIndex.build`. A failed warm never blocks startup and falls back to the existing lazy build.
- **S5** Evidence: RED observed before each behavior rule; one regression test per existing behaviour the change touches (activity stream contract, semantic gate ordering, routing decision count); differential check of the assistant envelope shape (the SSE event sequence for a successful turn is byte-identical).
- **S6** Every touched contract in `docs/` reflects the change (`docs/architecture/demiurgos-platform.md` §7.1 for the assistant path), and `odd/tasks/assistant-failure-recovery.md` gains the new evidence entry so the older failure taxonomy stays coherent.

### Measurements this feature is based on (evidence, 2026-11-19)

`~/.demiurgos/hermes/logs/agent.log`, the single failed turn after the reboot:

```
18:44:36  gate attempt 1   in=7402  latency=12.1s
18:44:51  gate attempt 2   in=7402  latency=10.3s  cache=256/7402 (3%)
18:45:01  gate attempt 3   in=7402  latency=5.6s
18:45:07  skill routing    in=6663  latency=4.9s
18:45:13  answer run       history=58 messages
18:45:43  "Interrupt requested (hard): explicit stop requested"
          "Turn ended: reason=interrupted_during_api_call"
          the run's SSE had delivered 200 with 0 bytes
```

- The answer run's first API call never completed inside 30 s, so no token ever reached the stream.
- `ACTIVITY_EVENT_TIMEOUT_SECONDS = 30.0` is a per-event **silence** ceiling; measured answer runs of comparable size took `in=34176 -> 18.8s` and `in=50789 -> 27.6s`.
- 33 s of the 67 s turn were **serial overhead before the answer started**: gate attempts plus routing.
- Prompt cache is not a lever: two identical gate prompts 10 s apart reported `cache=256/7402 (3%)` and `512/7402 (7%)`. Prefix ordering cannot help when identical prefixes are not reused, so reordering `_build_ai_ask_prompt` was **rejected** on this evidence.

## Tasks

- [x] T1 infra: answer-run interruption observability (S1, server side). Route: inline. Files: `api_server.py`, `tests/test_api_server.py::TestAssistantTurnInterruption`. Evidence: `close_reason` + one WARNING per un-answered close with `request`/`run`/`reason`/`answer_seen`/`elapsed`; disconnect logs at INFO. Test `test_silence_ceiling_closes_the_stream_and_logs_the_close` (RED observed: no `ACTIVITY_STREAM_BUDGET_SECONDS`), asserts no `answer` event, the run cancelled, and the log line.
- [x] T2 client: honest copy + retry when a turn ends with no answer (S1, client side). Route: inline. Files: `frontend/src/hooks/useAIAssistantSessions.ts`, `frontend/src/i18n/messages.ts`, `frontend/src/__tests__/useAIAssistantSessions.test.tsx`, `frontend/src/__tests__/assistantActivity.test.ts`. Evidence: new catalogue key `assistant.failure.interrupted` (es/en); an authoritative `allow` with no answer and a missing/malformed decision both render a specific copy with `retryPrompt`; a real `blocked` envelope keeps the server copy and stays non-retryable. Two new hook tests (RED observed) + two updated tests that pinned the old opaque copy (their safety assertions are unchanged).
- [x] T3 server: silence ceiling 30 s -> 120 s plus a 300 s total budget (S2). Route: inline. Files: `api_server.py`, its tests. Evidence: `ACTIVITY_EVENT_TIMEOUT_SECONDS = 120.0` (measured first-token latencies up to 27.6 s), new `ACTIVITY_STREAM_BUDGET_SECONDS = 300.0`; a timeout shorter than the ceiling is reported as `budget_exceeded`, not `silence_timeout`. Test `test_total_budget_bounds_a_run_that_never_terminates`.
- [x] T4 latency: routing runs concurrently with the semantic gate (S3). Route: inline. Files: `api_server.py`, `tests/test_api_server.py`. Evidence: the routing task is created before `_semantic_gate` and awaited after it; `_abandon_route_task` cancels it on every short-circuit return (blocked, guided handoff, unavailable/missing adapter, start failure) so nothing leaks; the close-time reuse of the same task is intact. Test `test_routing_starts_before_the_semantic_gate_finishes` (RED observed: order was `gate_start, gate_end, route_start`).
- [x] T5 latency: warm the entity graph at startup (S4). Route: inline. Files: `api_server.py`, `tests/test_api_server.py`. Evidence: `_warm_graph_indices()` runs in a daemon thread from `_lifespan`; one failing world never stops the sweep and `_get_graph` stays the only contract. Test `test_graph_warm_builds_each_world_and_never_raises`.
- [x] T6 docs + full verification (S5, S6). Route: inline. Files: `docs/architecture/demiurgos-platform.md` §7.1, `odd/tasks/assistant-failure-recovery.md` (L11), `payload_manifest.json` (regenerated: `source_commit` + one evidence line moved). Evidence: BE `5246 passed, 26 skipped` then the 4 manifest-freshness failures fixed by regenerating the manifest (`12 passed`); FE `1821 passed`; `npm run typecheck` clean; `npm run build` clean; `python3 scripts/check_assistant_graph.py` -> `VERDICT: PASS (2 warning(s))`.

### Differential check (S5)

- A successful turn still emits exactly `semantic_decision` -> `activity*` -> `answer` -> `terminal`; no event was added, removed, or reordered (the fail-closed stream and `_semantic_decision_event` are untouched).
- `_build_ai_ask_prompt` is byte-identical: the prompt-order experiment was rejected (see the measurements section).
- The assistant `reason` taxonomy is unchanged; only the *un-answered* close stopped borrowing the blocked copy.
- Behavioural delta expected and intended: with routing running under the gate, a route that previously timed out at 5 s now completes, so the routed skill contract reaches the prompt more often. That changes prompt *content* (the whole point), never the envelope.

## Log

- **L1 (Owner request, verbatim):** "1 [Image 1] me gustaria que al lado de la ruedita que muestra que se está procesando la soicitud aparezca un cronometro que marque cuanto tipo está tardando la respuesta en procesarse. Me parece que eso seria bastante util de cara al usuario."
- **L2 (Owner report, verbatim):** "2 [Image 2] aqui no me mostró nada y no entiendo por qué. Como contexto apagué la pc y volvi horas mas tarde a continuar con la conversacion"
- **L3 (Owner question, verbatim):** "lo que no entiendo es porque puede durar tanto. Eso me sorprende. Es el LLM que no responde con rapidez o que es lo que pasa?"
- **L4 (Owner authorization, verbatim):** "arranca con los 2 frentes y veamos como se comporta luego el Asistente"
- **L5 (done before this document, small task):** L1 implemented and verified inline: `frontend/src/components/atoms/ElapsedTime.tsx` (live `m:ss`, wall-clock based, `role="timer"` not a live region) mounted beside the spinner in `AIAssistantSidebar.tsx`; 2 new tests (RED observed); FE 1819 passed; typecheck and build clean.
- **L6 (diagnosis, 2026-11-19):** the generic copy in L2 is produced by `useAIAssistantSessions.ts:792-806`, which calls `applyBlocked(semanticBlockedText)` whenever the semantic state is `allow` and no answer arrived, and also for any non-`allow`/`clarify` state. The server killed the run at exactly 30.0 s of silence (`ACTIVITY_EVENT_TIMEOUT_SECONDS`), `translator.finalize()` emitted `terminal: unknown` with no `answer`, and `finally` issued `POST /v1/runs/<id>/stop` — visible in `demiurgos-api.log` — which is why the gateway recorded a clean-EOF interruption mid tool call. Neither side logged the close.
