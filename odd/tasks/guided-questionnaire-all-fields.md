# Guided questionnaire: ask every field, reflect incidental mentions

Branch: `feat/guided-questionnaire-all-fields`, based on `master` (`4f06694`). Delivery: work-unit commits; no push/PR unless the Owner asks.
Risk: item 1 (persisted session state gains `settled_fields`; legacy rows must resume without restarting the questionnaire).
Runners: `./.venv/bin/python -m pytest src/tools/demiurgos-suite/wiki/tests/`; `cd frontend && npx vitest run`; `cd frontend && npm run typecheck`.

## Specs

- **S1 (Owner decision, verbatim):** "en la formulario guiado todas las preguntas deberian hacerse". Every plan question (`Field.ask=True`) is asked, in order, even when the candidate already holds an incidental mention of that field. The only exceptions: a field the author explicitly skipped, and the field that only restates the already-settled narrative level (`rol_narrativo`, S7 of the previous feature).
- **S2 (Owner decision, verbatim):** "sin embargo si en una respuesta anterior se dió una idea parcial de ese campo entonces el asistente te tiene que decir algo tipo: Ahora venimos con el Deseo; en una respuesta anterior me dijiste que... por tanto crees que ese es su Deseo real? o es algo que lo complementa unicamente? si quieres podemos enriquecerlo." At a field with a prior incidental mention, the provider receives that fragment in the field brief and must reflect it, ask whether it is the real value or only something complementary, and offer to enrich it. A mention is never treated as settled.
- **S3 A field is settled only by its own turn:** the provider returns a `delta` that covers the current field (its key or a probe), or the author says "saltar"/"siguiente". An extraction made while answering a different field is preserved as an observation (no data loss) but does not settle its field.
- **S4 Settle + advance:** on the fields path, a delta that settles the current field advances the cursor and the same turn asks the next uncovered field. The settled field is never re-asked. The recorded turn decision names the field actually served, not the pre-turn one.
- **S5 The plan owns the questionnaire:** the platform minimum gate (identity + desire) never turns an in-plan delta into a public proposal mid-questionnaire. The proposal is assembled at plan completion, or through the existing explicit review action. If the plan completes while the minimum is still missing, one focused question asks the missing minimum.
- **S6 Persistence and legacy:** `settled_fields` survives restart (additive nullable column, legacy rows backfilled from the previous value-coverage rule) so a session written before this change never restarts from field 1. The schema version is not bumped: the migration is additive and reversible (an older build ignores the column and keeps writing its own data).
- **S7 Public progress:** `field_progress.covered` lists settled plan fields (plus the level-restating field); `complete` is true only when every asked field is settled or skipped.
- **S8 Tests:** cursor (mention does not advance, settlement does), two-turn settlement over the wire, no early proposal with name+desire present, proposal at plan completion, prior-note brief + provider prompt, migration/legacy backfill.

## Assumptions

- "Todas las preguntas" means the plan's asked fields; renderer-only labels (`ask=False`) remain non-questions.
- Optional plan fields (`optional=True`, still `ask=True`) are asked; skipping stays one field at a time.
- A mid-plan chat request to build the sheet is not honored during the questionnaire; the explicit review action stays hidden until the plan completes (existing UI rule). This is the Owner's "all questions" rule.

## Tasks

- [x] T1 Cursor + `settled_fields` state + store migration/backfill + settlement on commit (S3, S4, S6, S7). Route: inline. Commit `3c19eb2`. Tests: body cursor (mention never advances, settlement does, completion, legacy backfill), session settle/advance and no-early-proposal, store migration/backfill + restart. Evidence: `-k guided` 447 passed.
- [x] T2 Prior-mention brief + provider prompt + served turn decision (S2, S4, S5). Route: inline. Commit `5045d95`. Evidence: prompt free-path byte-identical (verifier sha `c6028a3d…`); 85 focused tests passed.
- [x] T3 Docs §10.9 + full backend/frontend verification (S8). Route: inline + independent verifier (Risk item 1). Commit `d6678a5` (verifier correction batch). Evidence: full backend 5074 passed / 11 skipped (CI-ignored e2e/installer/launcher files excluded); frontend 1830 passed. Verifier: S1-S4/S6-S8 met; S5 blocker (skip completing the plan left the minimum unasked) fixed and rechecked; S3 placeholder-delta advisory fixed and rechecked; no regressions.

## Post-verification follow-ups (non-blocking)

- The completed-plan minimum guard checks `delta` but not the same turn's `observations`. A provider QUESTION that carries the missing minimum only in observations would still ask it once more; then the observation is stored and the next turn is complete. Defensible under S2 (a mention is never settled); UX-only.
- Assistant-memory capture records each demoted questionnaire turn as a `proposal` fact (`api_server.py` memory capture). Non-canon and pre-existing; volume only.

## Log

- **L1 (Owner, verbatim):** "revisa que pasó en la ultima conversacion del asistente, me preguntó el nombre 2 veces cuando fui muy claro en la respuesta anterior"
- **L2 (diagnosis evidence, 2026-11-21):** session `guided-9b7ed7cd4d2f4d3ab18c2ef768073eae` (Vibrantes, Hesia). Provider returned `outcome: "delta"` with `delta: {nombre: "Hesia Viltri"}` (Hermes `state.db` message 5004). The global minimum gate demoted it on the fields path and re-served `request.field_progress`, so the "Nombre." question repeated (`guided_character_protocol.py:890-921`). Existing regression test only covered the free path (`tests/test_guided_session.py:179`).
- **L3 (deeper analysis):** the fields path and the free-path gate are two authorities; `delta` was overloaded ("field settled" vs "premature proposal"). With name+desire present, the same gate would emit a PROPOSAL at Deseo (field 27/36), abandoning the questionnaire (no completion guard).
- **L4 (Owner decision, verbatim):** "si, me gusta como lo planteas"
- **L5 (Owner decision, verbatim):** "lo que creo que es en la formulario guiado todas las preguntas deberian hacerse, sin embargo si en una respuesta anterior se dió una idea parcial de ese campo entonces el asistente te tiene que decir algo tipo: Ahora venimos con el Deseo; en una respuesta anterior me dijiste que... por tanto crees que ese es su Deseo real? o es algo que lo complementa unicamente? si quieres podemos enriquecerlo. O algo por el estilo"
- **L6 (independent verifier, 2026-11-21):** first pass: S1-S4/S6-S8 met, S5 NOT met (skipping the last plan field completed the plan with the minimum missing and a QUESTION response left it unasked), plus an S3 advisory (empty/placeholder/`null` deltas settled). Correction batch `d6678a5`: post-branch guard asks `next_required_question` when the plan is complete on a QUESTION turn, and `_delta_value_settles` rejects `None`/blank/non-answer placeholders. Recheck: blocker fixed (QUESTION and DELTA shapes), advisory fixed, no regressions; discriminator probe at `5045d95` reproduced both as RED.
