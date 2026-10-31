# Relations lifecycle — P3: on-demand semantic sweep

Objective: the Author decides when the world gets more connected. A passive badge
shows how much reviewable work exists; a manual sweep turns each candidate into
semantic proposals with evidence and confidence, which the Author accepts or
rejects. Nothing is written without an explicit accept.
Branch: `feat/relations-lifecycle-p3`, stacked on P2 (PR #63). Delivery:
work-unit commits; push/PR are the Owner's decision.
Tests: `.venv/bin/python -m pytest src/tools/demiurgos-suite/wiki/tests/ -q`

## Specs

S1 — Phase scope. The design (Engram `roadmap/relations-lifecycle`) names P3
"cola de propuestas + UI". This phase ships candidate detection, the on-demand
sweep, the proposal queue and the "Propuestas" tab. P4 (global destructive
reconciliation) and P5 (per-save report) stay out of scope.

S2 — On demand (Owner decision, L1). No model call happens on save. The Author
triggers the sweep; the cost is theirs to choose.

S3 — The badge measures reviewable work, and it re-arms. A ficha is a candidate
when its body mentions at least one other world entity and its body digest
differs from the one recorded at its last sweep (or was never swept). Muted
fichas are never candidates. This is computed without the model and does not
decay to a permanent zero: editing the body makes the ficha reviewable again.

S4 — "Dejar así" is reversible. Muting a ficha removes it from the candidate set
and from the sweep; unmuting restores it. Mute is a ficha-level verdict; a
rejected *pair* stays in P2's rejection memory.

S5 — Proposals are proposals. A sweep produces
`{source, target, relationship_type, confidence, evidence}` entries in a queue.
The model never writes. Only an explicit accept writes the target id into the
source ficha through the same frontmatter writer every other relation edit uses.

S6 — Bounded and cancelable. One request sweeps at most one ficha (one model
call), picks the next candidate deterministically, and returns what it produced.
The UI loops while the Author wants, with progress and a stop button; there is no
long-running background job and no partial write.

S7 — World-local state. `<world>/.relations/state.json` holds `swept`
(path → body digest), `muted` (paths) and `last_sweep_at`;
`<world>/.relations/proposals.json` holds the pending queue. Both are atomic,
fail-open, sorted and travel with the world. They are unreachable as content
(`.relations` is already in `_INTERNAL_DIRS`).

S8 — Reuse the semantic pipeline. Prompt, parse and validation come from the
existing importer path (`build_relationship_batch_prompt`,
`parse_hermes_response`, `validate_relationship_batch`) over the production
Hermes bridge; the sweep owns only the propose-don't-write orchestration.

## Tasks

- [x] T1 — `relation_state.py`: swept/muted state, atomic and fail-open. Route:
  inline. Evidence: `test_relation_state.py` 6 passed.
- [x] T2 — `relation_candidates.py`: deterministic scan (mentions, digest, mute).
  Route: inline. Evidence: `test_relation_candidates.py` 7 passed.
- [x] T3 — Endpoints: `GET /relations/candidates`, `POST /relations/mute`,
  `POST /relations/unmute`. Route: inline. Evidence:
  `test_relations_lifecycle_p3.py` 4 passed; full backend suite 4389 passed.
- [x] T4 — Sweep: `POST /relations/sweep` (one candidate per call) building
  proposals through the reused pipeline; queue persistence; accept/reject
  endpoints. Route: inline. Evidence: `test_relation_proposals.py` (6),
  `test_relation_sweep.py` (6), P3 API tests (7); full backend suite 4404
  passed, 8 skipped. A silent provider leaves the ficha unswept.
- [ ] T5 — Frontend "Propuestas" tab: badge, sweep progress, queue with
  accept/reject/mute.
- [x] T6 — Ship the new modules in the runtime payload manifest. Route: inline.
  Evidence: 179 payload files, `relation_state.py`, `relation_candidates.py`,
  `relation_proposals.py` and `relation_sweep.py` listed.

## Log

L1 (verbatim Owner decisions): "creo que si, deberia ser a demanda entonces. Cada
cierto tiempo el autor desencadena esa funcionalidad y el mundo se interconecta
mas. Ahora, estaria bien que cada x cantidad de cambios y nuevas fichas el mismo
Demiurgos sea quien le recuerde al usuario que si quiere que todo se interconecte
mejor debe hacer este barrido, no lo crees?" · "no, hagamozlo segun tu
recomendacion"

L2 Decision: the reminder is a passive badge driven by real candidates, not a
change counter, and it re-arms on body edits. A change counter would fire when
nothing is actionable and stay silent when a whole imported world is pending.
