# Guided turn directive: one decision per turn, recorded

Objective: stop the guided panel and the guided flow from disagreeing with each other — the class behind "the card says Apodo while the bubble asks Deseo".
Branch: `master` (next slice). Delivery: local build; publishing is the Owner's decision.
Runners: `.venv/bin/python -m pytest src/tools/demiurgos-suite/wiki/tests/`; `cd frontend && npx vitest run`.

## Specs

- **S1 (the report).** L1 verbatim: "mira esto, tiene sentido que me pregunte por el apodo cuando en la burbuja me esté preguntando por el Deseo?" / "me gustaria que hagas un diagnostico un poco mas profundo y le des unas vueltas a como hacer cambios para que no se vuelva a presentar el mismo error de maneras distintas mas adelante, ya que se habia presentado algo casi igual hace rato y pensé que estaba solucionado pero ahi sigue vivo".
  Acceptance: for any committed question turn, the bubble, the field card, the stored pending question and the next turn's field brief are the same recorded decision — not four independent recomputations.
- **S2 (recorded, not derived).** Every assistant question turn persists a `TurnDecision` (kind, question text, field key/label, field-progress snapshot, source, revision). The public state renders `pending_question`, `field_progress` and the card from that record. Legacy sessions without a record keep today's derivation until their next turn writes one.
- **S3 (one question authority per path).** On the `fields` path the plan cursor decides the next field; the minimum-anchor gate no longer chooses a question there. The gate keeps `candidate_minimum_complete` (finish/review eligibility) and the conversational path.
- **S4 (the provider cannot choose the subject).** On `fields`, the provider echoes the field key it served. A missing or different echo keeps the turn's extraction but replaces the question text with the deterministic server fallback derived from the field (`label` + `hint` + `examples`), and records the drift. The provider still owns the synthesis and the exploration answer.
- **S5 (one visible progress per path).** `fields` renders only `field_progress`; `explore` renders only `detail_progress`. The 6-slot plan is never rendered on the fields path and vice versa.
- **S6 (the pin is visible).** The panel shows the methodology version pinned by the session (`Método: Creación de Personajes v1.2`), not just its name.
- **S7 (a settled level is not asked twice).** Once `accepted_canon["nivel"]` holds a level, the field that only restates it (`rol_narrativo` on the 2º plan) is not asked again.
- **S8 (mismatches are loud, not silent).** Building the public state compares the rendered question and progress against the record; a divergence logs one bounded, redacted warning (no path, no prompt) instead of serving the lie silently.
- **S9 (invariants, not just behaviours).** A matrix of scripted turn sequences (fake provider) asserts the equalities of S2/S3/S4/S5 plus the pin rules; the frontend pins S5/S6. RED before each rule; full suites green.

## The class this closes

Six shipped symptoms, one cause: two things that should be one value are recomputed by different consumers at different times, and nothing compares them.

| # | Symptom | Fix | Where |
|---|---|---|---|
| 1 | Summarised everything, then asked the name | Gate reads `observations` | `3ab2b22` v0.4.5 |
| 2 | Cursor skipped fields ("sin definir" counted) | Non-answer predicate | `618a86b` |
| 3 | Panel kept a stale handle after a server change | Revalidate on mount | `438eea6` |
| 4 | Card says Apodo, bubble asks Deseo | **this document** | — |
| 5 | Level settled, "Rol narrativo" asked again | S7 | — |
| 6 | Activated 1.4, open session stays on 1.2, invisible | S6 | — |

Fixes 1 and 2 are inverses: one made `observations` count, the next had to stop it. When a fix undoes its predecessor, the shared definition is the defect — not the last patch.

## Authorities to retire (the actionable core)

**"What to ask / what to show" — five voices today:**

