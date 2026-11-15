# Guided world exploration inside the field questionnaire

Objective: let the author explore the world from inside any field question without leaving the field: the answer is its own block, nothing is committed, and the questionnaire keeps its place.
Branch: `feat/guided-level-before-flow` (continues the guided series). Delivery: local build; publishing is the Owner's decision.
Runners: `.venv/bin/python -m pytest src/tools/demiurgos-suite/wiki/tests/`; `.venv/bin/python -m pytest tests/`.

## Specs

- **S1 (the requirement).** L1 verbatim: "ok, a lo que me refiero es que dentro de cada pregunta pueda hacer exploracion del mundo. NO pueden ser cosas opuestas, es necesario que todo esté integrado."
  Acceptance: while the field-by-field questionnaire is asking field *N*, an author turn that asks about the world is answered with the bounded world lore already supplied to the provider, and the next question still belongs to field *N*.
- **S2 (the answer does not fit in a synthesis).** Acceptance: the exploration answer travels in its own bounded envelope field (`answer`, server cap 2,000 chars, cut on a word boundary) and renders in the chat above the synthesis; the synthesis keeps its 3-sentence contract. Messages without `answer` render byte-identically to today.
- **S3 (exploring commits nothing).** Acceptance: an explore turn creates no proposal and does not move the questionnaire cursor, even when the provider also extracts character fields: the server drops the delta and any observation whose key maps to a questionnaire field of the resolved plan. World facts outside the plan are kept.
- **S4 (the earlier fixes stay).** Acceptance: `v0.4.5` (the completeness gate counts observations) and the 2026-11-15 fix (a value that only says "not defined yet" is not an answer) keep their behavior; the explore filter removes plan keys only on explore turns.
- **S5 (fail-safe).** Acceptance: `intent` is honored only when the outcome is QUESTION; a missing or unknown `intent`, or `explore` on a DELTA, behaves exactly as before. No synthetic question is invented to close an explore turn.
- **S6 (evidence).** RED before each rule; a differential check for legacy envelopes without `answer`/`intent`; full wiki suite and root `tests/` green.

## Tasks

- [x] T1 Feature document + Engram mirror. Route: inline.
- [x] T2 `field_for_probe()` maps a candidate key to its questionnaire field (probe-aware). Route: inline.
- [x] T3 Envelope `answer` + `intent` with validation and bounds (S2, S5). Route: inline.
- [x] T4 Explore normalization in `continue_session`: drop delta + plan observations (S3, S4). Route: inline.
- [x] T5 Render `answer` before synthesis and question (S2). Route: inline.
- [x] T6 Provider prompt: exploration instruction for the fields path. Route: inline.
- [x] T7 Full suites + documentation + commit. Route: inline.

## Log

- **L1 (Owner requirement, verbatim):** "ok, a lo que me refiero es que dentro de cada pregunta pueda hacer exploracion del mundo. NO pueden ser cosas opuestas, es necesario que todo esté integrado."
- **L2 (Owner decision, verbatim):** "si, adelante".
- **L3 (prior exchange, evidence):** the field plan and the lore are already integrated in practice — `world_context` is resolved on every turn for both paths (`_guided_world_context`), and the prompt says "Answer all questions... Use the bounded reference, world lore and known state below". What blocks a useful in-field exploration is (a) the synthesis contract (3 sentences / 350 chars requested, 700 hard), (b) observations and proposals moving the cursor without author acceptance, and (c) `fields` having no instruction for an exploration turn. My earlier claim that exploration belonged to the `explore` path only was wrong; this document corrects it.
- **L4 (scope boundary):** the creation path stays pinned per session (no mid-session path switch). Exploration is a turn type, not a mode.

## Evidence

- **T2 (RED → GREEN, 2026-11-15):** `test_field_for_probe_maps_aliases_to_the_questionnaire_field`
  failed with `ImportError: cannot import name 'field_for_probe'`, then passed.
  Aliases map through the field probes (`oficio` → `trabajo`, `Desire` → `deseo`);
  `mundo`, `nivel` and the empty key map to `None`.
- **T3–T5 (RED → GREEN):** six tests failed for the right reasons
  (`AttributeError: 'GuidedResponse' object has no attribute 'answer'`, the
  rendering assertion, and the two explore-turn scenarios), all green after the
  change. `test_explore_intent_on_a_delta_is_ignored` passed before and after: it
  pins the fail-safe.
- **T6 (RED → GREEN):** the fields prompt failed on
  `assert 'World exploration inside the questionnaire' in ...`; green after the
  instruction, and absent from the conversational path.
- **Legacy differential:** ten content shapes (question only, text only,
  synthesis only, synthesis+question, whitespace, delta-only, empty answer)
  render byte-identically before and after the `_guided_message_text` refactor —
  zero diffs.
- **Suites:** wiki `5169 passed / 26 skipped`; root `tests/` `34 passed`.
- **Exploration scenario (integration):** an explore QUESTION carrying
  `answer`, `synthesis`, `observations {deseo, mundo}` and `delta {nombre}`
  commits the answer and `mundo` only: no proposal, no canon beyond `nivel`, no
  questionnaire movement.

