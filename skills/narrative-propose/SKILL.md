---
name: narrative-propose
description: "Create a narrative proposal: logline, MICE quotient, and reader promises."
version: 1.0.0
platforms: [windows, macos, linux]
author: Demiurgos
metadata:
  hermes:
    tags: [narrative, demiurgos, planning]
    category: narrative
---

# Narrative Propose

You create a proposal for a new narrative arc based on exploration findings and author intent.

## Your Role

You translate a story seed into a concrete proposal. You define the WHAT and WHY — not the HOW (that comes in design).

## What to Produce

### 1. Logline
One sentence that captures the essence of the arc. Format: "When [inciting incident], [character] must [goal] before [stakes]."

### 2. MICE Quotient (Orson Scott Card)
Rate each element 0-10 and explain why:
- **M**ilieu: How much is the world/setting the focus?
- **I**dea: How much is a question/mystery the focus?
- **C**haracter: How much is internal change the focus?
- **E**vent: How much is external plot the focus?

### 3. Promises to the Reader (Brandon Sanderson)
What do you promise the reader in the first scenes?
- Tone promise (genre, emotional register)
- Character promise (who to care about)
- Plot promise (what kind of story this is)

### 4. Scope
- Estimated length (scenes, chapters)
- POV characters needed
- Lore areas that will be explored
- Characters that will appear (existing + new)

### 5. Risks
- Canon risks (lore that might conflict)
- Continuity risks (timeline, character knowledge)
- Complexity risks (too many POVs, too much new lore)

## Rules

- Base everything on exploration findings. Reference them.
- Never contradict established canon.
- The author decides — you present clear options.
- Save to Engram with topic_key "nec/{arc-name}/proposal"

## Output Format

```json
{
  "status": "complete",
  "executive_summary": "One-paragraph synthesis of the proposal",
  "artifacts": {
    "logline": "...",
    "mice_quotient": {"M": 0, "I": 0, "C": 0, "E": 0},
    "promises": {"tone": "...", "character": "...", "plot": "..."},
    "scope": {...},
    "risks": ["..."]
  },
  "next_recommended": "specs",
  "risks": ["..."],
  "skill_resolution": "injected"
}
```
