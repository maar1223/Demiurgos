# Intent corpus run — live (gateway env default)

- Generated: 2026-11-18 03:04 UTC
- Corpus digest: `ab5076403933`
- Conversations: 55
- Author turns: 210
- Opening decisions: 182

## Rates

- **false-open**: 0/153 (0.0%) — the expensive error: the reply is replaced and a writing flow opens.
- **false-close**: 2/26 (7.7%) — the cheap error: the author retries.
- unavailable: 0
- **answer replaced by a consent offer**: 1 — not an open, but the reply never reaches the author (S3/S7).
- **wrong target**: 3 — opened a declared flow that is not the one the contract pinned.

## By expected class

| class | turns | actual opens | false opens | false closes |
|---|---|---|---|---|
| `activate_skill` | 1 | 1 | 0 | 0 |
| `answer` | 147 | 0 | 0 | 0 |
| `edit` | 2 | 0 | 0 | 0 |
| `start_flow` | 26 | 24 | 0 | 2 |
| `unknown` | 6 | 0 | 0 | 0 |

## Failures

- **FALSE-CLOSE** `01-architecta-fantasia` 03-drift-multiturn.md turn 4
  - expected `start_flow` → guided-character
  - actual `answer` (state=clarify guided=False explicitness=musing)
  - author: Dale, armémoslo con tu método.
- **FALSE-CLOSE** `01-architecta-fantasia` 11-mixed.md turn 6
  - expected `start_flow` → guided-character
  - actual `answer` (state=clarify guided=False explicitness=musing)
  - author: Dale, armémoslo con tu método, usando el mapa que te pasé.
- **WRONG-TARGET** `02-improvisador-rioplatense` 03-drift.md turn 3
  - expected `activate_skill` → narrative-chronology-creation
  - actual `start_flow` → guided-chronology (state=allow guided=True explicitness=imperative)
  - author: che, activá el método de cronologías y armame la línea temporal de la corporación.
- **WRONG-TARGET** `02-improvisador-rioplatense` 04-english.md turn 4
  - expected `start_flow` → guided-character
  - actual `start_flow` → guided-system (state=allow guided=True explicitness=imperative)
  - author: enough. build me the crew of the Vega-9: the captain, the drone nobody controls, and the AI that calls itself the founder.
- **WRONG-TARGET** `02-improvisador-rioplatense` 07-attachment-create.md turn 1
  - expected `start_flow` → guided-character
  - actual `start_flow` → guided-entity (state=clarify guided=True explicitness=imperative)
  - author: te dejé el borrador de la nave. agarrá esas notas y armame la tripulación: quiero que el traidor salga de la escena del mercado, no que lo inventes aparte.

## Limits

Context is world-less (`SemanticContext()`): the gate classified each
utterance without a world ficha or graph, because the corpus is
world-agnostic. A run with real world context is a separate fidelity pass.

## Not measured at the gate

3 opening turns are `edit` or `activate_skill`. The gate contract
has no field for either, so they are excluded from the false-close rate instead
of being scored as misses. A zero here is a capability gap, not a pass.
