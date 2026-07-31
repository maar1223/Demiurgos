# Skill Registry — Demiurgos / Vibrantes

> Generated: 2026-05-10 via sdd-init
> Updated: 2026-06-26 via sdd-init (added narrative SDD skills + narrative-vision)
> Mode: engram (no openspec/)

---

## Project Convention Files

| File | Purpose |
|------|---------|
| `Agente_Maestro.md` | Constitution: IA identity, tone, Sacred Symmetry, narrative structure, anti-cliché rules |
| `LEEME.md` | Entry point, directory map, workflow for character/history/lore/canon skills |
| `.opencode/instructions.md` | Bootstrap instructions: read Agente_Maestro.md → LEEME.md → use skills/ → canon sacred → epic tone in Spanish |

---

## Project Skills (`skills/` — resident)

### `actualizar_lore.md`

**Trigger:** Expand/correct world lore without breaking canon.
**Path:** `skills/actualizar_lore.md`

**Compact Rules:**
1. Stalers and Sacred Symmetry (Eneatype↔Stal) are immutable physical laws — never create new Stalers or break the mapping.
2. Allowed: creative Staler uses, new locations, creatures, tech, traditions, factions.
3. Classify change by TIER before execution (T1=intocable, T2=actualizable, T3=documentable).
4. Verify conflicts with existing lore files before proposing changes.
5. User must approve proposed changes before execution.
6. Every change must be logged in `mundos/vibrantes/Lore/CHANGELOG.md`.
7. New terms must be added to `mundos/vibrantes/Lore/Indice_de_Terminos.md`.
8. Consult the Quick Guide (Apéndice B) for yes/no/⚠️ decisions.
9. Cross-reference all additions via Apéndice C (what to review for each change type).
10. Location changes affect `mundos/vibrantes/Lore/Politica_y_Territorios/*` and `mundos/vibrantes/Lore/Planeta_Vibral.md`.

### `crear_personaje.md`

**Trigger:** Create a character adapted by narrative rank.
**Path:** `skills/crear_personaje.md`

**Compact Rules:**
1. First question is always the character's narrative rank (Relleno/Secundario/Principal/Inmortal).
2. Each rank has a fixed number of questions (7/12/18/10) — do not skip or add.
3. Sacred Symmetry is law: Stal (1-9) derives directly from Eneatype (1-9).
4. Never assign a power that doesn't match the base Eneatype.
5. Always consult `mundos/vibrantes/Lore/*` and the template catalog (`_catalog.json`) for validation.
6. The optional Villain Profile phase applies only to active antagonists with moral justification.
7. Every dialogue line must resonate with the character's Dominant Passion.
8. Actions must align with the 58 Alignment system (see Catalog Discovery Protocol in AGENTS.md).
9. Character evolution must be gradual through matrices, never abrupt.
10. Always output to `mundos/vibrantes/Personajes/` with the template format.

### `escribir_historia.md`

**Trigger:** Write complete narrative stories with structured prompts.
**Path:** `skills/escribir_historia.md`

**Compact Rules:**
1. Phase 0 (Semilla) defines logline (25 words), MICE type, theme, and reader contract before touching any catalogs.
2. Phase 1 sets scope (length, universe position, provisional title).
3. Phase 2 identifies protagonist(s) — existing from `mundos/vibrantes/Personajes/` or new via `crear_personaje.md`.
4. Phase 3 selects narrative pieces (Trama, Conflicto, Dilema, Tema) filtered by the MICE type chosen in Phase 0.
5. Phase 4 picks ONE Snyder story archetype and maps all 15 beats (see Catalog Discovery Protocol in AGENTS.md). Propp is deprecated — do not use.
6. Phase 5 populates characters: antagonist, supporting cast, fillers.
7. Phase 6 sets the scene: nation, scenario, era — must match lore.
8. Phase 7 generates beat-aligned outline → user approves → write chapter by chapter.
9. Tone: epic-mystical; narrator: 3rd person limited; sensory descriptions.
10. 1500-4000 words per chapter recommended.
11. Post-writing: validate canon with `verificar_canon.md`.
12. Style guide: natural dialogue with lore jargon (Stal, Flud, Sold, Dvex, Ayagar).

