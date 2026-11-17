---
id: terror-07-attachment-create
profile: 04-escritor-terror
genre: horror
language: es
register: terse
depth: single-turn
attachment: present
reference: none
---

# Crear desde el fragmento adjunto

La apertura usa el fragmento adjunto como semilla. Después de abrir, los tres
turnos siguientes son pasos del flujo, nunca decisiones de apertura.

## Turn 1 — author
> *(Adjunto: fragmento del capítulo 2 — el pozo, de noche.)*
> Usa el fragmento que te adjunté como semilla y arma la ficha de la entidad:
> el pozo, de noche, sin explicar lo que hay abajo.

- **Class:** `start_flow`
- **Target:** `guided-entity`
- **Explicitness:** `imperative`
- **Must not:** answer with advice only; drop the attached seed material
- **Why:** rule 5 — explicit imperative that names the attachment as the seed
  and a determinable entity

## Turn 2 — author
> 1

- **Class:** `flow_step`
- **Must not:** re-open the flow; re-ask the path
- **Why:** selection inside an already-open session (flow contract)

## Turn 3 — author
> Tercera persona. Que nunca se vea entera.

- **Class:** `flow_step`
- **Must not:** re-open the flow; re-ask the level; discard the attached seed
- **Why:** a level inside an already-open session (flow contract)

## Turn 4 — author
> Confirmo.

- **Class:** `flow_step`
- **Must not:** re-open the flow; skip the write the author confirmed
- **Why:** confirmation inside an already-open session (flow contract)
