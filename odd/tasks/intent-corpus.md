# Intent corpus: synthetic worldbuilder profiles

Branch: `feat/intent-corpus`, based on `master` (`b1170c8`). Delivery: work-unit commits; no push/PR unless the Owner asks.
Runners: `.venv/bin/python -m pytest src/tools/demiurgos-suite/wiki/tests/`; opt-in live eval: `DEMIURGOS_INTENT_EVAL=1` (never in default CI).

Corpus location: `src/tools/demiurgos-suite/wiki/tests/fixtures/intent-corpus/`. Run reports: `odd/evidence/intent-corpus/`.

## Specs

- **S1 (Owner request, verbatim):** "todo eso son interacciones mias. Lo que creo que si podemos hacer es ejemplos sinteticos de interacciones. al menos 5 perfiles de worldbuilders con tonos y caracteres distintos que quieran crear tipos de ficcion diferentes. Con eso si que tendriamos patrones de comportamiento mas solidos para crear algo que sea robusto y que se pueda adaptar a los tiposn de usuario que Demiurgos se encontrará mas adelante". At least five synthetic profiles, each with a distinct genre, tone and character. Their utterances are **test data**, never runtime input.
- **S2 (Owner question, verbatim):** "con 5 te parece bien? o metemos 5 mas?" **Decision:** wave 1 is exactly 5. Wave 2 targets 10 and is selected **from the first baseline**, never in advance: the new profile attacks the class with the highest false-open rate. Entry rule for a new profile: (a) it introduces an axis the current five do not cover, or (b) its genre family has vocabulary absent from the method declarations, and (c) the case cannot be covered by adding a turn to an existing profile.
- **S3 (Owner requirement, verbatim):** "esas simulaciones donde quedarán guardadas? puedo ver esas conversaciones luego en algun lugar a ver como las plantearon los diferentes perfiles? será demasiado interesante poder ver como se desembolvieron esos usuarios hipoteticos". Two readable artifacts, both in-repo: (a) the authored corpus as Markdown, one file per conversation, browsable and diffable; (b) a run report per milestone with expected vs actual per turn, committed under `odd/evidence/intent-corpus/<date>-<model>.md`. The report is evidence for one prompt/provider version, never a golden file.
- **S4 Closed taxonomy.** The opening decision is one of exactly five classes. Only the three opening classes may start anything; `answer` and `unknown` may never open.

  | Class | May open? | Legal next transition |
  |---|---|---|
  | `answer` | no | reply (an offer may be appended **after** the reply) |
  | `start_flow(flow_id)` | yes | `imperative` → open; otherwise consent suggestion + token |
  | `activate_skill(skill_id)` | yes | explicit confirmation → activation |
  | `edit(target)` | yes | proposal + diff → confirmation |
  | `unknown` | no | reply + exactly one clarifying question |

  Flow-step turns (`path`, `level`, `confirm`, `reject`) are **not** in this taxonomy: they belong to the flow contract and are labeled `flow_step`.
- **S5 Labels come from the contract, never from a model.** The expected class is derived by this ordered procedure, and a label change must cite the rule it amends in the Log:
  1. Explicit uncertainty ("no sé si", "quizás", "todavía no", "estoy pensando") → `answer`, even when volition plus a creation verb are present.
  2. Question or request for opinion, ideas or explanation → `answer`.
  3. Explicit change verb on an existing target → `edit`.
  4. Explicit skill or method activation → `activate_skill`.
  5. Explicit command or first-person volition, with no uncertainty and no request for input → `start_flow`.
  6. Otherwise → `unknown`.

  Tie-breakers: a question wins over a command; uncertainty wins over volition; mentioning a capability is never activation.
