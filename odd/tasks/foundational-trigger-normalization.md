# Foundational trigger normalization

Branch: `integration/guided-flows`. Delivery: work-unit commits, no PR. Runner: `.venv/bin/python -m pytest src/tools/demiurgos-suite/wiki/tests/`; `cd frontend && npx vitest run`; `cd frontend && npm run typecheck`.

## Specs

- **S1** Owner authorization: "si, normalizalo entonces" — normalize the three foundational triggers so all of them obey the skills-index budget.
- **S2** Every foundational trigger is one sentence of at most 57 characters that names what the skill produces and its distinguishing spine. No "Metodología fundacional para co-crear un…" boilerplate; the method's prose stays in `source.md`.
- **S3** Exact texts, verbatim:
  - Personajes (55): `Co-crea personajes: identidad, deseo, conflicto y arco.`
  - Sistemas (45): `Co-crea sistemas: origen, qué exige y límite.`
  - Cronología (57): `Co-crea sucesos y eras: qué ocurrió, cuándo y qué cambió.`
- **S4** Published records are immutable: the change ships as new versions (`narrative-character-creation@1.3`, `narrative-system-creation@1.2`, `narrative-chronology-creation@1.2`); the previous versions stay in the history and nothing migrates.
- **S5** Rendering a seeded trigger produces no `description-*` issue (the current character and system seeds emit `description-too-long`).
- **S6** Guided-flow resolution keeps working: the per-flow defaults resolve to the new versions, and no flow binding changes.
- **S7** Tests and docs are updated; backend and frontend suites plus typecheck are green.

Out of scope: rewriting the method bodies, changing the guided-flow declarations, and any other skill's trigger.

## Tasks

- [x] T1 seeds: apply the three texts, bump the versions, regenerate every `checksums.json`. Inline. Evidence: `narrative-character-creation@1.3`, `narrative-system-creation@1.2`, `narrative-chronology-creation@1.2`; every index label renders verbatim with no `description-*` issue; the method descriptions are untouched.
- [x] T2 pins: update version and digest locks across the wiki tests (the description feeds the canonical digest). Inline. Evidence: character canonical digest moved to `b484b581…`; version pins updated across seed, compiler, library, guided-flow and API tests.
- [x] T3 regression test: every seeded trigger renders inside the bound with no `description-*` issue. Inline. Evidence: `TestFoundationalTriggers` (3 tests) plus the renderer's trigger tests and the existing `test_real_seed_injects_full_system_method_contract`, which still passes: the injected contract keeps the nine markers and the five origin classes.
- [x] T4 `payload_manifest.json` regeneration. Inline. Evidence: no new files, so the file list is unchanged (16 seeded files); only file contents changed.
- [x] T5 docs: version references to the foundational seeds. Inline. Evidence: runtime contract §2.1 documents the trigger/description split and the approval binding; version references updated in the subsystem, tool-workshop and foundational-skills docs.
- [x] T6 full verification (backend + frontend + typecheck) and work-unit commit. Inline. Evidence: BE 4082 passed / 18 skipped with only the 2 known order-dependent `test_gateway_hooks` failures (green in isolation); FE 1481 passed; typecheck clean.

## Log

- **L1 (Owner request, verbatim):** "si, normalizalo entonces". Context: the audit showed character at 351 characters and system at 995 against a 57-character render budget, while chronology's 50 characters was the only compliant trigger; the owner then authorized normalizing all three with the proposed texts.

- **L2 (implementation blocker, 2026-10-22):** the trigger text is **not** a label only. `project_contract_markdown` builds the transversal contract injected into chat from `name + version + description + phases`. The 995-character system description was carrying the distilled method: the nine question markers `(1)`–`(9)` and the five origin classes lived there, not in `source.md`. Applying the normalized texts removes those two rails from what the assistant receives (measured: old projection has all four rails, new projection loses the markers and the origin classes; budget drops from ~399 to ~162 tokens). `test_real_seed_injects_full_system_method_contract` guards exactly that and fails. The three seed/test edits were reverted; the tree is green again at `6330d6be`-independent state (HEAD `b8e067d7`). The real defect is that one field serves two surfaces with incompatible budgets: the skills-index label (≤57) and the injected method contract (≤1000 tokens).
- **L3 (Owner decision, verbatim):** "si, la A" — split the field. Implemented: the manifest gains an optional `trigger` (≤60, what the index renders and what "Aprobar gatillo" approves); `description` stays the method summary projected into the injected contract. `approve_trigger` now writes the trigger and never overwrites the description; the publish gate binds the trigger digest; editing the description no longer revokes the approval, editing the trigger does. Records without `trigger` fall back to the bounded description (byte-identical). A trigger identical to the description is canonical-equivalent (never moves a pre-existing digest).
- **Historical decision note:** (superseded by L3) choose between (A) splitting the field — add an optional manifest `trigger` (≤60, index label, what "Aprobar gatillo" approves) and keep `description` as the method contract for injection, with a bounded-description fallback for records that lack `trigger`; or (B) leaving the long descriptions and accepting that the index label is truncated with `…`. Option (C) — short description everywhere — is rejected: it silently starves the injected method and would require deleting its regression test.

- **L4 (follow-up, Owner-approved: "si ve con la C y repara lo otro"):** (a) the router's classifier label now prefers `trigger` over `description` (`skill_router._description_for`), so both indexes read the same text; (b) the sidebar row of a companion whose pinned version is older than the latest published now offers a one-click "Actualizar chat" (title names both versions), wired through `ToolWorkshop → TallerExplorerSidebar → MethodologyLibrary → TallerTree`; no silent re-point. Evidence: `test_candidate_label_prefers_the_authored_trigger`, `TallerTree` drift tests (3), `ToolWorkshop` update test; BE 4083 passed / 18 skipped with only the 2 known order-dependent gateway failures; FE 1487 passed; typecheck clean.
