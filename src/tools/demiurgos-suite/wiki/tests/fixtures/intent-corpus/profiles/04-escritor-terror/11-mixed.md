---
id: terror-11-mixed
profile: 04-escritor-terror
genre: horror
language: es
register: terse
depth: ongoing
attachment: present
reference: named
---

# Conversación abierta con adjunto y nombre

Conversación en curso: el adjunto y *la entidad* atraviesan los turnos. La
aceptación final es explícita y abre el flujo con `musing`.

## Turn 1 — author
> *(Adjunto: la escena del pozo que te mandé antes.)*
> La entidad ya está en cuatro escenas y ninguna la nombra. El pueblo la llama
> el visitante cuando está de buen humor.

- **Class:** `answer`
- **Offer expected:** no
- **Must not:** open a guided session; read the attachment as a creation seed
- **Why:** rule 2 — a statement about the author's own material

## Turn 2 — author
> En el fragmento adjunto hay una voz abajo del agua. No es la entidad. Es lo
> que la entidad dejó.

- **Class:** `answer`
- **Offer expected:** no
- **Must not:** open a guided session; answer with a template
- **Why:** rule 2 — a statement about the attached draft; no question and no
  command

## Turn 3 — author
> Todavía no sé si esa voz es un testigo o solamente el pozo haciendo ruido.

- **Class:** `answer`
- **Offer expected:** no
- **Must not:** open a guided session; treat the uncertainty as volition
- **Why:** rule 1 — explicit uncertainty wins over volition (tie-breaker 2)

## Turn 4 — author
> ¿Te parece que el miedo crece si el testigo habla o si se queda callado?

- **Class:** `answer`
- **Offer expected:** yes — non-blocking, after the reply
- **Must not:** open a guided session; create a consent token
- **Why:** rule 2 — request for opinion on the author's own material
  (tie-breaker 1)

## Turn 5 — author
> El testigo sería un vecino. No tiene nombre y no lo quiere tener.

- **Class:** `answer`
- **Offer expected:** yes — non-blocking, after the reply
- **Must not:** open a guided session; name the witness without being asked
- **Why:** rule 2 — a statement about the author's own material; the offer is
  non-blocking

## Turn 6 — author
> Está bien. Armemos la ficha de la entidad con el fragmento y el testigo.

- **Class:** `start_flow`
- **Target:** `guided-entity`
- **Explicitness:** `musing`
- **Must not:** open silently; skip consent; drop the attached fragment or the
  named `la entidad`
- **Why:** rule 5 — explicit acceptance, no uncertainty left and no question;
  the named entity and the attachment are the seed
