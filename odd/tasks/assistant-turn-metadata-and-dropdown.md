# Assistant turn metadata and the per-response dropdown

Branch: `feat/assistant-turn-metadata`, based on `master` (`a272958`, the Engram cutover merged).
Delivery: work-unit commits on the feature branch; no push/PR/release unless the Owner asks.
Runners: `cd frontend && npx vitest run`; `npm run typecheck`; `npm run build` (the API serves `frontend/dist`).

## Specs

- **S1** The Owner's request, verbatim: "hazlo tu y sigamos adelante con el segundo frente".
  The accepted plan is FRENTE 2 of the checkpoint L4 entry ("ok, haz una lista de todo lo que tenemos que hacer para comenzarlo en una nueva sesion. Guardalo en checkpoint y lo comenzamos con contexto fresco"): measure the duration and what the turn consulted, and show them per response.
- **S2** Measure in `useAIAssistantSessions.sendMessage`: `startedAt` when the turn starts and `durationMs` when it closes, on the same wall clock as the visible `ElapsedTime` timer. The metadata is attached to the assistant message the turn produced, **including failed turns** (the blocked copy is still a turn that took time and consulted sources).
- **S3** Extend `Message` with `turn?: { durationMs: number; items: AssistantActivityItem[]; sources: string[]; warnings: string[] }`. No migration: messages persisted before this change carry no `turn` and render nothing extra.
- **S4** Render: one collapsible block, closed by default, under each assistant bubble, summarising "Tardó 27 s · Consultó 3 fuentes"; inside, every operation with its status and the confirmed sources. Reuse `isSafeEvidencePath`, `activityOperationLabel`, `activityStatusLabel` and `safeActivityWarning` — no second sanitizer.
- **S5** The live `ActivityEvidence` panel renders only while `isSending`; once the answer arrives the information lives in the collapsed block. Turn `ACTIVITY_EVIDENCE_UI_ENABLED` on (`AIAssistantSidebar.tsx`).
- **S6** i18n `es`/`en` in `frontend/src/i18n/messages.ts` with parity (enforced by `catalogueGuard.test.ts`), and tests: the hook persists `durationMs` on a successful turn, on a failed turn, and leaves a legacy message without `turn` alone; the block renders collapsed with the summary and opens to show operations and sources; the live panel disappears once the turn closes.

## Tasks

- [x] T1 hook: measure the turn and persist `turn` on every assistant message (S2, S3). Route: inline. Files: `frontend/src/hooks/useAIAssistantSessions.ts`.
- [x] T2 sidebar: collapsed per-message block reusing the activity helpers (S4). Route: inline. Files: `frontend/src/components/organisms/AIAssistantSidebar.tsx`.
- [x] T3 sidebar: live panel only while sending, and enable the flag (S5). Route: inline. Files: `frontend/src/components/organisms/AIAssistantSidebar.tsx`.
- [x] T4 i18n + tests (S6). Route: inline. Files: `frontend/src/i18n/messages.ts`, `frontend/src/__tests__/useAIAssistantSessions.test.tsx`, `frontend/src/__tests__/AIAssistantSidebar.test.tsx`.
- [x] T5 verification: `npx vitest run`, `npm run typecheck`, `npm run build` before asking the Owner to look at the UI.

## Log

- **L1 (Owner request, verbatim):** "hazlo tu y sigamos adelante con el segundo frente" — the Owner authorized `git merge --ff-only` to `master` (done: `a272958`) and asked to start FRENTE 2. No release requested.
- **L2 (plan, 2026-11-20):** the turn metadata is accumulated in the `sendMessage` closure with the existing `applyAssistantActivityEvent` reducer, so the persisted items, sources and warnings use exactly the same rules as the live panel instead of a parallel implementation.
- **L3 (implementation + evidence, 2026-11-20):** T1 measures with `Date.now()` (the timer's clock) and accumulates `turnActivity` through `applyAssistantActivityEvent`, so the persisted items/sources/warnings use the same rules as the live panel; `turn` rides on every assistant message, including the interrupted/failed copy and the legacy-fallback answer. T2 renders `TurnDetails` inside the assistant bubble: closed by default, summary from three localized keys (0/1/many sources), operations and sources inside. T3 set `ACTIVITY_EVIDENCE_UI_ENABLED = true` and added `isSending` to the live panel's condition. T4 added 5 keys per language with parity. T5 evidence: RED observed by stashing the three source files and running the new tests (2 hook failures, 3 sidebar failures; the legacy-message test passes either way), then GREEN: focused 143 passed, full FE **1828 passed / 139 files**, `npm run typecheck` clean, `npm run build` produced `dist/assets/index-R8Czk1Bp.js` and `dist/index.html` references it with no `src` file newer than the bundle. One existing test changed contract (the live panel is now expected while sending).
