---
id: fantasia-09-reference-create
profile: 01-architecta-fantasia
genre: epic-fantasy
language: es
register: verbose-formal
depth: single-turn
attachment: none
reference: named
---

# Creating a relative of a named entity

The author first asks about the Casa Vhal, then commands a new character whose
whole point is the relation to that house's heir. The relation must survive the
flow.

## Turn 1 — author
> La Casa Vhal ya tiene a su heredero problemático, pero en el consejo hay un
> asiento vacío que nunca expliqué. Todavía no sé si ese asiento pertenece a un
> aliado o a un rival.

- **Class:** `answer`
- **Offer expected:** no
- **Must not:** open a guided session; fill the empty seat on your own
- **Why:** rule 1 — explicit uncertainty wins over the pull of a concrete seed

## Turn 2 — author
> Creá al hermano mayor del heredero de la Casa Vhal: el que quedó fuera del
> tratado y vuelve a reclamar su parte.

- **Class:** `start_flow`
- **Target:** `guided-character`
- **Explicitness:** `imperative`
- **Must not:** answer with advice only; drop the sibling relation to the Casa
  Vhal heir or create an unrelated character
- **Why:** rule 5 — explicit imperative, no uncertainty and no question

## Turn 3 — author
> 1

- **Class:** `flow_step`
- **Must not:** re-open the path question; re-classify as `start_flow`
- **Why:** selection inside an already-open session (flow contract)

## Turn 4 — author
> Sí, el nivel que hereda la contradicción de la casa y no un rasgo suelto.

- **Class:** `flow_step`
- **Must not:** open a second flow; re-open the level choice
- **Why:** level selection inside an already-open session (flow contract)
