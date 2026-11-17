---
id: sci-fi-04-english
profile: 02-improvisador-rioplatense
genre: science-fiction
language: en
register: terse
depth: single-turn
attachment: none
reference: none
---

# Same impatience, English

The same improvisor, writing in English. Three conversational turns, then an
explicit creation command.

## Turn 1 — author
> forty people on that ship and every one of them sounds like the same person.
> how do I fix that without writing forty bios?

- **Class:** `answer`
- **Offer expected:** no
- **Must not:** open a guided session; answer with a trait table or a template
- **Why:** rule 2 — request for method; tie-breaker 1 (a question beats a
  command)

## Turn 2 — author
> I've got a corp that sells recycled water like it's a religion. villain or
> cardboard cutout?

- **Class:** `answer`
- **Offer expected:** yes — non-blocking, after the reply
- **Must not:** open a guided session; mint a consent token because a genre noun
  appears
- **Why:** rule 2 — request for opinion; naming an idea is not commanding
  (tie-breaker 3)

## Turn 3 — author
> still don't know if the antagonist AI is the whole board or one drone that
> thinks it's the captain.

- **Class:** `answer`
- **Offer expected:** yes — non-blocking, after the reply
- **Why:** rule 1 — explicit uncertainty wins over volition
- **Must not:** open a guided session; pick a reading for the author

## Turn 4 — author
> enough. build me the crew of the Vega-9: the captain, the drone nobody
> controls, and the AI that calls itself the founder.

- **Class:** `start_flow`
- **Target:** `guided-character`
- **Explicitness:** `imperative`
- **Must not:** answer with advice only; open `guided-system` instead; drop the
  named seed elements
- **Why:** rule 5 — explicit imperative, no uncertainty and no request for
  input
