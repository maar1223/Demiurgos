# Intent corpus

Synthetic worldbuilder conversations used to measure one thing: whether the
assistant separates *the author wants to talk* from *the author wants to open a
flow or activate a skill*.

- Contract and decisions: `odd/tasks/intent-corpus.md`
- Machine-readable classes: `labels.yaml`
- Run reports: `odd/evidence/intent-corpus/<date>-<provider>.md`

## Why a corpus and not more rules

Intent was decided by a boolean (`guided: true/false`) plus a term+verb matcher,
so every new case became an exception in one of the two. The corpus replaces
"add a keyword" with "add a labeled turn". A new case is a row, not a branch.

## Layout

```
intent-corpus/
  README.md
  labels.yaml
  profiles/
    01-architecta-fantasia/
      profile.md              persona card: voice, axes, what it breaks
      01-consult-advice.md    one conversation per file
```

## Conversation format

Frontmatter carries the fixture dimensions:

```yaml
id: fantasia-01-consult-advice
profile: 01-architecta-fantasia
genre: epic-fantasy
language: es
register: verbose-formal   # terse | verbose-formal | ambiguous
depth: single-turn         # single-turn | ongoing
attachment: none           # none | present
reference: none            # none | named
```

Each author turn is a heading, the verbatim utterance, and its contract labels:

```markdown
## Turn 3 — author
> Creo que necesito crear un personaje que encarne esa tensión, pero todavía no
> sé si va a ser un villano o un aliado.

- **Class:** `answer`
- **Offer expected:** yes — non-blocking, after the reply
- **Must not:** open a guided session
- **Why:** rule 1 (explicit uncertainty wins over volition)
```

Opening classes (`start_flow`, `activate_skill`, `edit`) must name their
`Target`. Turns inside an already-open flow are `Class: flow_step` and are not
classified by this contract.

## What is asserted

- The class, the offer expectation, the target, and the `Must not` line.
- **Never the assistant's wording.** The corpus fixes the decision and the
  forbidden outcome, not the prose.

## How to read a run

A report holds, per turn, expected class, actual class and the observed
transition, plus a per-class confusion matrix and the two error rates
**separately**:

- **false-open** — expensive: destroys the reply and enters a machine that writes.
- **false-close** — cheap: the reply happens and the author retries.

There is no single accuracy number on purpose. The design is judged by the
asymmetry, not the average.

## Rules

1. Labels come from the contract in `labels.yaml` and the spec, never from a
   model's opinion. The same model never authors a case and judges it.
2. Negatives dominate. A corpus full of "quiero crear un personaje" measures
   nothing.
3. The corpus is a fixture: no runtime path reads it and no user is profiled.
   Profiles exist to vary phrasing, not to build user types.