### `verificar_canon.md`

**Trigger:** Validate any content against established lore.
**Path:** `skills/verificar_canon.md`

**Compact Rules:**
1. Identify what to verify: Personaje, Relato, Escenario, or Elemento suelto.
2. Phase 1 checks Sacred Symmetry: Eneatype↔Stal match, Staler authenticity.
3. Phase 2 checks Personality Archetype against the 7x7 matrix.
4. Phase 3 checks Moral Alignment against the 58 alignments hierarchy.
5. Phase 4 checks Narrative Role (Trama, Conflicto, Dilema, Tema, Dinámicas).
6. Phase 5 cross-references Biology, Technology, Locations against lore.
7. Output contradictions as three sections: ✅ Coherencias, ⚠️ Advertencias, ❌ Violaciones.
8. ❌ Rule of Gold: Mark violations with exact file reference, ask user if intentional.
9. Never correct without consulting — the author may have a narrative reason.
10. Always list which files were consulted in the final output.

---

## Demiurgos Agent Skills (`Demiurgos/src/skills/` — SDD sub-agents)

### `narrative-idea`

**Trigger:** Manage Banco de Ideas — capture, browse, search, sync, promote narrative ideas.
**Path:** `Demiurgos/src/skills/narrative-idea/SKILL.md`
**Type:** Support | **Tier:** infrastructure | **Scope:** idea-bank

**Compact Rules:**
1. Domain boundary: write ONLY to `mundos/vibrantes/Ideas/` and Engram `nec/ideas/`. NEVER touch `mundos/vibrantes/Lore/`, `mundos/vibrantes/Personajes/`, or `mundos/vibrantes/sagas/`.
2. Capture workflow: receive idea → generate UUIDv4 id → determine type from CLOSED enum (`idea_loose`, `character_seed`, `scene_seed`, `dialogue`, `concept`; character ideas → `character_seed` NEVER `personaje`) → generate slug `{YYYY-MM-DD}-{first-4-meaningful-words}` (skip stopwords + single-char tokens like digits) → auto-tag content → write `mundos/vibrantes/Ideas/{slug}.md` with EXACT YAML schema (id, slug, timestamp-ISO8601, source, type, tags, status) → save to Engram `nec/ideas/{slug}`.
3. Sync workflow: read Google Sheets unprocessed rows → transcribe voice via faster-whisper → write local files → mark processed=true.
4. Auto-tagging: always analyze content for type, entities (from Lore/Personajes/), and themes. Manual tags are added to auto-tags (union, never replace). Tags are free-form.
5. Browse/search: parse YAML frontmatter from `mundos/vibrantes/Ideas/*.md`, filter by type/tags/date range or keyword search.
6. Promote: handoff idea to orchestrator for narrative-propose. Do NOT create arc files.
7. Hybrid storage: every idea exists in both `mundos/vibrantes/Ideas/{slug}.md` (git-tracked) and Engram `nec/ideas/{slug}` (semantic search).
8. Slug collision: append `-2`, `-3` to filename.
9. Schema enforcement: YAML frontmatter is CLOSED — 7 fields only (id, slug, timestamp, source, type, tags, status). FORBIDDEN: `date` (use `timestamp`), `personaje` (use `character_seed`), extra fields (`entidades`, `notas`), omitting `id`/`source`/`status`.

---

### `narrative-vision`

**Trigger:** Analyze images with Qwen 3.6 Plus vision for narrative context.
**Path:** `Demiurgos/src/prompts/narrative/narrative-vision.md`
**Type:** Support | **Tier:** vision | **Scope:** image-analysis

