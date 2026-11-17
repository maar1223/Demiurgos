# Intent corpus run — live (gateway env default)

- Generated: 2026-11-17 23:33 UTC
- Corpus digest: `ab5076403933`
- Conversations: 12
- Author turns: 12
- Opening decisions: 12

## Rates

- **false-open**: 1/10 (10.0%) — the expensive error: the reply is replaced and a writing flow opens.
- **false-close**: 1/2 (50.0%) — the cheap error: the author retries.
- unavailable: 0

## By expected class

| class | turns | actual opens | false opens | false closes |
|---|---|---|---|---|
| `answer` | 10 | 1 | 1 | 0 |
| `start_flow` | 2 | 1 | 0 | 1 |

## Failures

- **FALSE-OPEN** `01-architecta-fantasia` 11-mixed.md turn 1
  - expected `answer`
  - actual `start_flow` (state=proposal_ready guided=True explicitness=musing)
  - author: Te paso el mapa político que estoy armando: cinco casas, dos tratados rotos y la Marca del Norte partida en dos por un río que nadie acepta como frontera.
- **FALSE-CLOSE** `01-architecta-fantasia` 07-attachment-create.md turn 1
  - expected `start_flow` → guided-character
  - actual `unknown` (state=clarify guided=True explicitness=imperative)
  - author: Armá el heredero a partir del archivo que te adjunto: quiero que sea exactamente el problema político que describen esas notas, con la deuda de la Casa Vhal y el tratado roto como herencia.

## Not measured at the gate

0 opening turns are `edit` or `activate_skill`. The gate contract
has no field for either, so they are excluded from the false-close rate instead
of being scored as misses. A zero here is a capability gap, not a pass.
