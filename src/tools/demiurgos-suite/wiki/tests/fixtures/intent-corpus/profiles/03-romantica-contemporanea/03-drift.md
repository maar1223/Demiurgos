---
id: romantica-03-drift
profile: 03-romantica-contemporanea
genre: romance
language: es
register: ambiguous
depth: ongoing
attachment: none
reference: none
---

# Deriva en conversación abierta

La autora da vueltas a la misma historia durante dos turnos sin decidir nada: en
el primero pesa la duda, en el segundo pregunta por el riesgo. Recién en el
tercer turno acepta y el flujo abre.

## Turn 1 — author
> Llevo semanas con una restauradora de libros en la cabeza, alguien que repara
> lo que otros rompieron porque no sabe repararse a sí misma. Todavía no sé si el
> interés amoroso tiene que ser el heredero que le embargó el taller o alguien
> completamente nuevo.

- **Class:** `answer`
- **Offer expected:** yes — non-blocking, after the reply
- **Must not:** open a guided session; pick the love interest for her
- **Why:** rule 1 — explicit uncertainty wins over volition (tie-breaker 2)

## Turn 2 — author
> ¿Y un enemies to lovers con el heredero no queda demasiado tóxico para el
> punto de vista de ella?

- **Class:** `answer`
- **Offer expected:** no
- **Must not:** open a guided session; treat the genre question as a request for
  a character sheet
- **Why:** rule 2 — a question wins over a command (tie-breaker 1)

## Turn 3 — author
> De acuerdo, armemos la ficha con tu método y veamos qué sale de la química.

- **Class:** `start_flow`
- **Target:** `guided-character`
- **Explicitness:** `musing`
- **Must not:** open silently; skip consent
- **Why:** rule 5 — explicit acceptance of the method, no uncertainty left
