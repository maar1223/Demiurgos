---
description: Manage the Banco de Ideas — capture, browse, search, process, and promote narrative ideas
agent: Demiurgos-Orchestrator
---

/narrative-idea — Banco de Ideas command hub.

USAGE: /narrative-idea <capture|browse|search|process|promote> [args...]

SUBCOMMANDS:

  capture <idea-text>
    Capture an idea directly from the orchestrator chat.
    Example: /narrative-idea capture "Daest descubre un Umbral inestable en las minas"
    Auto-tags are generated; add manual tags with --tags="tag1,tag2"

  browse [--type=<type>] [--tags=<tag1,tag2>] [--since=<YYYY-MM-DD>] [--until=<YYYY-MM-DD>]
    List ideas with optional filters.
    Types: idea_loose, character_seed, scene_seed, dialogue, concept
    Example: /narrative-idea browse --type=scene_seed --since=2026-05-01

  search <query>
    Search ideas by content keywords or tag values.
    Example: /narrative-idea search "Daest"

  process [<capture-id>]
    Inspect or advance native Hermes captures through the durable worker.
    Raw input is retained on retryable or terminal failure.
    Example: /narrative-idea process

  promote <slug>
    Promote an idea for arc use — hands off to narrative-propose.
    Example: /narrative-idea promote 2026-05-16-escena-persecucion

WORKFLOW:
1. Parse subcommand and arguments from $ARGUMENTS
2. Launch narrative-idea sub-agent with the parsed intent
3. Sub-agent reads/writes ONLY Ideas/ and Engram nec/ideas/
4. Present results to author inline

CONTEXT:
- Working directory: !`echo -n "$(pwd)"`
- Current project: !`echo -n "$(basename $(pwd))"`
- Arguments: $ARGUMENTS

Do NOT touch Lore/, Personajes/, or Relatos/ — this is infrastructure.
