---
description: Execute narrative writing — outline context then draft scenes
agent: Demiurgos-Orchestrator
---

Execute the writing phase for the current arc "$ARGUMENTS" or carry out specific write instructions.

WORKFLOW:
1. If starting fresh: launch narrative-outline to prepare full context (lore, characters, beats, tasks)
2. Launch narrative-draft to write scenes/chapters in Relatos/
3. Optionally launch narrative-revise for creative revision passes

CRITICAL RULES:
- The writer sub-agents read Lore/ and Personajes/ but ONLY write/edit in Relatos/
- No lore expansion or character sheet modification during writing
- If canon questions arise during drafting, flag them — don't invent

CONTEXT:
- Working directory: !`echo -n "$(pwd)"`
- Current project: !`echo -n "$(basename $(pwd))"`
- Arc name: $ARGUMENTS

Read the orchestrator instructions to coordinate this workflow.
