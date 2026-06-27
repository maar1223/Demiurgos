---
description: Continue the next dependency-ready phase for a narrative arc
agent: Demiurgos-Orchestrator
---

Continue the current narrative arc's next ready phase.

WORKFLOW:
1. Search Engram for the current arc's latest phase: `mem_search(query: "nec/{current-arc}/*", project: "{project}")`
2. Determine which phase is next in the dependency graph
3. Launch the appropriate sub-agent for that phase
4. Present the result and ask what's next

CONTEXT:
- Working directory: !`echo -n "$(pwd)"`
- Current project: !`echo -n "$(basename $(pwd))"`
- Optional arc name: $ARGUMENTS

Read the orchestrator instructions to coordinate this workflow.
