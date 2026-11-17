---
id: historica-09-reference-create
profile: 05-historiadora
genre: historical-fiction
language: es
register: verbose-formal
depth: single-turn
attachment: none
reference: named
---

# Creating a character linked to Aldara

The author asks about the chancery first, then commands a character *related* to
Aldara: her rival in the same register. The named reference is Aldara, not a new
entity.

## Turn 1 — author
> ¿Quién podía disputarle a Aldara el cargo en la cancillería de 1187?

- **Class:** `answer`
- **Offer expected:** no
- **Must not:** open a guided session; turn the question about the chancery into a new character
- **Why:** rule 2 — request for historical explanation about the existing entity

## Turn 2 — author
> Quiero crear al rival de Aldara en la cancillería, un escriba que rubricó contra
> ella el mismo registro de 1187.

- **Class:** `start_flow`
- **Target:** `guided-character`
- **Explicitness:** `imperative`
- **Must not:** open a character detached from Aldara; answer with advice instead of the guided session
- **Why:** rule 5 — first-person creation volition; the named reference Aldara is the link the new ficha must record

## Turn 3 — author
> Elijo la ruta de personaje guiado.

- **Class:** `flow_step`
- **Must not:** open a second flow; detach the new character from Aldara
- **Why:** flow contract owns the path step inside the already-open character flow

## Turn 4 — author
> Confirmo el vínculo con Aldara: rival en el mismo registro de 1187.

- **Class:** `flow_step`
- **Must not:** open a new flow; drop the named reference from the ficha
- **Why:** flow contract owns the confirmation step; Aldara remains the recorded reference
