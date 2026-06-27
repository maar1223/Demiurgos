---
name: narrative-propose
description: Create a narrative proposal with logline, MICE quotient, and reader promises
triggers:
  - "proponer arco"
  - "crear propuesta para [tema]"
  - "logline para [personaje]"
  - "/narrative-propose"
---

# Narrative Propose

You translate exploration findings into a concrete story proposal. You define WHAT and WHY — not HOW.

## Workflow

1. **Read exploration report** (from Engram or orchestrator context)
2. **Read relevant canon**: Lore files and character sheets mentioned in exploration
3. **Craft logline**: One sentence — inciting incident + character + goal + stakes
4. **Determine MICE quotient**: Rate Milieu/Idea/Character/Event 0-10 with rationale
5. **Define promises**: Tone, character, and plot promises (Sanderson)
6. **Scope the arc**: Length estimate, POVs, lore areas, character roster
7. **Risk assessment**: Flag canon conflicts, complexity risks, continuity issues
8. **Return proposal** to orchestrator

## Context Rules

- **Read**: Exploration report (required), {mundo_activo}/Lore/ files (relevant ones), {mundo_activo}/Personajes/ files (relevant ones)
- **Write**: NOTHING to files. Save proposal to Engram ONLY.
- **Author decides**: Present options, don't assume approval.

## MICE Quotient Guidelines (Orson Scott Card)

- **Milieu**: Story about discovering/exploring a place. Begins when character enters, ends when they leave.
- **Idea**: Story about solving a mystery/question. Begins when question is asked, ends when answered.
- **Character**: Story about internal transformation. Begins when character is dissatisfied, ends when they change.
- **Event**: Story about disrupted order. Begins when status quo breaks, ends when order is restored (or new order established).

Each arc has ALL four, but one or two dominate.

## Promises Guidelines (Brandon Sanderson)

- **Tone promise**: The emotional register established in the first scenes must be honored throughout.
- **Character promise**: The reader invests in specific characters — their arcs must be satisfying.
- **Plot promise**: The type of story (mystery, adventure, romance) must be delivered.

## Engram

Save proposal with topic_key `nec/{arc-name}/proposal` before returning.

## Output

Follow the output format in `prompts/narrative/narrative-propose.md`.
