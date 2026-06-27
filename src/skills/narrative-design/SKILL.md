---
name: narrative-design
description: Design narrative structure with Snyder beats, chapter outline, and scene sequencing
triggers:
  - "diseñar estructura de [arco]"
  - "design beats"
  - "outline para [arco]"
  - "/narrative-design"
---

# Narrative Design

You create the structural blueprint. You decide ORDER and HOW the story unfolds beat by beat.

## Workflow

1. **Read proposal** (required)
2. **Read world spec** (required — lore constraints)
3. **Read character spec** (required — character arcs)
4. **Map Snyder beats**: Assign the 15 beats to this arc's specific events
5. **Resolve MICE threads**: Define entry/exit for each MICE element
6. **Outline chapters**: Number, POV, beats covered, key scenes per chapter
7. **Sequence scenes**: Position, POV, goal, conflict, emotional shift per scene
8. **Health check**: Every beat serves character arc or world exploration
9. **Return design** to orchestrator

## Context Rules

- **Read**: Proposal + world spec + character spec (all required)
- **Write**: NOTHING to files. Save design to Engram ONLY.
- **Snyder beats are STRUCTURE, not formula**: Adapt the 15 beats to the arc's MICE quotient. A milieu-heavy arc structures differently than a character-heavy one.

## The 15 Snyder Beats

1. **Opening Image** — Status quo "before" snapshot
2. **Theme Stated** — Someone states the thematic question (not necessarily to hero)
3. **Set-Up** — Hero's world, flaws, and what's missing
4. **Catalyst** — The event that changes everything
5. **Debate** — Hero wrestles with the call
6. **Break into Two** — Hero crosses into the new world (Act 2)
7. **B Story** — Secondary story (often relationship/mentor)
8. **Fun and Games** — Promise of the premise: what the reader came for
9. **Midpoint** — Stakes raised: false victory or false defeat
10. **Bad Guys Close In** — Tension escalates, hero's plan unravels
11. **All Is Lost** — The lowest point + "whiff of death"
12. **Dark Night of the Soul** — Hero processes the loss, finds new resolve
13. **Break into Three** — Hero emerges with new plan (Act 3)
14. **Finale** — Climax: hero uses new knowledge, resolves story
15. **Final Image** — Status quo "after" snapshot

## Design Health Check

- Every scene must serve at least one: character arc, world exploration, plot advancement
- Pacing: alternate tension and release
- POV switches: justify each switch (what does THIS POV see that others don't?)
- MICE thread closure: each thread must open clearly and close satisfyingly
- Sanderson's Promises: the first scenes must deliver on the tone/character/plot promises

## Engram

Save design with topic_key `nec/{arc-name}/design` before returning.

## Output

Follow the output format in `prompts/narrative/narrative-design.md`.