**Compact Rules:**
1. Analyze uploaded images for narrative-relevant context (characters, locations, mood, era).
2. Return structured findings: description, narrative elements detected, confidence levels.
3. Never interpret beyond what the image shows — mark ambiguities clearly.
4. Cross-reference detected elements with Lore/ and Personajes/ files when possible.
5. Return analysis to orchestrator in the format from narrative-vision.md prompt.

---

## Narrative SDD Skills — Complete Set (`Demiurgos/src/skills/` — project-level)

### `narrative-archive`
**Trigger:** Close a narrative arc — update CHANGELOG, record canon discoveries.
**Path:** `Demiurgos/src/skills/narrative-archive/SKILL.md`
**Compact Rules:**
1. Read ALL arc artifacts before archiving.
2. Write ONLY to `Lore/CHANGELOG.md` — never modify Lore/ or Personajes/ directly.
3. Non-spoiler principle: CHANGELOG entries must not spoil reveals for arcs written later but set earlier.
4. Catalog canon discoveries with source scene, impact scope, and confidence (CONFIRMED vs DISCOVERED).
5. Every canon discovery needs author approval before integration into Lore/ files.

### `narrative-character-spec`
**Trigger:** Specify characters, arcs, relationships, and voice for a narrative arc.
**Path:** `Demiurgos/src/skills/narrative-character-spec/SKILL.md`
**Compact Rules:**
1. Read ALL Personajes/ files for characters in scope — cite exact sources.
2. Knowledge boundaries are sacred: document what each character KNOWS, BELIEVES, and DOESN'T KNOW.
3. Design arcs with Sanderson types: positive change, negative change, flat arc, fall and rise.
4. Runs IN PARALLEL with narrative-world-spec; both feed narrative-design.
5. Write NOTHING to files — save character spec to Engram only.

### `narrative-design`
**Trigger:** Design narrative structure with Snyder beats, chapter outline, and scene sequencing.
**Path:** `Demiurgos/src/skills/narrative-design/SKILL.md`
**Compact Rules:**
1. Requires proposal + world spec + character spec as input.
2. Map all 15 Snyder beats to arc-specific events — structure, not formula.
3. Every scene must serve at least one: character arc, world exploration, or plot advancement.
4. POV switches must be justified — what does THIS POV see that others don't?
5. Health check: alternate tension/release, close MICE threads, deliver on Sanderson promises.
6. Write NOTHING to files — save design to Engram only.

### `narrative-draft`
**Trigger:** Write narrative prose in Relatos/ following the spec, design, and outline.
**Path:** `Demiurgos/src/skills/narrative-draft/SKILL.md`
**Compact Rules:**
1. Read outline and tasks before writing — they are required context.
2. Write ONLY in `Relatos/`. NEVER touch `Personajes/` or `Lore/`.
3. Edit ONLY in `Relatos/` (during revision phase).
4. If canon is ambiguous and the outline doesn't specify, ASK — never guess.
5. Self-check after each scene: did you use lore NOT in the outline? Flag it.

### `narrative-explore`
**Trigger:** Explore existing lore, characters, and narrative context before proposing a new arc.
**Path:** `Demiurgos/src/skills/narrative-explore/SKILL.md`
**Compact Rules:**
1. Gather and organize — never propose.
2. Read everything: Lore/, Personajes/, sagas/, and Engram.
3. Write NOTHING to files — save exploration report to Engram only.
4. Every fact must come from a source file or Engram — never invent.

### `narrative-outline`
**Trigger:** Compile complete context package for the writing phase.
**Path:** `Demiurgos/src/skills/narrative-outline/SKILL.md`
**Compact Rules:**
1. Read tasks + specs + Lore/ files + Personajes/ files.
2. Cite EXACTLY — every fact must have file + section reference.
3. Scene briefs: prerequisites + sensory anchors + emotional temperature + tension levers.
4. Build continuity checklist: physical objects, knowledge states, emotional states, timeline markers.
5. Flag gaps — don't resolve silently. Write NOTHING to files.

