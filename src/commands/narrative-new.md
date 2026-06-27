---
description: Start a new narrative arc — runs exploration then creates a proposal
agent: Demiurgos-Orchestrator
---

Follow the Narrative Engine Cycle workflow for starting a new arc named "$ARGUMENTS".

WORKFLOW:
1. Launch narrative-explore sub-agent to investigate existing lore, characters, and context for this arc
2. Present the exploration summary to the user
3. Launch narrative-propose sub-agent to create a proposal based on the exploration (logline, MICE quotient, promises)
4. Present the proposal summary and ask the user if they want to continue with world/character specs and design

CONTEXT:
- Working directory: !`echo -n "$(pwd)"`
- Current project: !`echo -n "$(basename $(pwd))"`
- Arc name: $ARGUMENTS
- Execution mode: ask/cache per orchestrator
- Artifact store mode: ask/cache per orchestrator

ENGRAM NOTE:
Sub-agents handle persistence automatically using the selected artifact store. In engram/hybrid, each phase saves with topic_key "nec/$ARGUMENTS/{type}".

Read the orchestrator instructions to coordinate this workflow. Do NOT execute phase work inline — delegate to sub-agents.
