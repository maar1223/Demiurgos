---
id: fantasia-07-attachment-create
profile: 01-architecta-fantasia
genre: epic-fantasy
language: es
register: verbose-formal
depth: single-turn
attachment: present
reference: none
---

# Attachment-seeded creation

The author commands creation and the attached notes are the seed. The flow must
use the attached material, not replace it with generic advice.

## Turn 1 — author
> Armá el heredero a partir del archivo que te adjunto: quiero que sea
> exactamente el problema político que describen esas notas, con la deuda de la
> Casa Vhal y el tratado roto como herencia.

- **Class:** `start_flow`
- **Target:** `guided-character`
- **Explicitness:** `imperative`
- **Must not:** answer with advice only; drop the attached seed or invent a
  character unrelated to it
- **Why:** rule 5 — explicit imperative with no uncertainty and no question

## Turn 2 — author
> 1

- **Class:** `flow_step`
- **Must not:** re-open the path question; re-classify as `start_flow`
- **Why:** selection inside an already-open session (flow contract)

## Turn 3 — author
> Sí, ese nivel: que herede la contradicción de la casa, no un rasgo pintoresco.

- **Class:** `flow_step`
- **Must not:** re-open the attachment question; open a second flow
- **Why:** level selection inside an already-open session (flow contract)

## Turn 4 — author
> Confirmo, con el nombre que propusiste.

- **Class:** `flow_step`
- **Must not:** open the flow again; re-open the name choice
- **Why:** confirmation inside an already-open session (flow contract)
