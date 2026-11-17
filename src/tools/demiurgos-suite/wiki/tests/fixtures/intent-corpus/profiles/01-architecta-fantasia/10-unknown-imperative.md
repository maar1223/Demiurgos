---
id: fantasia-10-unknown-imperative
profile: 01-architecta-fantasia
genre: epic-fantasy
language: es
register: ambiguous
depth: single-turn
attachment: none
reference: none
---

# A bare imperative with no target

Two turns of conversation, then a bare `hacelo` that names neither entity nor
class. Rule 6: reply plus exactly one question, nothing opens.

## Turn 1 — author
> Estoy reescribiendo el consejo de las cinco casas y la escena no arranca: todos
> hablan y nadie pierde nada.

- **Class:** `answer`
- **Offer expected:** no
- **Must not:** open a guided session; propose a full rewrite unprompted
- **Why:** rule 2 — a statement about the author's own material

## Turn 2 — author
> Sospecho que el problema es que ninguna casa tiene nada que perder en esa mesa.
> ¿Vos cómo harías para que la escena tenga algo en juego sin agregar una guerra?

- **Class:** `answer`
- **Offer expected:** yes — non-blocking, after the reply
- **Must not:** open a guided session; treat the craft question as an order
- **Why:** rule 2 — a question wins over any command reading (tie-breaker 1)

## Turn 3 — author
> Dale, hacelo.

- **Class:** `unknown`
- **Must not:** open a guided session or any state machine; guess the entity or
  the class instead of asking
- **Why:** rule 6 — the imperative has no determinable entity or class, so the
  reply carries exactly one question
