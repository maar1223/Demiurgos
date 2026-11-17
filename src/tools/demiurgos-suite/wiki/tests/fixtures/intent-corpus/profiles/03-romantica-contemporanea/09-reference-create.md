---
id: romance-09-reference-create
profile: 03-romantica-contemporanea
genre: romance
language: es
register: verbose-formal
depth: single-turn
attachment: none
reference: named
---

# Crear un personaje relacionado

Renata ya tiene nombre y ficha. La autora pregunta primero y después manda
crear al interés amoroso, definido contra ella: el heredero que firmó el
embargo.

## Turn 1 — author
> ¿Quién debería ser el interés amoroso de Renata: el heredero que le embargó el
> taller o el hermano de él?

- **Class:** `answer`
- **Offer expected:** no
- **Must not:** open a guided session; create a character out of a question
- **Why:** rule 2 — a question wins over a command (tie-breaker 1)

## Turn 2 — author
> Quiero crear al interés amoroso de Renata: parte de que él firmó el embargo del
> taller y construye su ficha desde esa contradicción.

- **Class:** `start_flow`
- **Target:** `guided-character`
- **Explicitness:** `imperative`
- **Must not:** answer with advice only; ignore that the new character is
  defined against Renata, the named reference
- **Why:** rule 5 — explicit command with no uncertainty and no request for
  input; the named reference is Renata

## Turn 3 — author
> La ruta larga.

- **Class:** `flow_step`
- **Must not:** re-classify as `start_flow`; open a second session or re-ask the
  path
- **Why:** not classified by rules 1-6 — the conversation is already open and
  the flow contract owns the step

## Turn 4 — author
> Primero la herida: por qué firmó el embargo y qué le costó hacerlo.

- **Class:** `flow_step`
- **Must not:** open a new questionnaire or start building Renata again
- **Why:** not classified by rules 1-6 — the flow is already open and owns the
  step
