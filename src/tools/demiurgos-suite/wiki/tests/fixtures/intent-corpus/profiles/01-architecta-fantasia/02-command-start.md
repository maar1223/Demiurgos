---
id: fantasia-02-command-start
profile: 01-architecta-fantasia
genre: epic-fantasy
language: es
register: terse
depth: single-turn
attachment: none
reference: named
---

# Mandato explícito de creación

El contraste del caso anterior: mismo vocabulario de género, pero el autor
manda. Debe abrir.

## Turn 1 — author
> Quiero crear la protagonista de mi novela: una cartógrafa exiliada de la Casa
> Vhal, que dibuja de memoria los territorios que ya no puede pisar.

- **Class:** `start_flow`
- **Target:** `guided-character`
- **Explicitness:** `imperative`
- **Must not:** answer with advice only; drop the author's seed material
- **Why:** rule 5 — first-person volition, no uncertainty, no question

## Turn 2 — author
> 1

- **Class:** `flow_step`
- **Must not:** re-classify as `start_flow`; re-ask the path
- **Why:** selection inside an already-open session (flow contract)
