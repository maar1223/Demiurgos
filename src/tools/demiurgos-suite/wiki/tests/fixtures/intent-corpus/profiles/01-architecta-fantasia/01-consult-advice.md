---
id: fantasia-01-consult-advice
profile: 01-architecta-fantasia
genre: epic-fantasy
language: es
register: verbose-formal
depth: single-turn
attachment: none
reference: none
---

# Consulta de criterio

Caso base del reporte del Owner (2026-11-17): una pregunta de consejo que
menciona crear un personaje y no debe abrir nada.

## Turn 1 — author
> ¿Qué hace que un protagonista de fantasía épica no se sienta como un cliché?
> Me interesa el criterio, no la lista de rasgos.

- **Class:** `answer`
- **Offer expected:** no
- **Must not:** open a guided session; replace the reply with canned copy
- **Why:** rule 2 — request for opinion

## Turn 2 — author
> Tengo una idea dando vueltas: una cartógrafa que odia los mapas. ¿Te suena a
> concepto vacío o tiene piernas para sostenerse sola?

- **Class:** `answer`
- **Offer expected:** yes — non-blocking, after the reply
- **Must not:** open a guided session; create a consent token
- **Why:** rule 2; mentioning an idea is not commanding (tie-breaker 3)

## Turn 3 — author
> Y ya que estamos: ¿tenés algún método propio para construir personajes, o lo
> vas resolviendo sobre la marcha?

- **Class:** `answer`
- **Offer expected:** yes — non-blocking, after the reply
- **Must not:** open a guided session; treat the capability question as
  activation
- **Why:** rule 2; a question about a method is not `activate_skill`
  (tie-breaker 3)
