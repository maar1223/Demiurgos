# Persistence Contract

How narrative artifacts are stored and retrieved across phases and sessions.

## Backend Modes

| Mode | Storage | Pros | Cons |
|------|---------|------|------|
| `engram` | Engram persistent memory | Fast, survives sessions, no files | Requires Engram MCP |
| `openspec` | Files in `openspec/` directory | Shareable, git-tracked | Slower, file clutter |
| `hybrid` | Both engram + files | Best of both | More tokens per operation |
| `none` | Inline only | Zero setup | Lost on session close |

## Topic Key Convention

All narrative artifacts use this key format:
```
nec/{arc-name}/{artifact-type}
```

| Artifact | Topic Key |
|----------|-----------|
| Exploration | `nec/{arc-name}/explore` |
| Proposal | `nec/{arc-name}/proposal` |
| World spec | `nec/{arc-name}/world-spec` |
| Character spec | `nec/{arc-name}/character-spec` |
| Design | `nec/{arc-name}/design` |
| Tasks | `nec/{arc-name}/tasks` |
| Outline | `nec/{arc-name}/outline` |
| Draft | `nec/{arc-name}/draft` |
| Revision | `nec/{arc-name}/revision` |
| Verify report | `nec/{arc-name}/verify-report` |
| Archive report | `nec/{arc-name}/archive-report` |
| Project init | `narrative-init/{project}` |
| Skill registry | `skill-registry` |

## Artifact Read/Write Rules

- **Orchestrator passes topic keys**, not content. Sub-agents read directly from the backend.
- **Required dependencies** must be read first. Example: `narrative-design` reads `proposal`, `world-spec`, and `character-spec` before producing `design`.
- **Save BEFORE returning**. Every phase saves its artifact to Engram/openspec before returning to the orchestrator.
- **Engram saves use `capture_prompt: false`** for automated phase artifacts.
- **Merging, not overwriting**: When resuming a phase (e.g., apply-progress for code), merge new data with existing. For narrative, phases are generally run once and the artifact is replaced on re-run.

## File-Based Artifacts (openspec mode)

When using `openspec` or `hybrid` mode, artifacts are saved as Markdown files:
```
openspec/
  └── changes/
      └── {arc-name}/
          ├── proposal.md
          ├── world-spec.md
          ├── character-spec.md
          ├── design.md
          ├── tasks.md
          ├── outline.md
          ├── draft-context.md
          ├── revision.md
          ├── verify-report.md
          └── archive-report.md
```
