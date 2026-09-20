# Assistant wizard UX: shared progress, 3 steps, platform name

**Feature id**: `assistant-wizard-ux`
**Branch**: `feat/profile-information-architecture-08-consistency`
**Status**: in progress
**Author decision**: proceed with the full restructure, in order, using sub-agents.

## Objective

The assistant configuration wizard stops feeling like a form and starts reading
like a sequence: one shared progress indicator with honest state, three steps
instead of five, a success state that does not demolish the wizard, and the
platform name the docs already decided.

## Problem (verified in code)

`AssistantSettingsPanel.tsx`:

- The "stepper" is a row of plain `Button`s (`:370-372`) — no numbers, no
  completion check, no connectors. The current step is distinguished only by a
  subtle variant change (`secondary` vs `ghost`).
- Future steps are clickable and answer with an ERROR (`goTo`, `:320-330`)
  instead of being disabled with a reason.
- The same precondition is enforced twice, in two different affordances: the
  step buttons error (`:321-328`) while "Siguiente" silently disables (`:382`).
- Nothing marks "already done": after validating, the Conexión step looks
  unchanged.
- Success replaces the ENTIRE wizard with a card (`saved ?`, `:338`), erasing
  the progress the user just completed.
- "Confirmación" is redundant: the probes already passed in "Capacidad".
- Step bodies are single-line JSX of ~1,500 chars each (`:375-379`).

`IdeaCapturePanel.tsx:487-542` already does it right: numbered circles with
`done`/`current`/`todo`, a check icon, painted connectors, labels and
`aria-current="step"`; a footer that explains blocked advancement; and a success
block rendered INSIDE the last step (`:988-1014`). Same task type, two
languages, in the same section — that is the inconsistency.

## Naming resolution (do not invent a new name)

The platform-wide visible name is ALREADY a closed decision:
`README.md:96`, `README.es.md:96`, `docs/architecture/demiurgos-platform.md:359`
(G15) and 10+ architecture docs all say **"Asistente de Demiurgos"**, and G15
adds that the runtime provider name never appears to the user.

So this is not a rename to a new concept: it is making the UI use the decided
name. `Asistente del Wiki` (`ProfilePage.tsx:1056`) is the only literal
occurrence in production copy, and it is the one that "falls short".

Target copy:

- Panel title: **"Asistente de Demiurgos"**
- Subtitle: platform-level, naming the consumers — Wiki, bot de Telegram, Skill
  Madre and the future workshops — so the role reads as shared infrastructure
  rather than a Wiki-only helper.

## Scope

### In scope
- New `frontend/src/components/molecules/WizardProgress.tsx` (named export, no
  barrel — matches `components/` conventions).
- `IdeaCapturePanel.tsx` migrated to it, behaviour-preserving.
- `AssistantSettingsPanel.tsx` restructured: 3 steps, honest `done` derived from
  real state, disabled-instead-of-error, non-destructive success, one
  subcomponent per step.
- Terminology sweep: `ProfilePage.tsx:1056-1058`, `ConfigurationCenter.tsx:77`,
  `Onboarding.tsx:33`.

