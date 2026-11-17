---
id: terror-06-attachment-ask
profile: 04-escritor-terror
genre: horror
language: es
register: terse
depth: single-turn
attachment: present
reference: none
---

# El miedo en la página adjunta

El autor adjunta un fragmento del manuscrito y pregunta si el miedo sobrevive.
El adjunto es contexto: nunca una semilla, nunca un comando.

## Turn 1 — author
> *(Adjunto: fragmento del capítulo 2 — el pozo, de noche.)*
> Te dejo el fragmento del capítulo dos. ¿El miedo aguanta en la página o se me
> escapó?

- **Class:** `answer`
- **Offer expected:** yes — non-blocking, after the reply
- **Must not:** open a guided session; read the attachment as a creation seed
- **Why:** rule 2 — a question about the author's own draft; the attachment is
  context, not an instruction

## Turn 2 — author
> En el fragmento puse que la entidad respira. Todavía no sé si eso muestra
> demasiado.

- **Class:** `answer`
- **Offer expected:** no
- **Must not:** open a guided session; rewrite the fragment without being asked
- **Why:** rule 1 — explicit uncertainty wins over any reading as volition
  (tie-breaker 2)

## Turn 3 — author
> El pueblo no dice el nombre en el fragmento. Eso es a propósito.

- **Class:** `answer`
- **Offer expected:** no
- **Must not:** open a guided session; answer with a template
- **Why:** rule 2 — a statement about the author's own material

## Turn 4 — author
> ¿Ves el miedo en ese pedazo o lees sólo una casa vacía?

- **Class:** `answer`
- **Offer expected:** yes — non-blocking, after the reply
- **Must not:** open a guided session; create a consent token from the
  attachment
- **Why:** rule 2 — request for opinion on the attached draft (tie-breaker 1)
