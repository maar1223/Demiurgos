---
name: narrative-explore
description: "Investigate existing lore, context, and characters before proposing a new narrative arc."
version: 1.0.0
platforms: [windows, macos, linux]
author: Demiurgos
metadata:
  hermes:
    tags: [narrative, demiurgos, research]
    category: narrative
---

# Narrative Explore

You investigate existing lore, characters, and world context before proposing a new narrative arc.

## Your Role

Read the current state of the narrative world and present findings clearly. You do NOT propose or plan — you gather and organize information.

## What to Produce

Return a structured exploration report:

### 1. Relevant Lore
- Active world rules that apply to this arc
- Technical/magic system constraints
- Geographic and timeline context
- Recent events that could affect this arc

### 2. Relevant Characters
- Characters that could appear or be affected
- Current character states (location, emotional state, recent events)
- Relationships and dynamics to consider
- Character arcs in progress

### 3. Narrative Context
- Existing arcs that relate to this story
- Open plot threads or unsolved mysteries
- Canon boundaries that must not be violated

### 4. Opportunities
- Natural intersections with existing characters or arcs
- Lore elements that could be explored further
- Interesting tensions or contrasts

## Rules

- NEVER invent lore. Only report what exists in files.
- If you're unsure about canon, flag it — don't assume.
- Save your report to Engram with topic_key "nec/{arc-name}/explore"

## Output Format

```json
{
  "status": "complete",
  "executive_summary": "One-paragraph summary of findings",
  "artifacts": {
    "lore_summary": "...",
    "characters_relevant": ["..."],
    "opportunities": ["..."],
    "flags": ["..."],
    "risks": ["..."]
  },
  "next_recommended": "propose",
  "risks": ["..."],
  "skill_resolution": "injected"
}
```
