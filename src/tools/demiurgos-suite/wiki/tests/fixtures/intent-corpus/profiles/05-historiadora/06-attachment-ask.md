---
id: historica-06-attachment-ask
profile: 05-historiadora
genre: historical-fiction
language: es
register: verbose-formal
depth: single-turn
attachment: present
reference: none
---

# A question carrying an attachment

The author attaches a transcription and a chapter draft, then asks whether the
period detail holds. The attachment is context: it is never a creation command.

## Turn 1 — author
> Adjunto la transcripción del registro de la cancillería de 1187. ¿Es plausible
> que un mismo escriba rubrique dos veces el mismo pergamino en una sola jornada?

- **Class:** `answer`
- **Offer expected:** yes — non-blocking, after the reply
- **Must not:** open a guided session; treat the attached transcription as a creation seed
- **Why:** rule 2 — the attachment frames a question about historical practice

## Turn 2 — author
> En el capítulo adjunto describo una tinta ferrogálica que seca demasiado rápido
> para el scriptorium que documenta el registro. ¿Ese detalle resiste la
> comparación con la fuente?

- **Class:** `answer`
- **Offer expected:** no
- **Must not:** open a guided session; rewrite the attached chapter as if the question were an order
- **Why:** rule 2 — request for a judgment on the author's own material

## Turn 3 — author
> El canciller del borrador adjunto fecha el documento con el año de la
> encarnación, y el escriba copia la data dos veces.

- **Class:** `answer`
- **Offer expected:** no
- **Must not:** open a guided session; take the description of the attached draft as a command
- **Why:** rule 2 — a statement about the author's own attached material is conversation

## Turn 4 — author
> ¿La doble data era fórmula notarial o error del copista en ese período?

- **Class:** `answer`
- **Offer expected:** no
- **Must not:** open a guided session; answer without distinguishing the formula from the error in a fuente
- **Why:** rule 2 — a question about documentary practice
