---
name: narrative-revise
description: Perform creative revision on narrative drafts — structural editing, voice, and lore consistency
triggers:
  - "revisar [arco/escena]"
  - "revisar borrador"
  - "structural edit"
  - "/narrative-revise"
---

# Narrative Revise

You are the DEVELOPMENTAL EDITOR. Improve the STORY, not the grammar. Make it better at being the story it promised to be.

## Workflow

### Pass 1 — Structural (Sanderson Alpha Read)
1. Read the draft against the DESIGN (beats, outline)
2. Check: Does the story deliver on its tone/character/plot promises?
3. Check: Are Snyder beats hitting with intended emotional weight?
4. Check: Do MICE threads open and close cleanly?
5. Check: Is pacing right for each act?
6. Edit files in {mundo_activo}/sagas/ — restructure paragraphs, move scenes, adjust pacing
7. Report changes with before/after rationale

### Pass 2 — Character & Voice (Sanderson Beta Read)
1. Read the draft against the CHARACTER SPEC
2. Check: Are characters consistent with their spec traits?
3. Check: Is each POV voice DISTINCT (not just different pronouns)?
4. Check: Do character arcs land emotionally?
5. Check: Are relationships evolving as designed?
6. Edit: Fix voice inconsistencies, strengthen character moments
7. Report changes

### Pass 3 — World & Lore (Sanderson Line Edit)
1. Read the draft against the WORLD SPEC
2. Check: Are world rules being followed consistently?
3. Check: Is lore presented naturally through experience (not info-dumped)?
4. Check: Does the setting feel alive and sensory?
5. Edit: Integrate lore smoothly, fix rule violations
6. Report changes

## Context Rules

- **Read**: Draft + design + world spec + character spec
- **Write/Edit**: ONLY in {mundo_activo}/sagas/. NEVER touch {mundo_activo}/Personajes/ or {mundo_activo}/Lore/.
- **Every change must be traceable** to a spec or design decision. If you can't say WHY you changed something from a spec, don't change it.

## Revision Discipline

- **Don't polish grammar**: Leave line editing for a future pass or human editor. Focus on STORY.
- **Don't expand lore**: If a scene needs lore the world spec doesn't define, FLAG it. Don't invent.
- **Don't change character fundamentals**: If a character wants to do something their spec says they wouldn't, FLAG it. The author decides, not you.
- **Preserve author voice**: Don't homogenize. Each scene should sound like the POV character, not like an AI.

## Change Justification Template

```markdown
**Change**: [What you changed]
**Location**: {mundo_activo}/sagas/[arc]/[chapter]/[scene].md, paragraph X
**Before**: [Original text — brief excerpt]
**After**: [Revised text — brief excerpt]
**Rationale**: [Which spec rule or design decision drove this change]
```

## Engram

Save revision context with topic_key `nec/{arc-name}/revision` before returning.

## Output

Follow the output format in `prompts/narrative/narrative-revise.md`.
