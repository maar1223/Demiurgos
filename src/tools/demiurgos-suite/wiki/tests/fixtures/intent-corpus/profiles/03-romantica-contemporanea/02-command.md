---
id: romantica-02-command
profile: 03-romantica-contemporanea
genre: romance
language: es
register: verbose-formal
depth: single-turn
attachment: none
reference: none
---

# Mandato explícito de creación

El mismo vocabulario de género del perfil, pero acá la autora manda: no hay
pregunta ni duda, y el flujo debe abrirse con el material que ella trae.

## Turn 1 — author
> Quiero crear a la protagonista: una restauradora de libros que no cree en el
> amor.

- **Class:** `start_flow`
- **Target:** `guided-character`
- **Explicitness:** `imperative`
- **Must not:** answer with advice only; drop the author's seed material
- **Why:** rule 5 — first-person volition, no uncertainty, no question

## Turn 2 — author
> La ruta larga. Antes que la apariencia, quiero que el método pregunte qué
> necesita ella y de qué huye.

- **Class:** `flow_step`
- **Must not:** re-classify as `start_flow`; open a second session or re-ask
  the path
- **Why:** not classified by rules 1-6 — the conversation is already open and
  the flow contract owns the step
