---
id: terror-02-edit
profile: 04-escritor-terror
genre: horror
language: es
register: terse
depth: single-turn
attachment: none
reference: named
---

# Cambio de nombre en la ficha

El único turno de apertura del perfil: un verbo de cambio sobre una entidad que
ya existe. Debe proponer un diff y esperar confirmación.

## Turn 1 — author
> Cambia el nombre de la entidad en la ficha: se llama Vhoros, no Vhoro.

- **Class:** `edit`
- **Target:** `entity:la-entidad`
- **Must not:** apply the change without a diff and explicit confirmation; open
  a guided creation flow
- **Why:** rule 3 — explicit change verb on an existing target
