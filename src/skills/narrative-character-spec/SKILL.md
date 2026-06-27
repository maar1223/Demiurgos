---
name: narrative-character-spec
description: Specify characters, arcs, relationships, and voice for a narrative arc
triggers:
  - "especificar personajes para [arco]"
  - "character spec"
  - "fichas de personaje para [arco]"
  - "/narrative-character-spec"
---

# Narrative Character Spec

You define who the story is about and how they grow. You read character sheets and specify arc demands.

## Workflow

1. **Read proposal** (required)
2. **Read {mundo_activo}/Personajes/ files**: ALL character sheets for characters in the arc's scope
3. **Build roster**: Every character with current state, Stal rank, location
4. **Design arcs**: Each POV character's change trajectory (type, conflict, lie→truth)
5. **Map relationships**: Key dynamics and how they evolve
6. **Specify voice**: Narrative distance, register, internal monologue style per POV
7. **Define constraints**: Canon traits that must be respected, knowledge boundaries
8. **Return character spec** to orchestrator

## Context Rules

- **Read**: Proposal (required), {mundo_activo}/Personajes/ files (all relevant), {mundo_activo}/Lore/ files (for context)
- **Write**: NOTHING to files. Save character spec to Engram ONLY.
- **Cite sources**: Every trait must reference its source file.
- **Knowledge boundaries are SACRED**: Never let a character know what they shouldn't.

## Parallel Execution

This phase runs IN PARALLEL with `narrative-world-spec`. Both feed into `narrative-design`.

## Arc Types (Sanderson)

- **Positive change**: Character overcomes flaw, grows. Most common.
- **Negative change**: Character descends, fails, or is corrupted. Tragedy.
- **Flat arc**: Character doesn't change but changes the world around them. Mentor/heroic archetype.
- **Fall and rise**: Character breaks then rebuilds.

## Knowledge Boundaries

For each character, explicitly state:
- What they KNOW (canon facts, recent events, other characters' secrets)
- What they BELIEVE (which may be wrong)
- What they DON'T KNOW (key information the reader has but they don't)

This prevents POV contamination during drafting.

## Engram

Save character spec with topic_key `nec/{arc-name}/character-spec` before returning.

## Output

Follow the output format in `prompts/narrative/narrative-character-spec.md`.
