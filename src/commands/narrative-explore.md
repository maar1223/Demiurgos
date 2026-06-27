---
description: Explore a narrative idea — investigate lore without creating files
agent: Demiurgos-Orchestrator
---

Investigate a narrative idea or question named "$ARGUMENTS".

WORKFLOW:
1. Launch narrative-explore sub-agent to read lore files, character sheets, and existing arcs
2. Present findings and compare approaches if applicable
3. No files are created — exploration output stays in Engram or is presented inline

CONTEXT:
- Working directory: !`echo -n "$(pwd)"`
- Current project: !`echo -n "$(basename $(pwd))"`
- Topic: $ARGUMENTS

Do NOT create proposal or spec files — this is exploration only.
