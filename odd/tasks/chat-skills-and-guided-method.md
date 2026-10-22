# Chat skills and guided-assistant method

Branch: `feat/skill-chat-guided-method` (based on `master`). Delivery: single work-unit chain, no PR.
Runners: `cd frontend && npm test -- --run` + `npm run typecheck`; `pytest src/tools/demiurgos-suite/wiki/tests/`.

## Specs

- **S1** "Que se entienda sin explicación qué skills están disponibles en el chat y cuál conduce el asistente guiado."
  The library shows chat availability per skill; the guided assistant shows its own method at start and while it runs.
- **S2** "Que no exista ningún botón que parezca encender/apagar una skill y en realidad haga otra cosa."
  No `Activar`/`Desactivar` control remains in the Taller (library or co-creation review). Controls must name their real effect.
- **S3** "Que el chat siga eligiendo solo la skill que necesita según la conversación, sin que yo tenga que activar nada."
  Routing and the companion (chat skills) mechanism stay unchanged. Only copy/placement changes.
- **S4** "Que no se pueda poner una skill que no crea personajes (Cronología, Sistemas) como método del asistente de personajes."
  Only the character-creation family is eligible: `narrative-character-creation`, `guided-character-v1`, and skills derived from `narrative-character-creation` (`parent_skill_id` chain). Enforced at session start and at every legacy activation route (guided flow).
- **S5** "Que mis skills propias se puedan añadir al chat de forma clara."
  `Añadir al chat` / `Quitar del chat` in the state panel; the co-creation review offers `Añadir al chat` instead of `Activar en`.
- **S6** "Que el asistente guiado elija su método al empezar (o use el de fábrica), en lugar de depender de un estado permanente escondido en la biblioteca."
  Method is chosen per session (consent card and direct session start), with `De fábrica` as the fallback. A legacy activation is honored only as the preselected default when eligible; an ineligible legacy activation falls back to factory for new sessions.
- **S7** "No romper las activaciones existentes."
  Stored activations are never deleted or rewritten; existing sessions keep their pinned snapshot.
- **S8** Out of scope: chat routing, the companions mechanism, foundational skill content, publishing/PRs, the closed Cronología feature.

Known facts (verbatim from the request):
- "Activar" no enciende el chat: fija el método que sigue el asistente guiado de personajes.
- El chat ya elige solo entre las skills disponibles; la activación no le hace falta.
- Solo puede haber un método activo para el asistente guiado.
- Hoy esa ranura acepta cualquier skill publicada, incluso las que no sirven para crear personajes.

## Tasks

- [x] T1 backend: eligibility helper + `GET /api/methodologies/guided-methods` (S4, S6). Route: inline. Evidence: `test_methodology_library.py` (95 passed), `test_per_flow_activation_api.py` guided-method tests.
- [x] T2 backend: per-session method at session start and consent accept; `methodology` echo in the public state (S6, S7). Route: inline. Evidence: `test_guided_character_api.py` (50 passed), `test_api_server.py` (592 passed with co-creation).
- [x] T3 backend: reject ineligible guided activations on `/api/methodologies/activate` and co-creation activate (S4, S2). Route: inline. Evidence: `ineligible_guided_method` tests; co-creation activation fixtures updated to the character family.
- [x] T4 frontend: library tree grouped by chat availability; activation chips/controls removed (S1, S2). Route: inline. Evidence: `tallerStates`, `TallerTree`, `axisCopyRegression`, `MethodologyLibrary` tests.
- [x] T5 frontend: state panel chat block + guided info (S1, S2, S5). Route: inline. Evidence: `MethodologyStatePanel` tests (no Activar/Desactivar; add/remove chat).
- [x] T6 frontend: guided consent method selector + method display in the guided surface (S1, S6). Route: inline. Evidence: `GuidedCharacterPanel`, `AIAssistantSidebar`, `guidedCharacter`, `useAIAssistantSessions` tests.
- [x] T7 frontend: co-creation review `Añadir al chat` replaces `Activar en` (S2, S5). Route: inline. Evidence: `CoCreationPanel` copy wired to the companions API; backend co-creation tests updated.
- [x] T8 copy, docs, full verification (S1–S8). Route: inline. Evidence: `tool-workshop.md` and `skill-runtime-consumption-contract.md` updated; FE 1466/1466 + typecheck clean; BE 3984 passed, 2 known order-dependent `test_gateway_hooks` failures that pass in isolation and do not touch this diff.

## Log

- **L1 (Owner request, verbatim):** "Objetivo: arreglar la activación de skills en el Taller de Herramientas. Trabajamos en Demiurgos. Quiero un cambio de producto, no un ciclo SDD: ve directo al cambio y, antes de tocar código, muéstrame la propuesta de qué cambia para el usuario y espera mi OK." (plus the six objectives, known facts and out-of-scope list reproduced in Specs above)
- **L2:** Proposal presented and approved verbatim: "me parece bien. Adelante".
- **L3 (implementation):** S2/S6 executed: activation removed from the Taller; chat availability is the library state; `Añadir/Quitar del chat` names the real effect; guided method chosen per session (`factory` token + eligible published method) with legacy activation only as an eligible default. S4 enforced by lineage at the session start and at both legacy activation routes. S7: stored activations untouched; existing sessions keep their pinned snapshot (the world-default change no longer invalidates them).
- **L4 (verification):** FE `npx vitest run` 1466/1466 passed; `npm run typecheck` clean. BE `pytest src/tools/demiurgos-suite/wiki/tests/` 3984 passed, 18 skipped; the two `test_gateway_hooks` failures are order-dependent `sys.modules` pollution (they pass in isolation and the diff does not touch that module).
- **L5 (risk):** `Risk: item 3` — the guarded shared activation/session contracts changed behaviour by request (guided slot now rejects ineligible methods; resume no longer invalidates on a world-default change). Covered by new/updated tests; independent verification requested.
- **L6 (verification correction batch):** Independent verifier found S1 unmet: the running guided surface (`AIAssistantSidebar`) showed the method only on the consent card, while the implementation lived in the unimported `GuidedCharacterPanel`. Fixed: the live chat now renders `Método: …` for factory and published methods whenever a guided session exists, and it fetches the eligible list for running sessions too. Also fixed the consent-selector race (an async default no longer overwrites a user choice) and closed the verifier's rollback advisory (`/api/methodologies/rollback` refuses to restore an ineligible guided method). Evidence: `AIAssistantSidebar.test.tsx` (33 passed, includes pin/factory method display), `test_per_flow_activation_api.py` (rollback guard), full FE 1468/1468, targeted BE 577 passed.
- **L7 (recheck):** Independent verifier rechecked only S1 and its direct regressions: S1 **PASS** (live `AIAssistantSidebar` renders `Método: …` for factory and published methods; 33 sidebar tests + 2 independent probes), backend focused 67 passed, frontend focused 69 passed, typecheck clean. Rollback advisory resolved (422, zero mutation, current slot unchanged). No new blocker. Remaining advisory: an imperative chat start (no consent card) uses the default method silently; the explicit selector lives on the consent card and the guided panel.
