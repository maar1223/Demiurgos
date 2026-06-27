---
description: Show the complete list of narrative commands, workflow guide, and help
agent: Demiurgos-Orchestrator
---

Display the Demiurgos Narrative Engine command reference and workflow guide.

## What to show

When the user runs `/narrative-help`, display a clear, structured help screen:

### 1. The Narrative Cycle (NEC)

Show the dependency graph visually:

```
/narrative-new "arc-name"
    ├── EXPLORE (auto) → PROPOSE → [author approves]
    ├── /narrative-continue → WORLD SPEC ∥ CHARACTER SPEC
    ├── /narrative-continue → DESIGN (beats, outline)
    ├── /narrative-continue → TASKS (scene breakdown)
    ├── /narrative-write → OUTLINE → DRAFT → REVISE
    └── /narrative-verify → /narrative-archive
```

### 2. Command Reference

List ALL commands with their purpose and when to use them:

**Startup:**
- `/narrative-init` — Initialize NEC for this project (run once)
- `/narrative-onboard` — Guided tour of the full system

**Planning:**
- `/narrative-explore "topic"` — Investigate lore without creating files
- `/narrative-new "arc-name"` — Start a new arc (explore + propose)
- `/narrative-ff "arc-name"` — Fast-forward: proposal → specs → design → tasks
- `/narrative-continue` — Run the next ready phase

**Writing:**
- `/narrative-write "arc-name"` — Execute writing (outline context + draft scenes)
- `/narrative-continue` — Continue writing the next batch

**Validation:**
- `/narrative-verify "arc-name"` — Check canon, continuity, consistency
- `/narrative-archive "arc-name"` — Close arc, update CHANGELOG

**Help:**
- `/narrative-help` — This guide

### 3. Phase Status

If the user is in the middle of an arc, check Engram for the current phase and show:
- What phase is complete (✅)
- What phase is in progress (🔄)
- What phase comes next (🔲)
- The exact command to type

### 4. Quick Tips

- `/narrative-continue` is your best friend — auto-detects the next phase
- `/narrative-ff` for speed when you already know the story
- `/narrative-verify` before archive — ALWAYS
- Domain boundaries are enforced: planner≠writer≠validator

## Rules

- This is a HELP command. Be warm and welcoming.
- If the user hasn't run `/narrative-init` yet, tell them to run it first.
- Keep it concise but complete. Don't overwhelm.
- Match the user's language (Spanish for Vibrantes).
