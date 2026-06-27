---
description: Initialize NEC context for the current narrative project
agent: Demiurgos-Orchestrator
---

Follow the Narrative Engine Cycle initialization workflow.

WORKFLOW:
1. Detect the narrative project structure (Lore/, Personajes/, Relatos/ directories)
2. Cache narrative conventions, world rules, and character roster
3. Detect artifact persistence (Engram/openspec/hybrid)
4. Register the narrative skill registry
5. Create a project context memory with topic_key "narrative-init/{project}"

CONTEXT:
- Working directory: !`echo -n "$(pwd)"`
- Current project: !`echo -n "$(basename $(pwd))"`

ENGINE NOTE:
This must run once per project before any other narrative command. Sub-agents handle persistence automatically.

Read the orchestrator instructions to coordinate this workflow. Do NOT execute phase work inline — delegate to sub-agents.
