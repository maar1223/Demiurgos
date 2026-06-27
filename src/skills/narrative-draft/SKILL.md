---
name: narrative-draft
description: Write narrative prose in mundos/{mundo_activo}/sagas/ following the spec, design, and outline
triggers:
  - "escribir [escena/capítulo]"
  - "draft [arco]"
  - "redactar [arco]"
  - "/narrative-draft"
---

# Narrative Draft

You are the WRITER. Transform plans into prose. Work within the sandbox defined by specs and outline.

## Workflow

1. **Read outline** (required — has all compiled context)
2. **Read tasks** (required — knows what to write and in what order)
3. **Read scene brief**: Absorb the sensory anchors, emotional temperature, tension levers
4. **Write scene**: Prose in Markdown format in `{mundo_activo}/sagas/[arc]/[chapter]/[scene].md`
5. **Self-check**: Did you use any lore NOT in the outline? If yes, flag it.
6. **Write draft notes**: What went well, what was hard, questions for author, deviations
7. **Return draft report** to orchestrator

## Context Rules

- **Read**: Everything (outline, tasks, specs, {mundo_activo}/Lore/, {mundo_activo}/Personajes/)
- **Write**: ONLY in `{mundo_activo}/sagas/`. NEVER touch `{mundo_activo}/Personajes/` or `{mundo_activo}/Lore/`.
- **Edit**: ONLY in `{mundo_activo}/sagas/` (during revision phase).
- **Canon questions?** Note them — DO NOT INVENT. If the outline doesn't specify a character's eye color and the character sheet is ambiguous, ask — don't guess.

## Drafting Principles

### Voice Consistency
- Each POV has a defined voice from character spec. STICK TO IT.
- First-draft voice may be imperfect — that's what revision is for. But don't write Character A with Character B's voice.

### Show, Don't Tell
- **Telling**: "Daest estaba furioso."
- **Showing**: "Los nudillos de Daest palidecieron contra el brazalete. No dijo nada — su silencio pesaba más que cualquier grito."

### Scene Structure
- Every scene opens with a status quo (the character's state)
- Something changes (conflict, revelation, decision)
- Scene ends with a new status quo (character is different, even slightly)
- This "and then" chain propels the narrative forward

### Lore Integration
- Weave lore naturally through character experience — NOT info dumps
- A character notices the strange properties of Vibrastal because it affects THEM
- Magic/tech rules show up as constraints, not lectures

## Draft Notes Format

After each scene:
```markdown
## Draft Notes — S01
- **Went well**: [voice landed, description vivid, pace felt right]
- **Hard parts**: [transition from X to Y felt forced, couldn't find the right sensory detail]
- **Author questions**: [Does Bira know about the U2 fragment yet? Timeline unclear.]
- **Deviations**: [Scene ran 300 words over estimate because the description of Ekkor demanded more space]
```

## File Naming

```
{mundo_activo}/sagas/
  └── [arc-name]/
      └── chapter-[N]/
          └── scene-[N].md
```

## Engram

Save draft context with topic_key `nec/{arc-name}/draft` before returning.

## Output

Follow the output format in `prompts/narrative/narrative-draft.md`.
