---
description: Verify narrative canon, continuity, and consistency
agent: Demiurgos-Orchestrator
---

Verify the current arc "$ARGUMENTS" against its specs and canon.

WORKFLOW:
1. Launch narrative-verify sub-agent with:
   - The arc's world-spec (world rules, lore constraints)
   - The arc's character-spec (character sheets, arcs, traits)
   - The arc's tasks (what was supposed to be written)
   - The draft (what was actually written)
2. Sub-agent compares draft against specs and canon
3. Reports findings: canon violations, continuity errors, consistency issues

REPORT FORMAT:
- CRITICAL: canon violations (contradicts established lore)
- WARNING: continuity issues (timeline, geography, character knowledge)
- SUGGESTION: consistency improvements (tone, voice, pacing)

CONTEXT:
- Working directory: !`echo -n "$(pwd)"`
- Current project: !`echo -n "$(basename $(pwd))"`
- Arc name: $ARGUMENTS

Read the orchestrator instructions to coordinate this workflow.
