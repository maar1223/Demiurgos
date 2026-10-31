# Relations lifecycle — P5: per-save relation-health report

Objective: after the Author saves a ficha, show whether it is connected to the
graph and, when it is not, why. The report never writes anything.
Branch: `feat/relations-lifecycle-p5` (from `master`). Delivery: work-unit
commits; push/PR are the Owner's decision.
Tests: `.venv/bin/python -m pytest src/tools/demiurgos-suite/wiki/tests/ -q`

## Specs

S1 — Phase scope. Quoted from the design (Engram `roadmap/relations-lifecycle`):
"El reporte de calidad (false-orphan/standalone/non-entity) corre tras cada
guardado y se muestra en la revisión." P5 ships that report; nothing else
changes.

S2 — Read-only and world-wide. `GET /relations/quality?path=` parses one ficha
and computes its tags against the whole world catalog, with the same evidence
rules as P1. It never writes and never triggers a model call.

S3 — Same tags as the importer review:
- `non-entity` — the document opted out of the graph (`graph: false`);
- `false-orphan` — no declared relation, but the body names another ficha;
- `standalone` — no declared relation and no mention at all.
A ficha with at least one declared relation is healthy and reports no tags.

S4 — Shown in the editor after a save. The editor fetches the report once the
save/create succeeds (after P1 already applied the grounded relations) and shows
it in a small banner. A healthy save shows nothing.

S5 — Reuse the copy. The banner uses the same messages the importer review
already shows, so the vocabulary cannot drift.

S6 — Fail-open. A failed quality request never turns a successful save into an
error; the banner simply does not appear.

## Tasks

- [x] T1 — `import_relations.ficha_quality`: tags for one ficha against a
  catalog. Route: inline. Evidence: five unit cases green.
- [x] T2 — `GET /relations/quality?path=` endpoint. Route: inline. Evidence:
  five endpoint cases green, including the 404.
- [x] T3 — Editor banner after save/create, with the reused copy. Route: inline.
  Evidence: `WikiEditor.test.tsx` asserts the request and the banner.
- [x] T4 — Tests: unit tags, endpoint cases, editor banner. Route: inline.
  Evidence: backend 4438 passed / 8 skipped; frontend 1658 passed; typecheck and
  build green; PR #68 CI 16/16.
- [x] T5 — Ship nothing new in the manifest unless a new module is added (the
  helper lives in an already-shipped file). Route: inline. Evidence: no new
  module, manifest unchanged.

## Log

L1 (verbatim Owner request): "ok adelante" — continue with P5 after P4.

L2 Delivery: PR #68 merged. This closes the relations lifecycle (P1–P5): the
deterministic service, rejection memory, on-demand semantic sweep, global
synchronization with a pre-image backup, and now the per-save health report.
