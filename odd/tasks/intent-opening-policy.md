# Intent opening policy: the gate decides, the server only routes

Branch: `feat/intent-opening-policy`, stacked on `feat/intent-corpus` (`bac9e05`). Delivery: work-unit commits; no push/PR unless the Owner asks.
Runners: `.venv/bin/python -m pytest src/tools/demiurgos-suite/wiki/tests/`; policy measurement: `intent_corpus_runner.py --live --concurrency 4`.

Measured by: `odd/tasks/intent-corpus.md` and `odd/evidence/intent-corpus/2026-11-17-baseline-live.md`.

## Specs

- **S1 (Owner requirement, verbatim):** "creo que el asistente siempre tienen que distinguir claramente la intencion del usuario. De si quiere hablar nada mas o preguntar de algo, o si quiere lanzar un flujo o activar alguna skill." Talking and asking never open anything; only an explicit command or a consented offer does. That distinction is a first-class contract, not a per-case judgment.
- **S2 (Owner constraint, verbatim):** "no digo que le demos el control total de Demiurgos al LLM, pero que al menos haya un doble check de ciertas decisiones." The validated semantic decision owns *whether* to open. The double check is the human consent card plus the truth table below — never a keyword layer. Deterministic code keeps authority over authorization, availability, schema and target validity; it keeps no opinion about language.
- **S3 (Owner expectation, verbatim):** "lo que queria que me hablara el LLM es acerca de que recomendaciones me daba para crear un personaje, osea, queria que me explicara primero, y posiblemente luego me dijera que tenia un protocolo interno para hacer personajes. Pero no que me lanzara la creacion de ficha de personaje de una sola vez". The answer is the product. The offer is subordinate, non-blocking and comes after the answer. The path and level questions exist only inside a session the author already consented to.
- **S4 The whole policy is one truth table over fields the gate already emits.** No row reads the utterance.

  | state | guided | explicitness | transition |
  |---|---|---|---|
  | `allow` | false | any | answer only |
  | `clarify` | false | any | answer + exactly one question |
  | `allow` / `clarify` | true | `musing` | answer, then a non-blocking consent offer |
  | `allow` / `clarify` | true | `imperative` | open the named target |
  | `require_confirmation` / `proposal_ready` | true | `imperative` | open the named target |
  | `require_confirmation` / `proposal_ready` | true | `musing` | answer, then a consent offer (the typed delta is dropped; it needs a session) |
  | `blocked` | any | any | blocked envelope, nothing opens |
  | no valid decision (`unavailable`) | — | — | fail closed, nothing opens |

  The lexical net leaves the opening path entirely. `_guided_open_profile` stops consulting `route_guided_intent`; the truth table replaces it.
- **S5 The target travels in the contract.** The semantic decision gains `target: {kind: "flow"|"skill", id}` (nullable). The server validates that the id exists and is available; a guided imperative without a target yields exactly one question ("¿qué querés crear?"), never a guessed character sheet. `_resolve_input_flow`'s term guessing is retired from the opening path.
- **S6 No new keyword layer, and no deterministic veto.** The baseline shows the deterministic layer is the dominant source of both error types (7/11 false-opens, 4/5 false-closes). Every future error becomes a corpus row plus a prompt rule; a keyword list that can open or veto an opening is a regression of this spec.
- **S7 The answer survives the offer.** A consent offer never replaces `result.response`. `_guided_consent_suggestion` must return the gate's answer plus an appended offer, with the card rendering the consent. Today the copy "Parece que quieres crear un personaje" replaces the answer, which is the S3 violation.
- **S8 Acceptance is measured, not argued.** Re-run the full corpus live. Targets: false-open ≤ 1/153 and false-close ≤ 1/26, both strictly better than the 11/153 and 5/26 baseline; zero opens on `answer` or `unknown` attributable to deterministic code (by construction of S4). Plus an exhaustive unit test of the truth table (every cell, both nullable fields) and a prompt-contract test for the `target` field.
- **S9 Known trade-off.** Downgrading `proposal_ready` + `musing` from "open and show the proposal" to "answer plus offer" loses one keystroke of convenience and protects the invariant that a writing session opens only with consent or command. Accepted.
- **S10 Supersession.** This retires the `allow_descriptive_seed=False` net introduced in `guided-field-plan-and-questionnaire.md` L5 and the widening `OR` recorded in Engram #3970. The agent-authoritative principle from #3970 is kept; its safety net is not. Coverage for a gate that under-signals moves to the prompt and to the consent offer, both measured by the corpus.

## Tasks

- [ ] T1 branch, feature document, Engram mirror (S1–S10). Route: inline.
- [ ] T2 contract: `target` field on the semantic decision (schema, normalization, validation, prompt requirement) (S5). Route: inline.
- [ ] T3 replace `_guided_open_profile` with the S4 truth table; remove the lexical net from both `/ai/ask` and `/ai/ask/activity` (S4, S6). Route: inline.
- [ ] T4 consent offer preserves the gate's answer in both server copy paths (S7). Route: inline.
- [ ] T5 prompt hardening with the baseline's negative examples: advice/ideas questions, statements about the author's own material, explicit uncertainty, and a bare imperative without an antecedent (S6, S8). Route: inline.
- [ ] T6 tests: exhaustive truth table, target resolution, answer-preservation, and the retired-net regression (an `allow`/`clarify` decision never opens) (S4, S5, S7).
- [ ] T7 live re-baseline and comparison report under `odd/evidence/intent-corpus/` (S8). Route: live run, concurrency 4.
- [ ] T8 docs: `docs/architecture/demiurgos-platform.md` and `skill-runtime-consumption-contract.md` updated so the closed decision and the implementation agree again (S10).

## Log

- **L1 (Owner authorization, verbatim):** "dale" — write the policy spec informed by the first baseline.
- **L2 (baseline evidence, 2026-11-17; corrected 2026-11-18):** `odd/evidence/intent-corpus/2026-11-17-baseline-live.md`, 182 decisions. **8 false-opens (5.2%)**: 7 from the lexical net widening a non-imperative decision (4 × `allow/guided=false/musing`, 2 × `allow/guided=true/musing`, 1 × `clarify/guided=true/musing`), 1 from the gate (`require_confirmation/imperative` on a bare "Hacelo."). The run as generated listed 11; 3 were `proposal_ready/musing`, which the server turns into a consent offer rather than a session, so they belong to the third metric below. 5 false-closes (19.2%): 4 from the strict lexical flow resolver refusing a correct `guided=true, imperative` because "heredero", "tripulación" and "escriba" are absent from `_NEW_CHARACTER_TERMS`; 1 from the gate returning `guided=false` for an explicit acceptance. **3 answers were replaced by a consent offer** — the S3/S7 defect, not a hijack.
- **L3 (design decision, 2026-11-17):** no deterministic veto was added even though it could have caught 3 of the 4 gate errors. A veto is the same failure mode with the sign flipped: it would need its own keyword list, its own false-positive surface, and its own patches. The gate's remaining errors are attacked in the prompt and measured by the corpus, which keeps one owner for the decision.
- **L4 (prediction, 2026-11-18):** with S4 alone, all 7 lexical false-opens disappear and the server stops opening on a non-imperative continuation; with S7 the 3 replaced answers become answers plus an offer; with S5 plus a gate that names `guided-character` for "heredero"/"tripulación"/"escriba", the 4 attachment false-closes disappear. The residual is the bare "Hacelo." (prompt rule, T5) and the single gate miss on "Dale, armémoslo con tu método". Expected post-fix: false-open ≤ 1, false-close ≤ 1, replaced answers 0.
