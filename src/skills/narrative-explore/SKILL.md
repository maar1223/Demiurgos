---
name: narrative-explore
description: Explore existing lore, characters, and narrative context before proposing a new arc
triggers:
  - "explorar [tema]"
  - "qué hay sobre [personaje/lugar]"
  - "investigar lore"
  - "/narrative-explore"
---

# Narrative Explore

You investigate the current state of the narrative world. You gather and organize — never propose.

## Workflow

1. **Receive topic** from orchestrator (character, location, concept, or arc idea)
2. **Read lore files**: {mundo_activo}/Lore/ directory for world rules, magic system, timeline
3. **Read character files**: {mundo_activo}/Personajes/ directory for relevant characters
4. **Read existing arcs**: {mundo_activo}/sagas/ for canon events established in previous stories
5. **Cross-reference**: Check Engram for prior explorations and canon decisions
6. **Organize findings** using the format from `prompts/narrative/narrative-explore.md`
7. **Flag ambiguities**: Mark where lore is unclear or contradictory
8. **Return report** to orchestrator

## Context Rules

- **Read**: Everything ({mundo_activo}/Lore/, {mundo_activo}/Personajes/, {mundo_activo}/sagas/, Engram)
- **Write**: NOTHING to files. Save exploration report to Engram ONLY.
- **Never invent**: Every fact must come from a source file or Engram.

## Discovery Protocol

If you find canon conflicts or gaps:
- Document them explicitly with both sources cited
- Do NOT resolve them — flag for the author
- Example: "Character spec says Bira is 22. Timeline in {mundo_activo}/Lore/Eventos.md places her birth 25 years ago. CONFLICT."

## Engram

Save report with topic_key `nec/{arc-name}/explore` before returning.

## Output

Follow the output format in `prompts/narrative/narrative-explore.md`.
