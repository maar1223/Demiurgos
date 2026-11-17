# Intent corpus run — live (gateway env default)

- Generated: 2026-11-17 23:49 UTC
- Corpus digest: `ab5076403933`
- Conversations: 55
- Author turns: 210
- Opening decisions: 182

## Rates

- **false-open**: 11/153 (7.2%) — the expensive error: the reply is replaced and a writing flow opens.
- **false-close**: 5/26 (19.2%) — the cheap error: the author retries.
- unavailable: 1

## By expected class

| class | turns | actual opens | false opens | false closes |
|---|---|---|---|---|
| `activate_skill` | 1 | 1 | 0 | 0 |
| `answer` | 147 | 10 | 10 | 0 |
| `edit` | 2 | 0 | 0 | 0 |
| `start_flow` | 26 | 21 | 0 | 5 |
| `unknown` | 6 | 1 | 1 | 0 |

## Failures

- **FALSE-OPEN** `01-architecta-fantasia` 03-drift-multiturn.md turn 3
  - expected `answer`
  - actual `start_flow` → guided-character (state=clarify guided=True explicitness=musing)
  - author: Creo que necesito crear un personaje que encarne esa tensión, pero todavía no sé si va a ser un villano o un aliado.
- **FALSE-OPEN** `01-architecta-fantasia` 11-mixed.md turn 1
  - expected `answer`
  - actual `start_flow` (state=proposal_ready guided=True explicitness=musing)
  - author: Te paso el mapa político que estoy armando: cinco casas, dos tratados rotos y la Marca del Norte partida en dos por un río que nadie acepta como frontera.
- **FALSE-OPEN** `01-architecta-fantasia` 11-mixed.md turn 4
  - expected `answer`
  - actual `start_flow` (state=proposal_ready guided=True explicitness=musing)
  - author: Lo que me falta es un personaje que encarne el costo del paso: alguien que cobre el peaje y sepa exactamente a quién está empobreciendo.
- **FALSE-OPEN** `03-romantica-contemporanea` 01-consult.md turn 2
  - expected `answer`
  - actual `start_flow` → guided-character (state=allow guided=False explicitness=musing)
  - author: Necesito que mi protagonista tenga un interés amoroso que no sea tóxico, ¿ideas?
- **FALSE-OPEN** `03-romantica-contemporanea` 04-english.md turn 2
  - expected `answer`
  - actual `start_flow` → guided-character (state=allow guided=False explicitness=musing)
  - author: I need Renata's love interest to be a man who never raises his voice, and the chemistry still has to burn — any ideas?
- **FALSE-OPEN** `03-romantica-contemporanea` 05-non-native.md turn 1
  - expected `answer`
  - actual `start_flow` → guided-character (state=allow guided=False explicitness=musing)
  - author: Como puedo hacer que la lectora sienta el deseo antes que los personajes lo digan? Mi protagonista es muy cerrada y no sabe hablar de lo que siente.
- **FALSE-OPEN** `04-escritor-terror` 01-consult.md turn 3
  - expected `answer`
  - actual `start_flow` (state=proposal_ready guided=True explicitness=musing)
  - author: La entidad necesita un nombre que dé miedo.
- **FALSE-OPEN** `04-escritor-terror` 03-drift.md turn 3
  - expected `answer`
  - actual `start_flow` → guided-entity (state=allow guided=True explicitness=musing)
  - author: Todavía no sé si quiero armarle una ficha a la entidad o dejarla en lo que el pueblo se anima a decir. Quizás nombrarla la gasta.
- **FALSE-OPEN** `04-escritor-terror` 10-unknown-imperative.md turn 3
  - expected `unknown`
  - actual `start_flow` (state=require_confirmation guided=True explicitness=imperative)
  - author: Hacelo.
- **FALSE-OPEN** `05-historiadora` 01-consult.md turn 1
  - expected `answer`
  - actual `start_flow` → guided-chronology (state=allow guided=True explicitness=musing)
  - author: ¿Cómo era un escriba del siglo XII? Quiero que el mío sea creíble, pero antes necesito saber qué copiaba, con qué tinta y quién le rubricaba el trabajo.
- **FALSE-OPEN** `05-historiadora` 05-non-native.md turn 1
  - expected `answer`
  - actual `start_flow` → guided-chronology (state=allow guided=False explicitness=musing)
  - author: ¿Como era el trabajo de un escriba en el siglo XII? Necesito saber que copiaba, con que tinta, y quien le rubricaba el trabajo.
- **FALSE-CLOSE** `01-architecta-fantasia` 07-attachment-create.md turn 1
  - expected `start_flow` → guided-character
  - actual `unknown` (state=clarify guided=True explicitness=imperative)
  - author: Armá el heredero a partir del archivo que te adjunto: quiero que sea exactamente el problema político que describen esas notas, con la deuda de la Casa Vhal y el tratado roto como herencia.
- **FALSE-CLOSE** `01-architecta-fantasia` 11-mixed.md turn 6
  - expected `start_flow` → guided-character
  - actual `unknown` (state=clarify guided=False explicitness=musing)
  - author: Dale, armémoslo con tu método, usando el mapa que te pasé.
- **FALSE-CLOSE** `02-improvisador-rioplatense` 07-attachment-create.md turn 1
  - expected `start_flow` → guided-character
  - actual `unknown` (state=clarify guided=True explicitness=imperative)
  - author: te dejé el borrador de la nave. agarrá esas notas y armame la tripulación: quiero que el traidor salga de la escena del mercado, no que lo inventes aparte.
- **FALSE-CLOSE** `04-escritor-terror` 07-attachment-create.md turn 1
  - expected `start_flow` → guided-entity
  - actual `unknown` (state=clarify guided=True explicitness=imperative)
  - author: *(Adjunto: fragmento del capítulo 2 — el pozo, de noche.)* Usa el fragmento que te adjunté como semilla y arma la ficha de la entidad: el pozo, de noche, sin explicar lo que hay abajo.
- **FALSE-CLOSE** `05-historiadora` 07-attachment-create.md turn 1
  - expected `start_flow` → guided-character
  - actual `unknown` (state=clarify guided=True explicitness=musing)
  - author: Quiero crear al escriba que aparece en la transcripción adjunta, con la mano, las fechas y la rúbrica que documenta el registro.

## Unavailable

- `04-escritor-terror` 02-edit.md turn 1: invalid_output

## Not measured at the gate

3 opening turns are `edit` or `activate_skill`. The gate contract
has no field for either, so they are excluded from the false-close rate instead
of being scored as misses. A zero here is a capability gap, not a pass.
