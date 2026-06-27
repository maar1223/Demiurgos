---
description: Archive a completed narrative arc — update canon and CHANGELOG
agent: Demiurgos-Orchestrator
---

Archive the completed arc "$ARGUMENTS".

WORKFLOW:
1. Launch narrative-archive sub-agent with all arc artifacts
2. Sub-agent:
   - Writes the final summary to Lore/CHANGELOG.md
   - Updates any canon facts discovered during the arc (new lore, refined rules)
   - Saves the archive report to Engram with topic_key "nec/$ARGUMENTS/archive-report"
3. Ask the user if they're ready to close the arc

CRITICAL RULES:
- The archive sub-agent reads everything but ONLY writes to Lore/CHANGELOG.md
- It must NOT modify character sheets or lore files directly — those are author domain
- It flags discovered canon that the author should decide on

CONTEXT:
- Working directory: !`echo -n "$(pwd)"`
- Current project: !`echo -n "$(basename $(pwd))"`
- Arc name: $ARGUMENTS

Read the orchestrator instructions to coordinate this workflow.
