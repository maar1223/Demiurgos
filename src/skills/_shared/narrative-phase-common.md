# Narrative Phase Common

Common fields and contracts shared across all Demiurgos narrative phases.

## Result Contract

Every phase MUST return a result with these fields:

```json
{
  "status": "complete" | "partial" | "failed" | "blocked",
  "executive_summary": "One paragraph summary of what this phase produced",
  "artifacts": {
    "...": "Phase-specific artifact structure"
  },
  "next_recommended": "name of the next phase to run",
  "risks": [
    "Risk 1 — severity and impact",
    "Risk 2"
  ],
  "skill_resolution": "injected" | "fallback-registry" | "fallback-path" | "none",
  "canon_flags": [
    {
      "type": "conflict" | "gap" | "ambiguity",
      "description": "...",
      "sources_cited": ["file:section", "file:section"],
      "recommendation": "..."
    }
  ]
}
```

### Status Values

- `complete`: Phase ran successfully, artifact is ready for the next phase
- `partial`: Phase started but didn't finish (batch processing). Context saved for continuation.
- `failed`: Phase encountered an unrecoverable error. Artifact may be incomplete.
- `blocked`: Phase cannot proceed due to missing dependency or unresolved canon question.

### Risk Classification

- **CRITICAL**: Canon violation imminent. STOP and ask author.
- **HIGH**: Significant complexity, scope creep, or continuity risk.
- **MEDIUM**: Manageable with attention. Flag for author awareness.
- **LOW**: Cosmetic or easily fixable.

### Skill Resolution

- `injected`: Orchestrator resolved skills and injected compact rules successfully.
- `fallback-registry`: Skill registry found but compact rules section missing or malformed.
- `fallback-path`: Skill registry not found in Engram, fell back to `.atl/skill-registry.md`.
- `none`: No skill registry found anywhere. Running without project standards.

### Canon Flags

When a sub-agent discovers canon issues during its phase, it must flag them:

- **conflict**: Two sources say different things. Example: "Character spec says age 22, timeline says born 25 years ago."
- **gap**: Required information is missing. Example: "Scene needs the northern continent's climate, but it's not described in any {mundo_activo}/Lore/ file."
- **ambiguity**: Information exists but is unclear. Example: "Lore says 'the U2 fragment was lost' — lost means destroyed? Hidden? Taken?"

## Phase Dependencies

```
explore ─┐ (optional, but recommended for new arcs)
          │
          ├─→ propose ──→ world-spec ──┬──→ design ──→ tasks ──→ outline ──→ draft ──→ revise ──→ verify ──→ archive
          │                             │
          │              character-spec ─┘
```

- `world-spec` and `character-spec` run in PARALLEL (independent).
- All other phases are SEQUENTIAL (dependency on previous phase).
- `explore` is optional for continuation arcs but recommended for new arcs.

## Domain Boundaries (ENFORCED BY ORCHESTRATOR)

| Domain | Can Read | Can Write/Edit |
|--------|----------|----------------|
| **Planner** (explore, propose, world-spec, character-spec, design, tasks) | Everything | NOTHING (artifacts only in Engram/openspec) |
| **Writer** (outline, draft, revise) | Everything | ONLY `{mundo_activo}/sagas/` |
| **Validator** (verify, archive) | Everything | ONLY `{mundo_activo}/Lore/CHANGELOG.md` |
