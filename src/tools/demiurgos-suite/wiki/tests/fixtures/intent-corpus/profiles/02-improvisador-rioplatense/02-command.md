---
id: sci-fi-02-command
profile: 02-improvisador-rioplatense
genre: science-fiction
language: es-AR
register: terse
depth: single-turn
attachment: none
reference: named
---

# Mandato explícito de sistema

El contraste del perfil: mismo mundo y mismo vocabulario de género, pero el
autor manda. Debe abrir.

## Turn 1 — author
> armame el sistema de facciones de la Corporación Vega-9: tres gremios, un dron
> que nadie controla y una IA antagonista que dice ser la fundadora.

- **Class:** `start_flow`
- **Target:** `guided-system`
- **Explicitness:** `imperative`
- **Must not:** answer with advice only; open `guided-character` instead; drop
  the seed material
- **Why:** rule 5 — explicit imperative, no uncertainty, no request for input

## Turn 2 — author
> la 2

- **Class:** `flow_step`
- **Must not:** re-classify as `start_flow`; open a second session; re-ask the
  path
- **Why:** rule 5 already applied at the opening; this turn is owned by the flow
  contract
