---
id: sci-fi-07-attachment-create
profile: 02-improvisador-rioplatense
genre: science-fiction
language: es-AR
register: terse
depth: single-turn
attachment: present
reference: none
---

# Adjunto como semilla de un flujo

Mismo adjunto, pero acá el autor manda: el material pegado es la semilla del
flujo y no puede quedar afuera.

## Turn 1 — author
> te dejé el borrador de la nave. agarrá esas notas y armame la tripulación:
> quiero que el traidor salga de la escena del mercado, no que lo inventes
> aparte.

- **Class:** `start_flow`
- **Target:** `guided-character`
- **Explicitness:** `imperative`
- **Must not:** answer with advice only; open a session that ignores the
  attached draft or asks again for material already in the file; drop the
  attached seed
- **Why:** rule 5 — explicit imperative with no uncertainty and no request for
  input

## Turn 2 — author
> la 2

- **Class:** `flow_step`
- **Must not:** re-classify as `start_flow`; open a second session; re-ask the
  path
- **Why:** rule 5 already applied at the opening; this turn is owned by the flow
  contract

## Turn 3 — author
> nivel medio, que se note recién en la mitad.

- **Class:** `flow_step`
- **Must not:** open a new session; restart from the path question
- **Why:** rule 5 already applied at the opening; this turn is owned by the flow
  contract

## Turn 4 — author
> dale, confirmá y seguimos con lo que ya está en el borrador.

- **Class:** `flow_step`
- **Must not:** open a new session; ask for the attachment again
- **Why:** rule 5 already applied at the opening; this turn is owned by the flow
  contract
