# Relations lifecycle — P2: rejection memory

Objective: the Author's curation wins. P1 merges relations additively, so a
relation the Author removes from a ficha comes back on the next save. P2
remembers the rejected pair and never proposes it again.
Branch: `feat/relations-lifecycle-p2`, stacked on `feat/relations-lifecycle-p1`
(PR #62) until it lands. Delivery: work-unit commits; push/PR are the Owner's
decision.
Tests: `.venv/bin/python -m pytest src/tools/demiurgos-suite/wiki/tests/ -q`

## Specs

S1 — Phase scope. Quoted from the Owner's design (Engram `roadmap/relations-lifecycle`):
"Memoria de rechazos: un par rechazado no se vuelve a proponer; la
automatización respeta la curaduría." P2 ships that memory. Semantic proposals
(P3), global reconciliation with backup (P4) and the per-save quality report (P5)
stay out of scope.

S2 — Curation sets the verdict. Breaking a relation from the graph UI
(`POST /api/{mundo}/graph/relation`, `action: "break"`) records the pair as
rejected; creating it (`action: "create"`) clears the rejection, because the
Author explicitly wanted it. Both are idempotent.

S3 — The plan respects it. `relation_service.build_relation_plan` drops every
grounded relation whose `(source_id, target_id)` pair is rejected, in every pass
(forward, reverse, folder index). A rejected pair is never re-added by a save.

S4 — World-local, unreachable as content. The store lives at
`<world>/.relations/rejected.json`, outside the content sections, alongside the
existing `.papelera`/`.history` bookkeeping. It travels with the world on move,
copy and backup, and no content route can read or write it.

S5 — Fail-open. A missing, corrupt or unreadable store is treated as "no
rejections" and logged; it never breaks a save or a manual relation edit.

S6 — Deterministic file. Entries are canonical-id pairs, deduped and sorted, so
the same curation always produces the same bytes.

S7 — Rejection does not delete. P2 only prevents re-adding. A relation already
present in a ficha stays until the Author removes it; destructive reconciliation
remains P4's job.

## Tasks

- [x] T1 — `relation_rejections.py`: load, record, clear, atomic write,
  fail-open. Route: inline. Evidence: `test_relation_rejections.py` 7 passed.
- [x] T2 — Wire `set_graph_relation`: `break` records, `create` clears. Route:
  inline. Evidence: `test_relations_lifecycle_p2.py` green.
- [x] T3 — Filter the plan in `relation_service`; add `.relations` to the
  internal directories so it is never reachable as content. Route: inline.
  Evidence: forward, reverse and folder-membership rejections filtered; the
  store is denied by `_resolve_mundo_path`.
- [x] T4 — Tests: break then save does not re-add; create clears; corrupt store
  is ignored; reverse pass and folder index respect it; file is sorted/deduped.
  Route: inline. Evidence: 24 P2-related tests passed; full backend suite 4372
  passed, 8 skipped.
- [x] T5 — Ship the new module in the runtime payload manifest. Route: inline.
  Evidence: 175 payload files, `relation_rejections.py` listed.

## Log

L1 (verbatim Owner request): "pushea, PR y sigue adelante"

L2 Context: P1 is open in PR #62 (branch `feat/relations-lifecycle-p1`); P2
stacks on it. P1's additive merge (S8) makes
the Author's removal ineffective on the next save, which is exactly the gap P2
closes.

L3 Decision: the verdict key is the source's canonical id, or its path when a
legacy ficha has none. Without the fallback, a ficha without an `id` could
break a relation and see it return on the next save, which is the very bug P2
exists to fix. Verified by the API test: `("lore/00_inicio.md", "lore::beta")`
is recorded and the resave does not re-add it.
