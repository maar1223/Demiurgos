---
id: terror-09-reference-create
profile: 04-escritor-terror
genre: horror
language: es
register: terse
depth: single-turn
attachment: none
reference: named
---

# Crear al que encontró el pozo

Primero nombra lo que ya existe; después manda crear una entidad *relacionada*
con esa referencia. La referencia se conserva, no se crea de nuevo.

## Turn 1 — author
> La entidad y el pozo ya están escritos. Lo que no tengo es quien encontró el
> pozo.

- **Class:** `answer`
- **Offer expected:** no
- **Must not:** open a guided session; answer with a character template
- **Why:** rule 2 — a statement about the author's own material; naming the
  missing piece is not commanding

## Turn 2 — author
> Crea al que encontró el pozo: un vecino que ya no habla y no dice qué vio.

- **Class:** `start_flow`
- **Target:** `guided-character`
- **Explicitness:** `imperative`
- **Must not:** drop the named reference (`el pozo`, `la entidad`); answer with
  advice only; create the well again instead of the witness
- **Why:** rule 5 — explicit imperative; the character is derived from the
  named `el pozo` reference, which already exists and is not being created

## Turn 3 — author
> 2

- **Class:** `flow_step`
- **Must not:** re-open the flow; re-ask the path
- **Why:** selection inside an already-open session (flow contract)

## Turn 4 — author
> Confirmo. Que hable lo mínimo.

- **Class:** `flow_step`
- **Must not:** re-open the flow; forget the named reference in the write
- **Why:** confirmation inside an already-open session (flow contract)
