# Relations — curated-pair memory (closes the P3/P4 conflict)

Objective: a relation the Author explicitly wanted survives the world-wide sync.
P4 removes declared relations no text backs; P3 can propose a relation whose
target the text does not name. Without this memory, accepting a P3 proposal and
later running P4 deletes it. Now "curated" wins.
Branch: `feat/relations-curation-memory` (from `master`). Delivery: work-unit
commits; push/PR are the Owner's decision.

## Specs

S1 — Explicit curation is recorded per world at
`<world>/.relations/curated.json` as `[source_key, target_id]` pairs. The source
key is the canonical id, or the path for a legacy ficha without one.

S2 — Recording: accepting a semantic proposal pins the pair; creating a relation
from the graph UI pins it; breaking a relation unpins it and records the
rejection (the Author's last verdict wins).

S3 — P4 respects it: `build_global_plan` never removes a declared relation whose
pair is curated, even when the text does not back it. A rejected pair still
loses to the rejection: if a pair is both, the rejection removes it (break
unpins first, so this only happens with a corrupted store).

S4 — Fail-open and deterministic: the store is atomic, sorted, deduped and
unreadable/corrupt stores mean "nothing curated".

S5 — The UI states the difference and the order: `Sincronizar` aligns the world
with the text (no model); the sweep proposes inferred relations (model, review
first). Sync first, sweep second.

## Tasks

- T1 — `relation_curation.py`: load/pin/unpin, atomic and fail-open.
- T2 — Wire accept-proposal and graph create/break.
- T3 — Keep curated pairs in `build_global_plan`.
- T4 — Tests: store, plan, API accept/break.
- T5 — UI hint: the Propuestas panel points to Sincronizar and states the order.
- T6 — Ship the module in the payload manifest.

## Log

L1 (verbatim Owner request): "ok, me gustaria que hicieras ese cambio, sin embargo
me gustaria entender algo mas, quiero que me expliques claramente las similitudes
y las diferencias entre la sincronizacion y el barrido."

L2 Decision: a separate curated store (not provenance in the ficha) keeps the OKF
format untouched and reuses the P2/P3 pattern.