| Voice | Decides | Fate |
|---|---|---|
| `current_field()` | next field, pre-turn | Stays: it is the cursor. Its *snapshot* becomes the record. |
| `candidate_minimum_complete` + `next_required_question()` | anchor question | Questions retired on `fields`; completeness stays |
| provider reading the methodology | can ask an anchor out of order | Echo + fallback (S4), no subject choice |
| `pending_kind` | server-owned path/level cards | Stays, becomes `TurnDecision.kind` |
| `visible_proposal_key()` | proposal card | Stays for `explore`; not rendered in `fields` |

**"How far along" — three definitions:** `field_progress` (36/21/5, counts observations), `detail_progress` (6 slots, accepted canon only), and the gate boolean. S5 makes exactly one visible per path; the other two remain internal.

**"Which methodology applies" — five notions:** session pin, library published, world activation, payload seed, data-root seed copy. S6 makes the *applied* one visible; the seed reconcile (`ba4e6d8`) already aligned the last two.

## Design

### TurnDecision

```python
@dataclass(frozen=True)
class TurnDecision:
    kind: Literal["path", "level", "field", "gate", "proposal", "review", "complete"]
    question: str                 # the exact text the author sees
    field_key: str | None         # plan field this turn is anchored to
    field_label: str | None
    field_progress: dict | None   # snapshot at decision time
    source: Literal["server", "provider"]
    revision: int                 # the revision this decision belongs to
    directiva_version: int = 1
```

Stored on `SessionState` (`turn_decision`) and in a new column
`turn_decision_json TEXT NOT NULL DEFAULT ''`. Written by `commit` when the
response is a QUESTION; cleared/overwritten by the next question turn. Delta and
error turns leave it untouched.

Readers (and only these):
- `_guided_public_state` → `pending_question`, `pending_kind`, `field_progress`, `pending_review`;
- `_guided_continue` → `field_context` for the next turn (from the record's
  field key, falling back to the cursor only when the record is a non-field kind);
- the panel card.

### Sequencing rule