### `narrative-propose`
**Trigger:** Create a narrative proposal with logline, MICE quotient, and reader promises.
**Path:** `Demiurgos/src/skills/narrative-propose/SKILL.md`
**Compact Rules:**
1. Requires exploration report as input.
2. Craft logline: inciting incident + character + goal + stakes in one sentence.
3. Determine MICE quotient (Milieu/Idea/Character/Event) rated 0-10 with rationale.
4. Define Sanderson promises: tone, character, and plot.
5. Risk assessment: flag canon conflicts, complexity risks, continuity issues.
6. Author decides — present options, don't assume approval. Save to Engram only.

### `narrative-revise`
**Trigger:** Perform creative revision on narrative drafts — structural editing, voice, and lore consistency.
**Path:** `Demiurgos/src/skills/narrative-revise/SKILL.md`
**Compact Rules:**
1. Three passes: Structural (Sanderson Alpha), Character & Voice (Beta), World & Lore (Line Edit).
2. Edit ONLY in Relatos/. NEVER touch Personajes/ or Lore/.
3. Every change must be traceable to a spec or design decision.
4. Don't polish grammar — focus on STORY. Don't invent lore. Don't change character fundamentals.
5. Preserve author voice — each scene sounds like the POV character, not like an AI.

### `narrative-tasks`
**Trigger:** Break narrative design into implementable writing tasks with scene goals and context bundles.
**Path:** `Demiurgos/src/skills/narrative-tasks/SKILL.md`
**Compact Rules:**
1. Requires design as input.
2. Scene tasks: ID, chapter, POV, beat, goal, input context files, output path, word estimate.
3. Map dependencies: state, knowledge, timeline, parallel scenes.
4. Set checkpoints: canon, voice, pacing, MICE — for verification gates.
5. Write NOTHING to files — save tasks to Engram only.

### `narrative-verify`
**Trigger:** Verify narrative draft against specs — canon, continuity, and consistency gate.
**Path:** `Demiurgos/src/skills/narrative-verify/SKILL.md`
**Compact Rules:**
1. Read world spec + character spec + tasks + draft + Lore/ files + Personajes/ files.
2. Go back to source files for every canon fact — don't trust specs alone.
3. Report in three tiers: CRITICAL (blocks archive), WARNING (needs author decision), SUGGESTION (optional).
4. Cross-reference: map each scene to the spec artifacts it fulfills.
5. Write NOTHING to files — save verify report to Engram only.

### `narrative-world-spec`
**Trigger:** Specify world rules, lore constraints, and setting details for a narrative arc.
**Path:** `Demiurgos/src/skills/narrative-world-spec/SKILL.md`
**Compact Rules:**
1. Requires proposal as input.
2. Classify lore boundaries: Established (must respect), Pliable (can expand), Unknown (can invent).
3. Sanderson's First Law: new magic/tech capabilities must be proportional to reader understanding.
4. Runs IN PARALLEL with narrative-character-spec; both feed narrative-design.
5. Write NOTHING to files — save world spec to Engram only.

---

## Global Skills (`~/.config/opencode/skills/` — user-level)

### `branch-pr`

**Trigger:** Creating, opening, or preparing PRs for review.
**Path:** `~/.config/opencode/skills/branch-pr/SKILL.md`

**Compact Rules:**
1. Issue-first: always check for related issue before creating PR.
2. PR body must reference the issue with "Closes #N" syntax.
3. Title format: `type(scope): brief description`.
4. Include changelog summary in PR body.
5. Verify branch naming matches convention before opening.

### `chained-pr`

**Trigger:** PRs over 400 lines, stacked PRs, review slices.
**Path:** `~/.config/opencode/skills/chained-pr/SKILL.md`

