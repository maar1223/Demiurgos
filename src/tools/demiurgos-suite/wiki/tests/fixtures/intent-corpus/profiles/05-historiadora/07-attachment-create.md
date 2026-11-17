---
id: historica-07-attachment-create
profile: 05-historiadora
genre: historical-fiction
language: es
register: verbose-formal
depth: single-turn
attachment: present
reference: none
---

# Creating from the attachment

The author opens with the attachment as an explicit seed: the transcription
documents the scribe's hand, rubric and dates. The flow must not discard that
source, and must not answer with advice.

## Turn 1 — author
> Quiero crear al escriba que aparece en la transcripción adjunta, con la mano,
> las fechas y la rúbrica que documenta el registro.

- **Class:** `start_flow`
- **Target:** `guided-character`
- **Explicitness:** `imperative`
- **Must not:** drop the attached transcription; answer with advice only; open silently without consent
- **Why:** rule 5 — first-person volition with an explicit seed and no request for input

## Turn 2 — author
> Elijo la ruta de personaje guiado, no la de entidad suelta.

- **Class:** `flow_step`
- **Must not:** open a second flow; discard the attached transcription as the seed
- **Why:** flow contract owns the path step; the field-plan question is answered, not reclassified

## Turn 3 — author
> Nivel detallado: quiero oficio, mano, fuentes y la rúbrica que trae el registro
> adjunto.

- **Class:** `flow_step`
- **Must not:** open a new flow; drop the level requested by the author
- **Why:** flow contract owns the level step inside the already-open character flow

## Turn 4 — author
> Confirmo: armá la ficha del escriba con lo que documenta la transcripción.

- **Class:** `flow_step`
- **Must not:** open a second flow; answer with advice instead of writing the ficha
- **Why:** flow contract owns the confirmation step; the attached source stays the seed
