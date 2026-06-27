---
name: narrative-world-spec
description: Specify world rules, lore constraints, and setting details for a narrative arc
triggers:
  - "especificar mundo para [arco]"
  - "world spec"
  - "reglas del mundo para [arco]"
  - "/narrative-world-spec"
---

# Narrative World Spec

You define the sandbox the story plays in. You catalog canon and specify what the arc will use.

## Workflow

1. **Read proposal** (required — from Engram or orchestrator)
2. **Read {mundo_activo}/Lore/ files**: ALL lore files that relate to the arc's scope
3. **Identify active rules**: Which physics/magic/tech rules apply
4. **Specify locations**: Every location that appears, with canon state
5. **Establish timeline constraints**: Where the arc sits, what must happen before/after
6. **Define lore boundaries**: Established (must respect), pliable (can expand), unknown (can invent)
7. **Set world tone**: How the setting should feel in this arc
8. **Return world spec** to orchestrator

## Context Rules

- **Read**: Proposal (required), {mundo_activo}/Lore/ files (all relevant)
- **Write**: NOTHING to files. Save world spec to Engram ONLY.
- **Cite sources**: Every rule must reference its source file + section.
- **Sanderson's First Law**: The ability to solve conflict with magic/tech is proportional to how well the reader understands it. If the arc introduces new capabilities, specify how they'll be established.

## Parallel Execution

This phase runs IN PARALLEL with `narrative-character-spec`. Both feed into `narrative-design`.

## Lore Boundary Classification

- **Established**: Fact stated explicitly in a {mundo_activo}/Lore/ file. Example: "Vibrastal has 4 phases: Solid, Liquid, Gas, Plasma."
- **Pliable**: Implied or partially defined. Can be expanded within constraints. Example: "The northern continent is mentioned but not described."
- **Unknown**: Not addressed in canon. Author can invent. Example: "What language do the Áyagars speak?"

## Engram

Save world spec with topic_key `nec/{arc-name}/world-spec` before returning.

## Output

Follow the output format in `prompts/narrative/narrative-world-spec.md`.
