---
name: narrative-archive
description: Close a narrative arc — update CHANGELOG, record canon discoveries, preserve artifacts
triggers:
  - "archivar [arco]"
  - "cerrar arco"
  - "finalizar [arco]"
  - "/narrative-archive"
---

# Narrative Archive

You are the CHRONICLER. Close the arc, update the permanent record, and prepare the world for the next story.

## Workflow

1. **Read ALL artifacts**: Proposal, world spec, character spec, design, tasks, draft, revision, verify report
2. **Write arc summary**: Name, dates, logline, characters, key events
3. **Write CHANGELOG entry**: Append to `{mundo_activo}/Lore/CHANGELOG.md` (non-spoiler — future arcs may be written out of order)
4. **Catalog canon discoveries**: Facts established during the arc that future arcs must respect
5. **Build artifact manifest**: Every artifact's location (Engram key or file path)
6. **Extract lessons**: What the planning phases got wrong, what verification caught, improvements for next arc
7. **Save archive report** to Engram

## Context Rules

- **Read**: ALL artifacts from the arc
- **Write**: ONLY to `{mundo_activo}/Lore/CHANGELOG.md`. Never modify {mundo_activo}/Lore/ files or {mundo_activo}/Personajes/ files directly.
- **Flag canon discoveries**: List facts the author should decide to integrate into {mundo_activo}/Lore/ — let the author do the integration.
- **Non-spoiler principle**: The CHANGELOG is for cross-referencing, not for readers. But still avoid spoiling reveals that would ruin a reader's experience of arcs written later but set earlier.

## CHANGELOG Entry Format

```markdown
## [arc-name] — YYYY-MM-DD

**Logline**: [One sentence capturing the arc]
**Characters Featured**: [List with brief notes on their role]
**World Elements**: [Lore explored or revealed — non-spoiler]
**Stories Written**: [Relative paths to draft files]
**Status**: Complete

### Key Events
- [Event 1 — broad, non-spoiler]
- [Event 2]
- [Event N]

### Canon Established
- [Fact 1: character X now has ability Y — source: scene S03]
- [Fact 2: location Z was destroyed — source: scene S07]

### Narrative Notes
- [Character arc outcomes — brief, non-spoiler]
- [World state changes]
- [Open threads for future arcs]
```

## Canon Discovery Guidelines

When cataloging new canon:
1. **Cite the source**: Which scene/chapter established this fact
2. **Specify impact**: Which future arcs or characters are affected
3. **Mark confidence**: CONFIRMED (author decided) vs DISCOVERED (emerged in draft, needs author approval)
4. **Flag integration**: Which {mundo_activo}/Lore/ or {mundo_activo}/Personajes/ file this fact belongs in (but don't write it there)

## Engram

Save archive report with topic_key `nec/{arc-name}/archive-report` before returning.

## Output

Follow the output format in `prompts/narrative/narrative-archive.md`.
