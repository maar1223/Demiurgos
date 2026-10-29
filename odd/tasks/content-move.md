# Step 5 — move the content to another folder or disk

Branch: `feat/content-move` · Base: `master` (`4ad457f2`) · Tests: `.venv/bin/python -m pytest tests -q` from `src/tools/demiurgos-suite/wiki`, `npm test -- --run` in `frontend` · Delivery: work-unit commits; push/PR are the Owner's decision.

## Specs

S1 — The action lives in `/perfil` → **Respaldo**, in a "Carpeta de tu contenido" card above the backup destination, next to the folder it must never overlap. Quoted from the Owner: "si, me parece perfecto que vaya alli".
Acceptance: the card is reachable from that section, shows the folder in use, the worlds and the free space, and reuses the onboarding step's component (one component, two surfaces).

S2 — The action offered depends on the state, never on the screen (quoted from the Owner's decision: "si, incluyelo con doble confirmacion"; table agreed in the plan):

| Target | Current content | Action |
|---|---|---|
| empty | no worlds | use |
| already holds content | has content | use |
| empty | has content | **move** |
| holds content | no content | use |
Acceptance: one shared predicate decides it, with cells for every row.

S3 — A move copies, verifies, then publishes. The pointer is written ONLY after the copy verified; a cancelled, interrupted or failed copy changes nothing.
Acceptance: after a cancel or a forced failure the pointer is byte-identical and the target holds no half tree that a later start could mistake for content.

S4 — What travels is the AUTHOR CONTENT, classified by the same rules the backup uses (`backup.inventory`), plus the content-root `.env`. Machine state never travels, and the project's own source tree is never treated as content (the content root can be a checkout).
Acceptance: on a checkout-shaped content root only `mundos/`, `ideas/`, `plantillas/`, `config/`, `data/` and `.env` are copied; state artifacts are reported as not copied, with the reason.

S5 — A move never modifies the source: no delete, no rename, no truncate. Not even after success.
Acceptance: hashes of the source tree are identical before and after a completed move.

S6 — The source can be deleted ONLY from the app, ONLY for the exact path recorded by the last successful move, ONLY after that move verified and the pointer points at the new folder, and ONLY with double confirmation (a typed value matching the recorded path). Never automatic, never for a checkout, never for a path that is not the recorded one.
Acceptance: a wrong typed value, a path that differs from the record, a source containing `.git`, and a move that did not complete are all refused with the reason; a correct confirmation removes the old tree and says what it removed.

S7 — The move runs as a job with progress and cancellation, because a copy of gigabytes cannot be a request. `POST /api/data-root/move` validates the preconditions synchronously and returns a job id; `GET /api/data-root/move/{id}` reports `state`, counters and the failure reason; `POST /api/data-root/move/{id}/cancel` stops it.
Acceptance: the endpoints are behind the principal guard; the job record of the last run lives in the STATE directory (never in the content root); a second concurrent move is refused.

S8 — The preconditions are refused up front, with both paths in the message: a relative path, a target that is not an existing empty directory, a target overlapping the machine state, a target overlapping the backup destination, a source with no content, and a target without free space.
Acceptance: each refusal names what to change and writes nothing.

S9 — After a completed move the app asks for a restart (the running process caches the content root) and, once restarted, offers to delete the old copy. The card reports the pending cleanup.
Acceptance: no world is created between the move and the restart; the cleanup action is only offered when the record says a verified move ended with the pointer on the new folder.

S10 — The overlap rule and the "action" rule are shared with the frontend, and the browser's version may only be a courtesy: the server is the authority on every refusal.
Acceptance: the frontend pre-check mirrors the server for the canonical cases and never claims a move is possible when the server would refuse it.

## Tasks

| ID | Task | Specs | Route | Status | Commit |
|---|---|---|---|---|---|
| T1 | `content_mover.py`: plan (content set, space), copy, verify, publish | S3, S4, S5 | inline | pending | — |
| T2 | Job + endpoints + last-run record in the state dir | S7, S8, S9 | inline | pending | — |
| T3 | Server-side cleanup of the old copy (double confirmation, record-bound) | S6 | inline | pending | — |
| T4 | Shared action predicate + cells | S2, S10 | inline | pending | — |
| T5 | `ContentFolderCard` extracted, `MoveContentDialog`, cleanup flow | S1, S9 | inline | pending | — |

Risk lines: T1/T2/T3 `Risk: item 1` (they decide where persisted content lives and T3 deletes it) · T1 also `item 6` · T4/T5 `item 6`. Item 1 gets one independent verifier at the end, as in steps 3 and 4.

## Log

L1 (Owner, verbatim) — "ok, y si construyes el 3ero, en que parte de Demiurgos llamo esa funcionalidad?"

L2 (Owner, verbatim) — "si, me parece perfecto que vaya alli" → `/perfil` → Respaldo.

L3 (Owner, verbatim) — "si, incluyelo con doble confirmacion" → U5/T3 included: deleting the old copy from the app, with double confirmation.

L4 (design decision D1) — the moved set is the backup's own author-content classification plus `.env`, not "the whole folder". Reason: the content root may legitimately be a checkout (this machine's is), and copying a repository is not moving the author's worlds. The inventory includes unrecognised top-level members by default, so a new folder is not silently dropped.
