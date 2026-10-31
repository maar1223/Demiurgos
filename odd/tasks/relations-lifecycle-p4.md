# Relations lifecycle — P4: global reconciliation with backup

Objective: turn the one-off repair into product. A world-wide deterministic pass
that adds the relations the text justifies and removes the ones no text backs,
behind a preview and a pre-image backup. Only the Author triggers it.
Branch: `feat/relations-lifecycle-p4` (from `master`). Delivery: work-unit
commits; push/PR are the Owner's decision.
Tests: `.venv/bin/python -m pytest src/tools/demiurgos-suite/wiki/tests/ -q`

## Specs

S1 — Phase scope. The design (Engram `roadmap/relations-lifecycle`) names P4
"reconciliación global con backup (el script que corrimos se vuelve producto)".
P5 (per-save quality report) stays out of scope.

S2 — Deterministic and world-wide. For every graph entity: additions are the
grounded relations it does not declare; removals are declared entries the text
does not justify (including dangling references to entities that no longer
exist). Same evidence rules as P1 (`grounded_relations`, structural membership
uncapped).

S3 — Curation wins. A rejected pair (P2) is never added and is removed if
present. A muted ficha (P3, "dejar así") is skipped entirely: no additions, no
removals. Non-entities (`graph: false`) are untouched.

S4 — Preview before any write. `GET /relations/reconcile/preview` returns per
ficha additions and removals plus totals. The Author sees exactly what will
change.

S5 — Pre-image backup. Before the first write, every affected file is copied to
`<world>/.relations/preimages/<UTC stamp>/` with a manifest (counts, paths,
created_at). The backup is the reversal path; it lives in the hidden world
directory, is unreachable as content and travels with the world.

S6 — One explicit confirmation, applied server-side. `POST /relations/reconcile`
recomputes the plan (never trusts a client-supplied list), writes the pre-image
backup, then rewrites each affected ficha through the shared frontmatter writer
under the target lock. A second run with nothing to do writes nothing and creates
no backup.

S7 — Idempotent and fail-open per file. Re-running after a successful pass
produces an empty plan. A file that cannot be read or rewritten is reported in
the result and does not abort the rest of the pass.

S8 — No provenance, documented. Relations have no origin field, so removal is
"not justified by the text". The Owner confirmed no relations were added by hand
(L1), and the preview plus backup keep the operation reversible.

## Tasks

- [x] T1 — `relation_reconcile.py`: world plan (resolve declared entries,
  additions, removals, unresolved), deterministic and bounded. Route: inline.
  Evidence: `test_relation_reconcile.py` 9 passed.
- [x] T2 — Pre-image backup with manifest and restore-by-copy semantics. Route:
  inline. Evidence: backup test checks copied files and manifest contents.
- [x] T3 — Endpoints: preview and apply (recompute server-side, one
  confirmation). Route: inline. Evidence: `test_relations_lifecycle_p4.py` 5
  passed.
- [x] T4 — Tests: additions, removals, dangling refs, rejected, muted,
  non-entity, idempotency, backup contents, API preview/apply. Route: inline.
  Evidence: full backend suite 4418 passed, 8 skipped.
- [x] T5 — Frontend: "Reconciliar mundo" section in the Propuestas tab with
  preview counts and the apply confirmation. Route: inline. Evidence:
  `RelacionesCanon.test.tsx` 6 passed; full frontend suite 1658 passed;
  typecheck and build green.
- [x] T6 — Ship the new module in the runtime payload manifest. Route: inline.
  Evidence: 180 payload files, `relation_reconcile.py` listed.

## Log

L1 (verbatim Owner decision): "yo no he agragado ninguna relacion a mano"

L2 Decision: single confirmation over a full preview (not per-item selection),
because there is no hand-authored relation to protect. The pre-image backup and
the hidden store keep it reversible.

L3 Evidence: a second pass on a reconciled world yields an empty plan and creates
no backup; a muted ficha and a `graph: false` ficha are untouched; a rejected
pair is removed rather than re-added. The apply recomputes the plan server-side,
so a client can never supply the changes.

L4 Independent verification found two blockers and a CRLF advisory, all fixed:
- an unreadable affected file aborted the whole apply with a 500 before the
  fail-open loop; the pre-image backup is now per-file fail-open and the skipped
  files are reported in `failed`, with only a manifest failure aborting;
- a mute recorded through an accepted spelling (`lore/./alpha.md`) was stored raw
  and reconcile compared the index path; the mute endpoint now stores the
  canonical world-relative path;
- the appliers read with universal newlines and rewrote CRLF fichas as LF; the
  three writers now read with `newline=""`.
The verifier's ten probes are committed as
`tests/test_relations_lifecycle_p4_verifier.py`. Final evidence: backend 4428
passed / 8 skipped; frontend 1658 passed; build green.