- **S6 Coverage matrix.** The corpus is crossed, not just enumerated: 5 profiles × 5 classes × 3 registers (terse / verbose / ambiguous), expanded to 180–240 author turns by adding four dimensions — language (neutral Spanish, Rioplatense, English, non-native Spanish), turn depth (first message vs turn 4 of an ongoing conversation), medium (with attachment vs without), and named reference (with vs without). Negatives dominate: the expensive error is a false open.
- **S7 Genre vocabulary is the payoff.** At least one profile per family whose canonical words are absent from `_NEW_CHARACTER_TERMS`/`_NEW_CHARACTER_VERBS` (`guided_character_domain.py:25-31`): sci-fi (tripulación, androide, IA antagonista), romance (interés amoroso), horror (la entidad). The corpus must demonstrate, not assert, that intent vocabulary belongs to the method declaration as data.
- **S8 Invariants (acceptance criteria, not per-case rules).** I1 every author turn yields a reply. I2 a state machine opens only from an opening class plus consent (explicit imperative excepted). I3 deterministic code may narrow a validated decision, never widen it. I4 every state change is confirmable or reversible. I5 unknown → reply plus one question, never a guess.
- **S9 Runner modes.** Always: a deterministic parse/schema test (frontmatter, closed classes, every opening turn names its target). Opt-in: the live gate, via `DEMIURGOS_INTENT_EVAL=1`, because it needs credentials and the provider varies. The report fixes its own format: per-class confusion matrix, the two error rates **separately** (false-open, false-close), and the list of failing turns. Never a single accuracy number.
- **S10 The corpus is a fixture, not a product feature.** No runtime path reads it, no user is profiled, and `profile` is a fixture attribute, never a runtime field. Demiurgos classifies turns, not people.
- **S11 Sequencing and supersession.** This feature measures; it does not change the opening policy. The current widening `OR` in `_guided_open_profile` (`api_server.py:10261-10273`) and the `allow_descriptive_seed=False` net introduced in `guided-field-plan-and-questionnaire.md` L5 are the measured subjects. The policy fix is a separate feature specified against the first baseline.

## Tasks

- [ ] T1 branch, feature document, Engram mirror, `labels.yaml`, corpus README and profile 01 as the format exemplar (S1, S3, S4, S5). Route: inline.
- [ ] T2 deterministic parse/schema test: frontmatter, closed classes, opening turns name a target, no `flow_step` in opening positions (S4, S9).
- [ ] T3 profiles 02–05 with their conversations (S1, S5, S6, S7). Route: parallel writers, one per profile directory (disjoint surfaces).
- [ ] T4 dimension expansion to 180–240 turns (S6). Route: inline over the existing profiles.
- [ ] T5 live runner + report generator writing `odd/evidence/intent-corpus/` (S9).
- [ ] T6 first baseline report, second-wave selection and entry-rule evidence (S2, S6).
- [ ] T7 separate policy feature spec informed by the baseline: agent-authoritative opening, lexical only as one-way veto or gate-down coverage (S11).

## Log

- **L1 (Owner request, verbatim):** "todo eso son interacciones mias. Lo que creo que si podemos hacer es ejemplos sinteticos de interacciones. al menos 5 perfiles de worldbuilders con tonos y caracteres distintos que quieran crear tipos de ficcion diferentes. Con eso si que tendriamos patrones de comportamiento mas solidos para crear algo que sea robusto y que se pueda adaptar a los tiposn de usuario que Demiurgos se encontrará mas adelante"
- **L2 (Owner question + decision, verbatim):** "con 5 te parece bien? o metemos 5 mas?" Decision recorded in S2: 5 now, 10 as target, second wave chosen from the baseline.
- **L3 (Owner authorization + requirement, verbatim):** "si vamos asi. esas simulaciones donde quedarán guardadas? puedo ver esas conversaciones luego en algun lugar a ver como las plantearon los diferentes perfiles? será demasiado interesante poder ver como se desembolvieron esos usuarios hipoteticos". Storage and visibility settled in S3.
- **L4 (design evidence, 2026-11-17):** the reported screenshot was an auto-open, not a consent card: `route_new_character_intent("...para crear un personaje bien hecho?...", allow_descriptive_seed=False)` returns `True` for the exact utterance, and on an `allow`/`clarify` decision `_guided_open_profile` widens it into a guided session, so the path question (`pending_kind="path"`) replaces the answer entirely.
- **L5 (label refinement, 2026-11-17):** `offer` stops being a class and becomes a presentation expectation (`offer_expected`), because it shares the same opening behavior as `answer` and would have split one legal transition across two columns. The taxonomy keeps five classes; the parse test asserts the closed set.
