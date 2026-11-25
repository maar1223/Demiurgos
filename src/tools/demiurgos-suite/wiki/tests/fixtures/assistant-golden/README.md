# Assistant golden set

A per-world corpus of **level-C questions** that measure one thing: whether the
assistant answers from the author's world (the fichas) instead of inventing from
general knowledge. It complements, and never replaces, the two gates that
already exist:

- `scripts/check_assistant_graph.py` — wiring (levels A and B: the graph is
  reachable and the MCP side can read it).
- `tests/fixtures/intent-corpus/` — whether the assistant opens a flow at the
  right time.

This corpus is the third question: **when it answers, does it answer from the
world?**

- Contract and decisions: `odd/tasks/assistant-runtime-evolution.md` (Phase 2,
  S7).
- Closed vocabularies: `labels.yaml`.
- Machine-readable shape: `schema.json`.

## Why a corpus and not a manual question

Level C used to be the Owner asking one question by hand
(`docs/architecture/ASSISTANT_WORLD_READING.md` §5). That leaves no record and
cannot be re-run after an engine change. A corpus turns "ask the Owner" into
"run the set, diff the record": the baseline is written down, and a regression
is a red case, not a vague feeling.

## Layout

```
assistant-golden/
  README.md
  labels.yaml
  schema.json
  worlds/
    <slug>/
      world.yaml      # world descriptor (never indexed)
      cases.yaml      # the cases for this world (validated by ../../schema.json)
      lore/           # ficha tree, ONLY when world.yaml says source: fixture
      personajes/
      referencias/
```

`world.yaml` and `cases.yaml` sit at the world root on purpose: the graph
indexer scans only `lore/`, `personajes/` and `referencias/`, so the descriptor
and the cases are never treated as entities.

## World descriptor — `world.yaml`

| Field | Required | Meaning |
|---|---|---|
| `name` | yes | World slug, exactly the directory name and the world name the app uses. |
| `description` | yes | One or two sentences: what this world is and what the cases prove. |
| `source` | yes | `fixture` — the fichas live under this directory and are indexed as a self-contained world (deterministic, CI-safe). `data-root` — the fichas are a real world resolved from `DEMIURGOS_DATA_ROOT/mundos/<name>` (a release baseline on the Owner's install). |
| `language` | no | Default expected reply language (BCP-47-ish `es`, `en`, `es-AR`). A case may override it. |

## Case format — `cases.yaml`

The document is `{ world: <slug>, cases: [ ... ] }`. A case is:

| Field | Required | Meaning |
|---|---|---|
| `id` | yes | Stable slug, unique inside the world. Prefix it with the world slug. |
| `level` | yes | `C` today. Levels A and B belong to the wiring gate, not here. |
| `question` | yes | The author's turn, **verbatim**, in the world's language. Never paraphrased into a prompt. |
| `language` | no | Overrides the world's default expected language. |
| `source_paths` | yes | Repo-relative ficha paths (relative to the world root) that hold the answer. At least one must be cited in the reply. |
| `expected_facts` | yes | One or more `{ name, any_of }` groups. **Every** group must match **at least one** of its `any_of` strings. Multiple spellings in `any_of` absorb wording differences. |
| `must_not.codes` | yes | Closed codes from `labels.yaml`, each with a severity. `blocking` codes fail the case; `advisory` codes are reported. |
| `must_not.strings` | no | Literal forbidden substrings (invented names, wrong years, wrong place). Deterministic and cheap. |
| `notes` | no | Why the case matters and what a human should watch. |

## What is asserted — and what is not

- **Deterministic:** every `expected_facts` group matches, every `must_not.strings`
  is absent, at least one `source_paths` entry is cited, and the reply is in the
  expected language when one is declared.
- **Judged:** `must_not.codes` (invented canon, claimed authority, blind answer…).
  The runner reports them; a blocking code fails the case.
- **Never the wording.** The corpus fixes the facts, the citation and the
  forbidden outcomes, not the prose. Two correct answers may read differently.

## How to read a run

A report is written to `odd/evidence/assistant-golden/<date>-<sha>.md` and
holds: the corpus digest, per-case PASS/FAIL, the first fact group that missed,
any forbidden string that appeared, whether the source was cited, and the
per-world and overall pass rates. There is no single score on purpose: a
regression is a named case, not a number that moved.

## Rules

1. **Negatives dominate.** A corpus of easy questions measures nothing. Include
   cases whose answer is a single obscure ficha, and cases that tempt the model
   to fill gaps (a year that sounds plausible, a neighbour region that does not
   exist).
2. **The same model never authors a case and judges it.** Labels come from the
   fichas and this contract, never from a model's opinion of its own answer.
3. **Fixture worlds are synthetic and dev-only.** No runtime path reads this
   directory and no user is profiled. `source: data-root` worlds point at a real
   install; they are not committed content.
4. **Add a case, not a rule.** A new failure becomes a row in `cases.yaml`, not
   more matcher code.
5. **Coverage minimum** (Phase 2): 15–25 level-C cases per world, including
   must-not cases for invented canon, claimed authority, a blind answer while
   the graph is down, and the wrong language or tone.

## Validating the format

`schema.json` is JSON Schema (draft 2020-12). Validate a `cases.yaml` document
against it directly; validate a `world.yaml` against its `worldDescriptor`
definition:

```python
import json, yaml
from jsonschema import Draft202012Validator
schema = json.load(open("schema.json"))
Draft202012Validator(schema).validate(yaml.safe_load(open("worlds/<slug>/cases.yaml")))
world_schema = {"$schema": schema["$schema"], "$defs": schema["$defs"],
                "$ref": "#/$defs/worldDescriptor"}
Draft202012Validator(world_schema).validate(yaml.safe_load(open("worlds/<slug>/world.yaml")))
```
