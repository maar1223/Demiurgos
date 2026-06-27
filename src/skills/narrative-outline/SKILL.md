---
name: narrative-outline
description: Compile complete context package for the writing phase — lore, characters, scene briefs
triggers:
  - "preparar contexto para escribir"
  - "outline context"
  - "compilar lore para draft"
  - "/narrative-outline"
---

# Narrative Outline

You are the research assistant for the writer. Compile everything the writer needs BEFORE they start drafting.

## Workflow

1. **Read tasks** (required)
2. **Read world spec + character spec** (required)
3. **Read actual {mundo_activo}/Lore/ files**: Get exact quotes, not paraphrases
4. **Read actual {mundo_activo}/Personajes/ files**: Get canonical descriptions and voice
5. **Compile lore context**: Relevant rules, locations, timeline with citations
6. **Compile character context**: Each character's state, voice, knowledge, recent history
7. **Write scene briefs**: Prerequisites + sensory anchors + emotional temperature + tension levers per scene
8. **Build continuity checklist**: Facts that must carry between scenes
9. **Flag gaps**: If lore doesn't specify something the scene needs, flag it
10. **Return outline** to orchestrator

## Context Rules

- **Read**: Tasks + specs + {mundo_activo}/Lore/ files + {mundo_activo}/Personajes/ files
- **Write**: NOTHING to files. Save outline to Engram ONLY.
- **Cite EXACTLY**: Every fact must have file + section reference. No paraphrasing from memory.
- **Flag, don't fix**: If you find gaps or conflicts, flag them — don't resolve silently.

## Scene Brief Template

```
Scene: S01 — Opening Image
Prerequisites:
  - Reader knows nothing yet (first scene of arc)
  - Character [X] is in [location] doing [activity]
Sensory anchors:
  - Sound: [ambient sounds of location]
  - Sight: [key visual details]
  - Smell/Texture: [atmospheric details]
Emotional temperature:
  - Going in: [character] feels [emotion] about [situation]
  - Coming out: [emotional shift target]
Tension levers:
  - What's at stake: [immediate concern]
  - What can go wrong: [imminent threat or fear]
```

## Continuity Checklist Rules

Track facts that must be consistent across scenes:
- Physical objects (character has item X in scene 1, must still have it in scene 2 unless shown losing it)
- Knowledge states (character learns fact Y in scene 3, must know it in scene 5)
- Emotional states (character is angry at end of scene 2, enters scene 3 still angry unless transition shown)
- Timeline markers (scene 4 happens "two days later" — track the date)

## Engram

Save outline with topic_key `nec/{arc-name}/outline` before returning.

## Output

Follow the output format in `prompts/narrative/narrative-outline.md`.
