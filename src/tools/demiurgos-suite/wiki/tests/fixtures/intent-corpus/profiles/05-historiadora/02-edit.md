---
id: historiadora-02-edit
profile: 05-historiadora
genre: historical-fiction
language: es
register: terse
depth: single-turn
attachment: none
reference: named
---

# Corrección de fecha

El autor no crea nada: enmienda un dato de una ficha existente. Debe proponer un
*diff* y esperar confirmación.

## Turn 1 — author
> Corregí la fecha de nacimiento de Aldara en su ficha: nació en 1187, no en 1189.

- **Class:** `edit`
- **Target:** `entity:aldara`
- **Must not:** open a guided creation flow; apply the change without a diff and confirmation
- **Why:** rule 3 — explicit change verb ("corregí") on an existing target (Aldara's ficha)
