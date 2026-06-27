---
description: Walk through the full Narrative Engine Cycle using the current world
agent: Demiurgos-Orchestrator
---

Guide the user through a complete Narrative Engine Cycle using their real world and characters.

WORKFLOW:
1. Detect the project lore structure and explain each directory's role
2. Walk through each phase: explore → propose → world-spec → character-spec → design → tasks → outline → draft → revise → verify → archive
3. At each phase, explain what happens, what artifacts are produced, and what the author decides
4. Use real lore files and characters for concrete examples
5. Let the user drive—explain, don't execute unless they ask

ONBOARDING FLOW:
- Phase 0: Show how narrative-init works
- Phase 1: Show narrative-new with a real character/world example
- Phase 2: Show narrative-write with a brief scene example
- Phase 3: Show narrative-verify and narrative-archive
- Summary: Explain the domain boundaries (planner≠writer≠validator)

CONTEXT:
- Working directory: !`echo -n "$(pwd)"`
- Current project: !`echo -n "$(basename $(pwd))"`

This is a TEACHING command. Explain the concepts, show the flow, let the user learn.