**Compact Rules:**
1. Split changes over 400 lines into ordered, reviewable chain.
2. Each PR must be independently reviewable and mergeable.
3. Maintain base/stack dependency order across the chain.
4. Each PR title must include position marker: `[1/N]`, `[2/N]`, etc.
5. No PR in chain may depend on unmerged changes from later PRs.

### `cognitive-doc-design`

**Trigger:** Writing guides, READMEs, RFCs, onboarding, architecture docs.
**Path:** `~/.config/opencode/skills/cognitive-doc-design/SKILL.md`

**Compact Rules:**
1. One concept per section — avoid mixing concerns.
2. Use structural cues: tables, code blocks, consistent heading hierarchy.
3. Anti-pattern: walls of prose without navigation anchors.
4. Include a "How to read this doc" section for complex docs.
5. Summary-first: put the TL;DR at the top for time-constrained readers.

### `comment-writer`

**Trigger:** PR feedback, issue replies, reviews, Slack messages, or GitHub comments.
**Path:** `~/.config/opencode/skills/comment-writer/SKILL.md`

**Compact Rules:**
1. Warm and direct tone — no passive aggression or excessive positivity.
2. State the observation first, then the reasoning.
3. Always offer a concrete suggestion when pointing out a problem.
4. Avoid "just" and "simply" — they minimize the reader's effort.
5. For disagreements: acknowledge the valid point before presenting the counterargument.

### `go-testing`

**Trigger:** Go tests, go test coverage, Bubbletea teatest, golden files.
**Path:** `~/.config/opencode/skills/go-testing/SKILL.md`

**Compact Rules:**
1. Use `testing` package standard table-driven tests.
2. Golden files for complex multi-line output assertions.
3. `t.Parallel()` on every test unless stateful dependency.
4. Coverage threshold: 80% minimum for new code.
5. Bubbletea models use `teatest` for integration testing.

### `issue-creation`

**Trigger:** Creating GitHub issues, bug reports, or feature requests.
**Path:** `~/.config/opencode/skills/issue-creation/SKILL.md`

**Compact Rules:**
1. Issue-first: search existing issues before creating.
2. Bug reports must include: steps, expected, actual, environment.
3. Feature requests must include: problem statement, proposed solution, tradeoffs.
4. Use labels: bug/enhancement/documentation/question.
5. Link related issues and PRs in the body.

### `judgment-day`

**Trigger:** Judgment day, dual review, adversarial review, juzgar.
**Path:** `~/.config/opencode/skills/judgment-day/SKILL.md`

**Compact Rules:**
1. Blind dual review: two independent agents review without seeing each other's output.
2. Fix only confirmed issues (both agents agree).
3. Re-judge after fixes — repeat until both agents pass.
4. Document each round: what was flagged, what was fixed, what remains.
5. No single-agent changes without dual confirmation.

### `skill-creator`

**Trigger:** New skills, agent instructions, documenting AI usage patterns.
**Path:** `~/.config/opencode/skills/skill-creator/SKILL.md`

**Compact Rules:**
1. All skills must have valid frontmatter with name, description, trigger.
2. Required structure: Activation Contract, Hard Rules, Decision Gates, Execution Steps, Output Contract, References.
3. Description must be quoted, one physical line, trigger-first, ≤250 chars.
4. Target 180-450 body tokens; move examples/edge-cases to local `references/`.
5. References must be local files, stable relative to skill directory.

### `work-unit-commits`

**Trigger:** Implementation, commit splitting, chained PRs, keeping tests/docs with code.
**Path:** `~/.config/opencode/skills/work-unit-commits/SKILL.md`

**Compact Rules:**
1. Each commit must be a reviewable work unit: one logical change.
2. Tests and docs must ship in the same commit as the code they cover.
3. No "fix review comments" commits — rebase/squash before review.
4. Commit messages: conventional commits with body explaining why.
5. Split large changes into stacked branches via chained-pr skill.