1. Turn starts: the server computes the directive (path/level/field/gate/complete) **once**.
2. The provider is invoked with that directive (it already receives `field_context`; it now also receives `field_key`).
3. The response is admitted; on `fields` the echo is checked (S4).
4. The turn is committed **with** the directive record — the text stored is the text served (provider's or fallback).
5. The public state renders the record. Nobody recomputes the view she just recorded.

The cursor itself keeps reading the candidate (observations still count), so
v0.4.5's "never re-ask what we hold" stays intact. What changes is that the
*displayed* field is the decided one, which removes the systematic off-by-one:
today every turn that extracts a value for the field it just asked moves the
cursor one step ahead of its own question.

### Fallback question (S4)

Deterministic, derived from the plan field:

```
"{label}. {hint} Ejemplos: {ex1} / {ex2}."   # hint/examples omitted when empty
```

Copy lives beside `_field_brief` and follows the conversation language. It is a
last resort: it only replaces the provider's question when the echo is missing
or wrong, and the drift is counted.

### Consistency check (S8)

`_guided_public_state` asserts, when a record exists:
`payload.pending_question == record.question` and, for `kind == "field"`,
`payload.field_progress == record.field_progress`. A divergence logs
`guided_turn_directive_mismatch` with the record kind and revision only —
bounded and redacted, never the prompt, never a path.

## Invariant matrix (S9)

Each row is a scripted sequence against a fake provider; every turn asserts the
listed equalities.

| # | Sequence | Asserts |
|---|---|---|
| M1 | fields: three answered fields | bubble == record.question; card == record.field_progress |
| M2 | fields: one skip | skip moves the cursor; the new record is the next field; card == record |
| M3 | fields: provider asks the wrong field | extraction kept; question replaced by the fallback; drift logged; card == record |
| M4 | fields: world exploration turn | no proposal, cursor unmoved, card unchanged, answer rendered |
| M5 | fields: level settled before the plan | `rol_narrativo` never asked (S7) |
| M6 | explore: proposals accumulate | only `detail_progress` renders; no field card |
| M7 | legacy session without a record | derivation fallback identical to today, then the next turn writes a record |
| M8 | activate a new methodology version | an open session keeps its pin and the panel shows that version |

## Tasks

- [x] T1 This document + Engram mirror. Route: inline.
- [x] T2 `TurnDecision` + column + migration; `commit` writes it (S2). Route: inline.
- [x] T3 `_guided_public_state` renders the record; legacy fallback (S2, S8). Route: inline.
- [x] T4 `fields` question authority: cursor decides, gate retires from questions (S3). Route: inline.
- [x] T5 Provider echo `field_key` + fallback question + drift log (S4). Route: inline.
- [x] T6 One visible progress per path (S5), frontend. Route: inline.
- [x] T7 Pin visible in the panel (S6), frontend. Route: inline.
- [x] T8 `rol_narrativo` not asked once the level is settled (S7). Route: inline.
- [x] T9 Invariant matrix (S9) + full suites + evidence. Route: inline.

## Log

- **L1 (Owner report, verbatim):** "mira esto, tiene sentido que me pregunte por el apodo cuando en la burbuja me esté preguntando por el Deseo?"
- **L2 (Owner instruction, verbatim):** "me gustaria que hagas un diagnostico un poco mas profundo y le des unas vueltas a como hacer cambios para que no se vuelva a presentar el mismo error de maneras distintas mas adelante, ya que se habia presentado algo casi igual hace rato y pensé que estaba solucionado pero ahi sigue vivo".
- **L3 (Owner choice, verbatim):** "si, vamos con B".
- **L4 (live evidence, 2026-11-15):** session `guided-d655bb67c15d4bf2bb8065b07cc2dcfd` rev 3, path `fields`, level 1º: `accepted_canon={nivel}`, `observations={nombre, nivel, vinculo}`, last question "¿Cuál es el deseo que define a este personaje?" while the card showed "Campo 2 de 36 — Apodo". Pre-turn cursor was Nombre (1 of 36); the same turn extracted the name, so the post-turn cursor became Apodo. The model also drifted: told Nombre, it asked Deseo because the pinned methodology says to ask a missing minimum anchor (identity + desire) and that rule outranked the field order.
- **L5 (scope boundary):** this document does not redesign the field plan, the 6-slot explore plan, or the methodology. It records decisions and retires duplicate authorities. Coverage semantics stay as they are.

## Evidence

- **T2–T5 (RED → GREEN):** five directive tests failed for the right reason
  (`'GuidedResponse' object has no attribute 'field_key'` / missing
  `turn_decision` / `KeyError: 'field_progress'`), then passed:
  record+render, drift→fallback with the extraction kept, missing echo, a free
  turn with no field, and the legacy fallback. A missing `observations` carry in
  the fallback reconstruction was caught by the drift test and fixed (drifting
  must never cost the author a fact).
- **T8 (RED → GREEN):** `test_settled_level_is_not_asked_again_as_rol_narrativo`
  now lands on Deseo, and the placeholder-cursor test was re-anchored on the 1º
  plan so it no longer depends on S7.
- **T5 prompt (RED → GREEN):** the fields prompt carries the key to echo
  (`'apodo'`) and the "may not change the subject" sentence.
- **T6/T7 frontend:** the six-slot progress does not render on `fields`, and the
  method line now reads `Método: narrative-character-creation v1.2`.
- **T3 rule change pinned by an existing test:** choosing the path no longer
  serves a field card while the level card is pending (`pending_kind: "level"`,
  no `field_progress`) — the two cards never stack.
- **Suites:** wiki `5181 passed / 26 skipped`; root `tests/` 34 passed;
  frontend `1808 passed`; `tsc --noEmit` clean.
- **Manifest:** `payload_manifest.json` regenerated (the new imports appear in
  `runtime_import_evidence`); `--check` fresh.
- **Matrix status:** M1, M3, M4, M7 covered at the backend seam; M2 by the
  existing skip test; M5 by the body test; M6 and the display half of M8 by the
  frontend tests. The pin-immutability half of M8 is pre-existing behaviour
  (snapshot pinned at creation), not re-tested here.
