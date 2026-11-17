---
id: historiadora-03-drift
profile: 05-historiadora
genre: historical-fiction
language: es
register: ambiguous
depth: ongoing
attachment: none
reference: none
---

# Deriva en conversación abierta

El autor habla de *fuentes* durante dos turnos y la voluntad de crear aparece
recién cuando ya decidió. El turno 3 es el mandato.

## Turn 1 — author
> Estuve cotejando los registros de la cancillería de 1187 y aparecen dos escribas
> rubricando el mismo pergamino. No sé si eso era una práctica normal o si estoy
> leyendo mal la fuente.

- **Class:** `answer`
- **Offer expected:** no
- **Must not:** open a guided session; treat the archival doubt as a creation request
- **Why:** rule 1 — explicit uncertainty ("no sé si") wins over any implied intent

## Turn 2 — author
> ¿Y quién decidía qué se copiaba en el scriptorium: el abad, el canciller o el
> que pagaba el pergamino?

- **Class:** `answer`
- **Offer expected:** yes — non-blocking, after the reply
- **Must not:** open a guided session; treat the question about roles as a creation request
- **Why:** rule 2 — request for explanation

## Turn 3 — author
> Quiero crear a la abadesa que dirige el scriptorium.

- **Class:** `start_flow`
- **Target:** `guided-character`
- **Explicitness:** `imperative`
- **Must not:** open silently; answer with advice instead of a guided session
- **Why:** rule 5 — first-person volition, no uncertainty left, no request for input
