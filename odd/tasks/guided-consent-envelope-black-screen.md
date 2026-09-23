# Feature: guided-consent-envelope-black-screen

**Branch**: `fix/guided-consent-envelope-black-screen`
**Status**: in progress
**Artifact language**: English (technical artifact)

## Objective

Make the guided character save flow render instead of blanking the whole application, and make a future render-time crash recoverable instead of leaving an empty viewport.

## Problem

`POST /api/{mundo}/guided-character/consent/accept` returns a semantic decision envelope
(`api_server.py:2614-2618` -> `_open_guided_continuation` -> `_semantic_confirmation_continuation`, `api_server.py:6675-6699`):

```
{ state: "require_confirmation", action, response, request_id, attempts, fallback,
  guided, guided_explicitness, session_id,
  guided_session_id, guided_revision, guided_state: {...bare session...} }
```

The frontend declares and stores it as a bare `GuidedCharacterSession`:

- `frontend/src/api/guidedCharacter.ts:98-107` — `Promise<GuidedCharacterSession>`
- `frontend/src/hooks/useAIAssistantSessions.ts:525-532` — stores the raw result as `guided`

Then the sidebar dereferences a field that does not exist on the envelope:

- `frontend/src/components/organisms/AIAssistantSidebar.tsx:328-335` — `activeSession.guided.candidate.proposals`

`candidate` is `undefined` -> `TypeError` during render. There is **no error boundary anywhere in the app**
(`main.tsx:9-13` renders `<StrictMode><App /></StrictMode>` directly), so the throw unmounts the entire React
tree and `#root` goes empty: a fully black viewport with no navbar, rail or header. That is exactly the
reported screenshot.

Secondary symptoms of the same mismatch, which explain "the flow does not advance":

- `phase` is `undefined` -> the confirmation card (`AIAssistantSidebar.tsx:493-525`, checked at `:303`) never renders.
- `revision` is `undefined` (the real field is `guided_revision`) -> `requestGuidedProposal` / `requestGuidedReview`
  (`useAIAssistantSessions.ts:505-516, 550-558`) send a missing `base_revision` -> 422.

A second, independent crash path exists: sessions persisted in `localStorage` with an older shape that lacks
`candidate`. `loadSessions` (`useAIAssistantSessions.ts:108-115`) does an unchecked `JSON.parse`, and
`isGuidedSession` (`frontend/src/lib/semanticIntent.ts:48-55`) validates only `session_id` / `revision` / `phase`.
Such a session reproduces the identical crash even after the envelope is fixed.

## Why

Reported by the Author on 2026-09-20 (screenshot: full black viewport, no app chrome). Deferred by explicit
request to the following session. Root cause identified on 2026-09-21 and approved for fix.

## Scope

**In scope (approved package of 4 points):**

1. Normalize the consent envelope at the frontend boundary so `guided` is always a bare session.
2. Add defensive optional-chaining guards where the sidebar dereferences the guided session.
3. Sanitize persisted sessions that lack `candidate` during load.
4. Add a root error boundary so an uncaught render error degrades into a recoverable UI.

**Out of scope:**

- The backend envelope contract. It is intentional and already consumed correctly by the `/ai/ask` path
  through `mapSemanticDecision` (`frontend/src/lib/semanticIntent.ts:134,145,159`). Do NOT change the server.
- Removing the dead `GuidedCharacterPanel` / `useGuidedCharacter` pair. Noted as a follow-up, not part of this fix.
- Any redesign of the guided flow UX.

## Constraints

- Frontend only. No backend file may be modified.
- Reuse the existing `SemanticDecisionEnvelope` type (`frontend/src/api/types.ts:903-935`, `guided_state?: GuidedCharacterSession` at `:918`). Do not invent a parallel type.
- Normalize once, at the boundary. Do not scatter unwrapping logic through components.
- Keep the public behaviour of the happy path identical: after the fix the guided flow must reach the
  confirmation card and advance to review.

## Resolved configuration

- **TDD**: OFF. Source: testing-capabilities observation #506 (`Strict TDD Mode: disabled`). Do not run a RED/GREEN cycle.
- **Runner**: from `frontend/` — `npm test` (= `vitest run`) and `npm run typecheck` (= `tsc --noEmit`).
- **RDD**: off (decided by `clone_local`). No review lifecycle.
- **Verification depth**: writer self-verification + independent verifier. The automatic tier cannot be computed
  (the repo sits on a FUSE/NTFS mount whose fixed-owner projection makes RAR authority validation fail), so the
  change is treated as high risk for verification purposes.

