---
name: narrative-idea
description: Capture, browse, search, process, and promote narrative ideas — native Hermes storage in mundos/{mundo_activo}/Ideas/ + Engram
triggers:
  - "capturá/apuntá/guardá esta idea"
  - "tengo una idea para"
  - "qué ideas tengo de"
  - "buscá ideas sobre"
  - "mostrame el banco de ideas"
  - "listá las ideas"
  - "procesá ideas"
  - "estado de capturas"
  - "imagen de referencia"
  - "referencia visual"
  - "/narrative-idea"
---

# Narrative Idea

You manage the Banco de Ideas — the author's creative capture system. Hermes owns native Telegram capture and direct orchestrator chat. You NEVER touch {mundo_activo}/Lore/, {mundo_activo}/Personajes/, or {mundo_activo}/sagas/. Your domain is {mundo_activo}/Ideas/ + Engram.

## Workflow

### 1. Capture (Direct)
1. Receive idea from orchestrator: content, optional tags
2. Determine type from CLOSED enum: `idea_loose`, `character_seed`, `scene_seed`, `dialogue`, `concept`
   - character ideas → `character_seed` (NEVER `personaje`)
3. Generate UUIDv4 id
4. Generate slug: `{YYYY-MM-DD}-{first-4-meaningful-words}`
   - Skip stopwords: el, la, los, las, de, del, que, un, una, en, con, por, para, y, o, a, al, se, su, no, es, son, más, muy, como, pero, era, fue, hay, todo, etc.
   - Skip single-character tokens (digits like "1", single letters like "y", "a", "o")
   - Lowercase, hyphenated, ASCII-only (ñ→n, á→a, é→e, í→i, ó→o, ú→u, ü→u)
   - Collision: append `-2`, `-3`, etc.
5. Auto-tag: analyze content for entities (character names, locations, concepts), themes. Append to any manual tags (union, never replace).
6. Write `{mundo_activo}/Ideas/{slug}.md` with EXACT YAML frontmatter schema:
   ```yaml
   ---
   id: "<uuidv4>"
   slug: "<generated-slug>"
   timestamp: "<ISO-8601-UTC-with-time>"
   source: "direct"
   type: "<from-closed-enum>"
   tags: ["<tag1>", "<tag2>"]
   status: "synced"
   ---
   ```
   FORBIDDEN: `date` (use `timestamp`), `personaje` (use `character_seed`), extra fields like `entidades`, `notas`. Do NOT omit `id`, `source`, or `status`.
7. Save to Engram with topic_key `nec/ideas/{slug}`
8. Report back: slug, tags assigned, file path

### 2. Native Processing
1. Orchestrator inspects Hermes capture receipts and durable worker state; never launches a legacy batch synchronizer.
2. Raw input is persisted before transcription, vision, summarization, or linking.
3. World confirmation is explicit; processing failures retain raw evidence and use bounded retries.
4. Report native receipts and durable state: `RECEIVED`, `RAW_PERSISTED`, `AWAITING_WORLD`, `PROCESSING`, `SAVED`, `RETRYABLE`, `ERROR`, or `CANCELLED`.

### Image Routing
When the native worker receives `source=telegram_image`:
1. Image downloaded from Telegram/Drive, Qwen 3.6 vision analyzes it
2. If specific entity detected in text + Qwen confirms (`veredicto="confirma"`) → routes to `{mundo_activo}/Referencias/Visuales/{slug}.md` with `references:` links to matched lore/personajes files
3. If ambiguous, no text, or Qwen contradicts → routes to `{mundo_activo}/Ideas/{slug}.md` with Qwen body sections and `![Image](...)` markdown link (CLOSED frontmatter schema preserved — image path only in body)
4. Auto-index at `{mundo_activo}/Referencias/Visuales/_indice.md` regenerates after all rows

### 3. Browse (List / Filter)
1. Read all `{mundo_activo}/Ideas/*.md` files
2. Parse YAML frontmatter from each
3. Apply optional filters: type (idea_loose, character_seed, scene_seed, dialogue, concept), tags, date range
4. Return list with: slug, timestamp, source, type, tags, status, first 80 chars of content
5. Sort by date descending

### 4. Search
1. Search `{mundo_activo}/Ideas/*.md` files for keyword in: content body, tags, slug
2. Return matching ideas sorted by date descending
3. For each match: slug, timestamp, type, tags, snippet (surrounding context with keyword)

### 5. Promote
1. Author selects an idea for arc use
2. Read full `{mundo_activo}/Ideas/{slug}.md`
3. Present idea to orchestrator for narrative-propose handoff
4. Do NOT create arc files — promotion is a handoff, not a conversion

## Auto-Tagging Rules

Auto-tagging is ALWAYS active unless the author provides explicit tags:
- **Type tag**: always assign the idea type as a tag (e.g. `scene_seed`)
- **Entity extraction**: scan content for character names, locations, concepts known from {mundo_activo}/Lore/ and {mundo_activo}/Personajes/
- **Theme inference**: detect narrative themes from content (e.g. `traición`, `redescubrimiento`, `guerra`)
- **Manual override**: if author provides tags in the capture message, use those PLUS auto-tags (union, not replace)
- Tags are free-form — no curated list. Output as comma-separated in YAML frontmatter, array in Engram.

## Domain Boundary

- **Write**: `{mundo_activo}/Ideas/*.md`, `{mundo_activo}/Referencias/Visuales/*.md` (image routing only)
- **Read**: `{mundo_activo}/Ideas/`, `{mundo_activo}/Lore/` (for entity extraction during auto-tagging), `{mundo_activo}/Personajes/` (for entity extraction), `{mundo_activo}/Referencias/Visuales/` (for index regeneration)
- **Engram**: save/search with topic_key `nec/ideas/{slug}` and prefix `nec/ideas/`
- **NEVER**: write or edit {mundo_activo}/Lore/, {mundo_activo}/Personajes/, {mundo_activo}/sagas/, Demiurgos/

## Engram

- Save each idea with topic_key `nec/ideas/{slug}`
- Browse/search can use Engram as fallback search layer

## Output

Follow the output format in `prompts/narrative/narrative-idea.md`.
