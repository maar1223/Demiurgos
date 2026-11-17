---
id: sci-fi-09-reference-create
profile: 02-improvisador-rioplatense
genre: science-fiction
language: es-AR
register: terse
depth: single-turn
attachment: none
reference: named
---

# Crear algo pariente de lo ya nombrado

El autor pregunta por la Corporación Vega-9 y después manda crear su capitán
rival. La referencia es la relación, no el objeto.

## Turn 1 — author
> la Corporación Vega-9 ya tiene tres gremios. ¿le falta un cuarto o ya está
> demasiado repartida?

- **Class:** `answer`
- **Offer expected:** no
- **Must not:** open a guided session; add the fourth guild because the
  corporation was named
- **Why:** rule 2 — request for opinion; tie-breaker 3 (mentioning an entity is
  not activation)

## Turn 2 — author
> dale, armame el capitán rival de la Vega-9: el que le vendía agua a la colonia
> antes que ellos y ahora se quiere vengar.

- **Class:** `start_flow`
- **Target:** `guided-character`
- **Explicitness:** `imperative`
- **Must not:** answer with advice only; open `guided-system` instead of
  `guided-character`; drop the named Vega-9 reference that defines the rivalry
- **Why:** rule 5 — explicit imperative, no uncertainty and no request for
  input; the named corporation is the relational seed, not an edit target

## Turn 3 — author
> la 1

- **Class:** `flow_step`
- **Must not:** re-classify as `start_flow`; open a second session; re-ask the
  path
- **Why:** rule 5 already applied at the opening; this turn is owned by the flow
  contract

## Turn 4 — author
> nivel bajo, que se entienda en dos escenas y listo.

- **Class:** `flow_step`
- **Must not:** open a new session; restart from the path question
- **Why:** rule 5 already applied at the opening; this turn is owned by the flow
  contract
