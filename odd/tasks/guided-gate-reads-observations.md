# Guided gate reads observations, keeps the demoted delta

Objective: stop the guided character flow from re-asking facts it already holds, and stop discarding the provider delta and its synthesis when the minimum-completeness gate has to ask one more question.
Branch: `fix/guided-gate-reads-observations`, based on `master`. Delivery: hotfix `v0.4.5` (patch), Owner updates from Perfil → Actualizaciones.
Runners: `.venv/bin/python -m pytest src/tools/demiurgos-suite/wiki/tests/`; `cd frontend && npx vitest run`.

## Specs

- **S1 (the report).** L1 verbatim: "porque si en el mensaje de arriba el agente hizo un resumen de todo lo que llevamos, aqui pregunta que como se llama el personaje? no lo entiendo".
  Acceptance: once a required anchor (identity, desire) is stored anywhere in the session — `accepted_canon`, `proposals` or `observations` — the gate treats it as known and never asks for it again.
- **S2 (no data loss).** Acceptance: when the gate demotes a provider `delta` to one focused question, the delta's fields are preserved in `candidate.observations` (internal, never a public proposal) and the provider's `synthesis` is preserved in the committed message. The author sees the summary above the question.
- **S3 (evidence).** RED before each behavior rule; one regression test per existing behavior touched (`incomplete delta → question`, `complete delta → proposal`, proposals stay empty on demotion). Full backend suite green.
- **S4 (delivery).** L2 verbatim: "si, adelante y acualiza la app de una vez para probarlo". Acceptance: hotfix tagged `v0.4.5`, published to the Recommended channel, and the installed app updated from Perfil → Actualizaciones so the Owner can retest the same Vibrantes session.

## Tasks

- [ ] T1 feature document + Engram mirror. Route: inline.
- [ ] T2 domain gate counts `observations` (S1). Route: inline.
- [ ] T3 `continue_session` preserves a demoted delta as observations + keeps the synthesis (S2). Route: inline.
- [ ] T4 semantic open path preserves a demoted delta as observations (S2). Route: inline.
- [ ] T5 full backend suite + commit (S3). Route: inline.
- [ ] T6 publish `v0.4.5` + Owner updates the app (S4). Route: inline.

## Log

- **L1 (Owner report, verbatim):** "porque si en el mensaje de arriba el agente hizo un resumen de todo lo que llevamos, aqui pregunta que como se llama el personaje? no lo entiendo"
- **L2 (Owner instruction, verbatim):** "si, adelante y acualiza la app de una vez para probarlo"
- **L3 (diagnosis, 2026-11-08):** live session `guided-f74775b2529e4fe4924ceaaa2a39a288` (Vibrantes, rev 14) in `~/.local/share/demiurgos/data/guided-sessions.sqlite3`: `accepted_canon={}`, `proposals={}`, `observations` with 40+ facts including `nombre: "Ganic (ya declarado por el autor; corregido: no volver a preguntar)"`. `_candidate_known_fields` (`guided_character_domain.py:83`) reads only canon + proposals + the turn delta, while the provider prompt sends every collected fact to `observations` (persisted at `guided_session_store.py:350`) and `_guided_known_state` feeds them back to the model — so the model summarises correctly while the gate believes nothing was collected. `continue_session` (`guided_character_protocol.py:591-613`) then replaces the delta with `next_required_question()` and drops both the delta and the synthesis.
- **L4 (scope note):** the uncommitted `assistant-response-style` T7 work stays out of this hotfix (stashed, restored after the release).
