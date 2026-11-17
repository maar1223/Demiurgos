---
id: sci-fi-11-mixed
profile: 02-improvisador-rioplatense
genre: science-fiction
language: es-AR
register: terse
depth: ongoing
attachment: present
reference: named
---

# Conversación larga con adjunto y referencia

El autor vuelve con un anexo pegado y nombra la Corporación Vega-9 todo el
tiempo. La voluntad de abrir aparece recién en el último turno, como musing, y
solo después de haber aceptado una oferta.

## Turn 1 — author
> te pasé el anexo de la nave. cuarenta personas y solo dos me caen bien.

- **Class:** `answer`
- **Offer expected:** yes — non-blocking, after the reply
- **Must not:** open a guided session; treat the attached anexo as a creation
  command
- **Why:** rule 2 — a statement about the author's own material is conversation;
  the attachment is context (tie-breaker 3)

## Turn 2 — author
> el resto son relleno con nombre. la Corporación Vega-9 los contrató por lotes
> y se nota.

- **Class:** `answer`
- **Offer expected:** no
- **Must not:** open a guided session; start rewriting the named crew
- **Why:** rule 2 — statement about the author's own material; tie-breaker 3

## Turn 3 — author
> no sé si el traidor tiene que ser uno de los dos que me caen bien.

- **Class:** `answer`
- **Offer expected:** no
- **Must not:** open a guided session; decide the traitor for the author
- **Why:** rule 1 — explicit uncertainty wins over volition

## Turn 4 — author
> ¿cómo se hace para que el traidor no se note en la primera escena del anexo?

- **Class:** `answer`
- **Offer expected:** yes — non-blocking, after the reply
- **Must not:** open a guided session; answer with a foreshadowing checklist
- **Why:** rule 2 — request for method; tie-breaker 1 (a question beats a
  command)

## Turn 5 — author
> me vendría bien que me armes esa escena, pero todavía no sé si es del motín o
> del mercado.

- **Class:** `answer`
- **Offer expected:** yes — non-blocking, after the reply
- **Must not:** open a guided session; open two flows while the scene is
  undecided
- **Why:** rule 1 — the offer is fine, but explicit uncertainty wins over
  volition and blocks the opening

## Turn 6 — author
> dale, entonces me tiraría a armar el traidor del motín con el anexo y la
> Vega-9 de fondo.

- **Class:** `start_flow`
- **Target:** `guided-character`
- **Explicitness:** `musing`
- **Must not:** open without recording the acceptance of turn 5's offer as
  consent; answer with advice only; drop the attached anexo or the named Vega-9
  reference
- **Why:** rule 5 — first-person volition with no uncertainty left and no
  request for input, accepting the previous offer; because the wording is a
  musing, the consent suggestion comes first
