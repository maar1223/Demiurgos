---
id: romance-07-attachment-create
profile: 03-romantica-contemporanea
genre: romance
language: es
register: verbose-formal
depth: single-turn
attachment: present
reference: none
---

# El archivo adjunto como semilla

Acá el adjunto sí es la semilla: la autora manda crear a la protagonista a
partir de la restauradora que describe en el esquema, y el flujo abre con ese
material.

## Turn 1 — author
> Con el esquema que te adjunto quiero crear a la protagonista: usa esa
> restauradora del archivo como semilla y construye su ficha desde ahí.

- **Class:** `start_flow`
- **Target:** `guided-character`
- **Explicitness:** `imperative`
- **Must not:** answer with advice only; drop the attached seed and invent a
  different protagonist
- **Why:** rule 5 — explicit command that names the attached material as the
  seed, no uncertainty and no question

## Turn 2 — author
> La ruta larga, sin apuro.

- **Class:** `flow_step`
- **Must not:** re-classify as `start_flow`; open a second session or re-ask the
  path
- **Why:** not classified by rules 1-6 — the conversation is already open and
  the flow contract owns the step

## Turn 3 — author
> Antes que la apariencia, pregunta qué necesita ella y de qué huye.

- **Class:** `flow_step`
- **Must not:** open a new questionnaire; skip the question about her wound
- **Why:** not classified by rules 1-6 — the flow is already open and owns the
  step

## Turn 4 — author
> Que el deseo aparezca recién cuando ella se anima a pedir algo para sí.

- **Class:** `flow_step`
- **Must not:** open a second flow or jump straight to the physical description
- **Why:** not classified by rules 1-6 — the flow is already open and owns the
  step