### Explicitly deferred terminology (author decides)
`StatusOverviewHeader.tsx:38-44,94` ("Asistente activo" / "Asistente no
disponible" / strip label "Asistente"), `TabBar.tsx:9` (the chat sidebar),
`IdeasWorkshop.tsx:50` (source attribution), `semanticIntent.ts:16`,
`constants.ts:126`, and all `docs/**` + `README*.md`. These use "Asistente" as a
short-form STATUS or FEATURE label, not as the name of the configured thing.
Renaming them would mix status with identity and churn four test assertions for
no clarity gain. Reported to the author rather than swept.
- The affected tests, migrated (not weakened).

### Out of scope — MUST NOT be renamed (public/internal contracts)
- `id: "assistant"` (`ProfilePage.tsx:1054`), `connection-assistant-body`
  (`ConnectionsPanel.tsx:104-106`), asserted in 4 test files.
- Every `/api/profile/assistant/*` route and every `Assistant*` API type.
- The module path and named export `AssistantSettingsPanel` (five `vi.mock`
  factories depend on it).
- `CARD_DEFS` key `"assistant"` and `cardState`/`cardLabel` behaviour.
- `src/tools/demiurgos-suite/wiki/assistant_settings.py` and the backend
  contract.
- The save-path gates: `selectedModel && validation === "validated"` + both
  probes `passed`, `revision: status.revision`, and NO `unknown_ack`.

## Tasks

| ID | Task | Route |
|---|---|---|
| T1 | `WizardProgress` molecule + migrate `IdeaCapturePanel` (behaviour-preserving) | delegated (writer A) |
| T2 | `AssistantSettingsPanel` restructure + its tests | delegated (writer B) |
| T3 | Terminology sweep across the app + the affected tests | delegated (writer C) |
| T4 | Parent verification of the whole diff | parent |
| T5 | Independent adversarial verification | delegated (verifier) |

## Design decisions for T2

- **3 steps**: `Conexión` (provider + endpoint + key — one act), `Modelo`
  (discover / choose), `Pruebas` (text + vision + save).
- **Honest `done`**: Conexión done when `validation === "validated"`; Modelo done
  when `selectedModel` is set; Pruebas done when both probes passed. Derived from
  state, not from how far the user walked.
- **Disabled, not punished**: future steps are not selectable; the reason goes in
  the footer helper text (the idea-capture pattern). `goTo` stops setting errors.
- **Non-destructive success**: keep the progress indicator visible with every
  step `done` and render the confirmation as a block inside the last step,
  keeping `role="status"` / `aria-live="polite"` and both actions
  ("Cambiar configuración", "Volver al Taller de Mundos").
- **Primary-action budget**: the Conexiones section must keep AT MOST ONE primary
  action (`ProfilePage.emphasis.test.tsx` audits this). `Button` defaults to
  `primary`, so every new button must state its variant explicitly.
- **Keep `apiKeyValueRef` / `apiKeyInputRef`** alive across step mounts, or the
  connection payload is lost.
- **Keep the `aria-label` asserted at `AssistantSettingsPanel.test.tsx:324`**, or
  migrate that test deliberately.

## Acceptance criteria

- One progress component, used by BOTH wizards; the idea-capture rendering is
  visually unchanged.
- The assistant wizard shows 3 numbered steps with a check on completed ones and
  painted connectors; completed state is honest after reloading.
- No future step is clickable; blocked advancement is explained in the footer,
  never as an error.
- Success keeps the wizard visible and adds a confirmation block; `runtime_state`
  stays honest for all three values.
- The panel title is "Asistente de Demiurgos" and the subtitle names the
  consumers.
- No do-not-rename contract from the Out-of-scope list is touched.

## Checks

- `cd frontend && npm run typecheck`
- `cd frontend && npm test -- --run`
- `.venv/bin/python -m pytest src/tools/demiurgos-suite/wiki/tests/test_assistant_settings.py -q` (backend contract untouched — regression guard)

## Progress

- [x] Recon map produced (explore)
- [x] T1 Writer A — `WizardProgress` + `IdeaCapturePanel` migration. Parent-verified: exact class strings reproduced, 42 targeted tests, typecheck clean.
- [x] T2 Writer B — 3-step restructure, `states` prop, disabled-not-punished, non-destructive success, per-step components. Parent-verified: 3 steps, no `goTo` errors, zero primaries, `unknown_ack` absent, `revision` intact.
- [x] T3 Writer C — platform name applied. Parent-verified by grep + full suite.
- [x] T4 Parent verification — full suite **1292 tests / 107 files**, `tsc --noEmit` clean.
- [x] T5 Independent verification — `sound with nits`, nothing unsafe to ship.
  - **F-1 fixed** (real gap): `modelDone` was `selectedModel !== null`, but the GET
    seeds `selectedModel` from `model_metadata`, which the backend returns with an
    EMPTY id when nothing is configured — so "Modelo" read as done on a fresh
    profile before the user acted. Now requires `selectedModel.id !== ""`, with a
    regression test that was confirmed RED under the old condition.
  - **F-3 fixed**: the footer hint is now linked to the disabled "Siguiente" via
    `aria-describedby`, so a screen reader is told WHY advancement is blocked.
  - **F-2 resolved by scope**: `StatusOverviewHeader` was listed in the original
    In-scope line and deliberately deferred (see above); the document now says so
    instead of contradicting the implementation.
  - **F-4 / F-5 accepted as nits**: `aria-current="step"` still lands on step 3 in
    the saved view (visually intentional), and `blockedReasons.probes` remains a
    null table entry special-cased in the footer.

## Author decision pending

Nothing committed. The working tree also carries the earlier uncommitted fixes
(restart SIGPIPE, vision probe 422) and the offline-card removal.