## Route per task (ODD)

| Phase | Route | Trigger evidence |
| --- | --- | --- |
| Mapping | delegated (`explore`) | understanding required 4+ files |
| Implementation | delegated direct (one writer) | 2+ non-trivial files |
| Verification | writer self-check + independent verifier | RDD off, tier treated high |

## Tasks

- [x] **T1 — Unwrap the consent envelope at the boundary.**
  `acceptGuidedConsent` must return the envelope type; `resolveGuidedConsent` must store
  `envelope.guided_state ?? envelope` so `session.guided` is always a bare session. Reuse
  `SemanticDecisionEnvelope`. Fix the lying mock at `frontend/src/__tests__/useAIAssistantSessions.test.tsx:314`
  so it resolves the real envelope shape, and add a regression test asserting that a real envelope yields a
  usable `guided` session (with `candidate`, `phase`, `revision`).

- [x] **T2 — Guard the sidebar dereferences.**
  In `frontend/src/components/organisms/AIAssistantSidebar.tsx`, make `hasGuidedCandidate` (`:328-335`) and
  `confirmationPending` (`:303`) safe against a missing/partial `guided` object via optional chaining.
  A malformed session must render the normal chat UI, never throw.

- [x] **T3 — Sanitize persisted sessions on load.**
  Harden `loadSessions` / the guided-session validation (`useAIAssistantSessions.ts:108-115`,
  `frontend/src/lib/semanticIntent.ts:48-55`) so a stored session whose `guided` lacks `candidate` is dropped or
  normalized instead of crashing on mount. Add a test that seeds `localStorage` with the old shape and asserts no throw.

- [x] **T4 — Add a root error boundary.**
  New component (e.g. `frontend/src/components/ErrorBoundary.tsx`) implementing
  `getDerivedStateFromError` / `componentDidCatch`, wrapping `<App />` in `frontend/src/main.tsx:9-13`, rendering
  a recoverable fallback (message + reload/retry action) instead of an empty `#root`. Add tests covering the
  fallback render and the recovery action.

## Acceptance criteria

1. Given a real `/consent/accept` envelope, `session.guided` is a bare session with `candidate`, `phase` and `revision` populated.
2. A session whose `guided` lacks `candidate` renders the chat UI without throwing (no black screen).
3. A stored `localStorage` session in the old shape does not crash on mount.
4. An uncaught render error inside the app renders the error-boundary fallback, not an empty viewport.
5. `npm test` and `npm run typecheck` pass from `frontend/`.
6. No backend file is modified.

## Delivery

- Strategy: `single-pr` (small, single-concern fix). No chaining needed.
- Work units: one commit per task (T1..T4), Conventional Commits, tests alongside the behaviour.
- Push, PR and merge remain the Author's decision.

## Progress / Evidence

- 2026-09-21: root cause identified and persisted to Engram (`bugs/guided-character-save-black-screen`, observation #3485).
- Branch created from `master` at `f0e16e5`.
- Baseline before the fix (from `frontend/`): `npm run typecheck` exit 0; `npm test` 107 files / 1297 tests passed.
- Implementation complete. Work-unit commits:
  - T1 `4ac7d21` — `fix(guided): unwrap consent envelope into a bare guided session`
  - T2 `ba6eb22` — `fix(assistant): guard sidebar guided candidate dereference`
  - T3 `d7f29ec` — `fix(assistant): sanitize persisted guided sessions on load`
  - T4 — `fix(assistant): add a root error boundary` (this commit; it also lands this task update, so its own SHA is not self-referenced — see `git log`)
- Verification after all four units (from `frontend/`):
  - `npm test` -> 108 files / 1307 tests passed, exit 0
  - `npm run typecheck` -> exit 0
- Acceptance criteria: (1) real envelope unwraps to a bare session with candidate/phase/revision — T1 test; (2) candidate-less `guided` renders the chat UI — T2 test; (3) old-shape `localStorage` session mounts without crashing and keeps its conversation — T3 tests; (4) uncaught render error shows the boundary fallback with retry/reload — T4 tests; (5) both commands green; (6) no backend file modified.

## Next step

All four tasks are implemented and committed on `fix/guided-consent-envelope-black-screen`. Next: run the independent verifier against commits `4ac7d21`, `ba6eb22`, `d7f29ec` and the T4 boundary commit. Push/PR/merge remain the Author's decision.
