---
description: Fast-forward narrative planning: proposal → specs → design → tasks
agent: Demiurgos-Orchestrator
---

Run the planning phases back-to-back for a new arc named "$ARGUMENTS" or the current arc.

WORKFLOW:
1. Launch narrative-propose → narrative-world-spec ∥ narrative-character-spec → narrative-design → narrative-tasks
2. Show the final planning result (tasks breakdown) to the user
3. Ask if they want to proceed to writing

CONTEXT:
- Working directory: !`echo -n "$(pwd)"`
- Current project: !`echo -n "$(basename $(pwd))"`
- Arc name: $ARGUMENTS (if empty, detect current active arc)

Read the orchestrator instructions to coordinate this workflow.
