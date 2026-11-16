# Guided creation: level question before the flow, and choice cards that dismiss on click

Feature: guided-character-creation | Branch: `feat/guided-level-before-flow` | Delivery: `ask-on-risk` | Runner: `pytest src/tools/demiurgos-suite/wiki/tests/` (BE), `npx vitest run` (FE)

## Specs

- **S1 (Owner, verbatim):** "es normal que al dar click en alguna de las 2 opciones no se borre la ventana de los botones sino hasta que aparezca la respuesta del agente?"
  The server-owned choice card must leave the screen the moment the author chooses; the spinner is the progress cue, and the card returns only if the turn fails.
- **S2 (Owner, verbatim):** "tiene sentido que la pregunta del nivel de profundidad del personaje se pregunte al mismo tiempo que el nombre? eso facilmente va a confundir al flujo. Eso del nivel deberia estar antes de el flujo pero igualmente con la funcion de la ventana de UI. Al menos es como me lo imagino. Y eso aplica tanto para el 40/60 como para la ficha paso a paso"
- **S3:** The narrative level is a server-owned turn asked after the creation path and before any creative or field question, for both `explore` and `fields`. It renders as a `GuidedChoiceCard` with three options: 1º principal, 2º secundario, 3º relleno.
- **S4:** The chosen level is recorded on the session candidate (`accepted_canon["nivel"]`) so `resolve_candidate_nivel` drives the field plan; subsequent provider turns receive it in the known state and never re-ask it.
- **S5:** Sessions already in flight (a provider exchange already finished) are never interrupted by the level card; the card only appears before the first provider run.
- **S6:** The server-owned question text (path or level) is never duplicated as a chat bubble: the card is the only asker, and the text is not persisted into the chat transcript.

## Tasks

- [x] T1 Server: level turn after path (S2, S3, S4, S5) — route: inline — commit: `1fddfcd`. Evidence: `test_level_choice_reads_numbers_and_labels`, `test_level_question_follows_the_path_and_precedes_the_provider`, `test_finished_exchange_is_never_interrupted_by_the_level_question`; RED observed by stashing the three source files (KeyError `pending_kind`), then GREEN.
- [x] T2 Frontend: level card, immediate dismiss, no duplicated question bubble (S1, S3, S6) — route: inline — commit: `96bb0f3`. Evidence: sidebar + panel + hook tests; RED observed by stashing the frontend source files.
- [x] T3 Docs: guided creation sections 10.8/10.9 (S2, S3) — route: inline — commit: next docs commit.

## Log

- **L1 (Owner, verbatim):** "es normal que al dar click en alguna de las 2 opciones no se borre la ventana de los botones sino hasta que aparezca la respuesta del agente? ah y otra cosa, tiene sentido que la pregunta del nivel de profundidad del personaje se pregunte al mismo tiempo que el nombre? eso facilmente va a confundir al flujo. Eso del nivel deberia estar antes de el flujo pero igualmente con la funcion de la ventana de UI. Al menos es como me lo imagino. Y eso aplica tanto para el 40/60 como para la ficha paso a paso"
- **L2 (diagnosis, 2026-11-14):** `_guided_continue` asks the path as a server-owned turn but never asks the level; the provider asked it mid-flow, so the `fields` path shows "Campo 1 de 36 — Nombre" while the assistant asks the level. The path card is rendered while `isSending`, so it lingers until the server answers, and the question text is stored in the chat transcript, so it re-appears once a user message follows it.
- **L3 (design):** order is path → level → flow; the level is written into `accepted_canon["nivel"]` (no schema change; `_META_KEYS` already excludes it from the rendered extras); `pending_kind` is derived in `_guided_public_state` by comparing `pending_question` to the server-owned copies, so no new persisted column is needed.
- **L4 (implementation evidence, 2026-11-14):** the level turn only parses an answer when `pending_question` is the level copy — otherwise the path answer "2" is also a valid level token and was consumed as `2º`. `has_finished_exchange` could not be used for S5 because the committed path/level questions look like provider questions; a local `_has_provider_exchange` excludes them by text. The frontend hides the field cursor while `pending_kind === "level"` and both choice cards while `isSending`.
- **L5 (verification, 2026-11-14):** BE `pytest src/tools/demiurgos-suite/wiki/tests/` → 5148 passed, 26 skipped (+ 62 guided API tests). FE `npx vitest run` → 1785 passed. `tsc --noEmit` clean. `npm run build` OK.
- **L6 (environmental note):** running `pytest src/tools` from the repo root collects `src/tools/web-config-ui/tests` and fails on a `backup` module-name collision (`ALLOWED_COMMANDS`); pre-existing, unrelated to this change; CI runs the wiki suite path directly.
