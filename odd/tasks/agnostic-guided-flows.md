# Agnostic guided flows (Sistemas as the first new case)

Branch: `feat/agnostic-guided-flows`, based on the integration line `feat/sistema-foundational-skill` + merge of `feat/skill-chat-guided-method` (Owner-approved). Delivery: work-unit commits, no PR.
Runners: `.venv/bin/python -m pytest src/tools/demiurgos-suite/wiki/tests/`; `cd frontend && npx vitest run`; `cd frontend && npm run typecheck`.

## Specs

- **S1** "A skill that produces a persistible, verifiable entity can declare a guided flow, and one generic engine runs it. Sistemas is the first new case. The method text stays in the skill; the flow contract (what it produces, where it lands, when it is complete, what it indexes) is declared and server-validated."
- **S2** "El engine debe ser agnóstico: no character-specific branches in generic code. Character, Sistemas and any future entity differ only by their declared binding." Refined by the Owner: "la skill declara la forma; el kernel decide la sección y los mínimos", and imported skills only inherit through lineage.
- **S3** "A published Sistemas skill that declares the guided flow offers the consent card on 'crear un sistema' intent, with a method selector (factory + eligible systems methods)."
- **S4** "Accepting a proposal persists a system entity at the agreed location, validates OKF minimums, indexes it, and echoes the method; rejecting writes nothing and indexes nothing." Agreed location: `lore/<slug>.md` with `type: Sistema`; minimums: identity + origin + limit.
- **S5** "The character flow keeps its current behavior byte-identically (regression suite green)."
- **S6** "A method from another flow is rejected at session start and at legacy activation/rollback routes with a clear 422; no mutation on rejection."
- **S7** "Invalid or incomplete flow declarations fail at publish (fail closed); only published, validated skills can bind a flow; the client never supplies the binding."
- **S8** "Existing stored activations and session snapshots are preserved."
- **S9** "No character-specific branch appears in the generic engine; character behavior is one profile among others."
- **S10** "Docs updated (`tool-workshop.md`, `skill-runtime-consumption-contract.md`, the subsystem doc, and the new feature doc)."
- **S11** Out of scope: Cronología, chat routing, companions, skill content rewrites, publishing/PRs/version bumps, the Skill Mother canvas declaration UI (phase two), RDD.

Owner decisions taken (verbatim):
- "en cuanto al alcance tengo una pregunta: Que pasará en un futuro con las nuevas Skills? tambien será un problema esto si es que se crean desde el taller de herramientas con la skill madre?"
- "si, adelante" (approves the proposal and the refined decision 3).

## Tasks

- [x] T1 integration line: branch from `feat/sistema-foundational-skill`, merge `feat/skill-chat-guided-method`, resolve 5 conflicts (S5, S8). Route: inline. Evidence: merge `a73b8915`; BE 4010 passed/18 skipped (2 known order-dependent `test_gateway_hooks` failures green in isolation); FE 1470 passed; typecheck clean.
- [ ] T2 kernel declaration: `guided_flow` compiler field + bounded validation + conditional digest + kernel entity→section allowlist + profile resolution (S1, S2, S7). Route: inline.
- [ ] T3 kernel profile use: generic minimums gate, server questions, generic serializer; character output byte-identical (S2, S5, S9). Route: inline.
- [ ] T4 library: `is_method_for_flow` + declaration-authoritative lineage + per-flow listing + legacy wrappers (S6, S9). Route: inline.
- [ ] T5 protocol/store: pinned flow profile in the session snapshot, durable round-trip, generic completion (S1, S8). Route: inline.
- [ ] T6 API: generic `/api/{mundo}/guided/*` routes + legacy aliases, flow echo, consent flow, `guided-methods?flow=`, guards on start/activate/rollback (S3, S4, S6, S7). Route: inline.
- [ ] T7 intent: flow-neutral semantic prompt + server-side flow resolution from declared triggers, fail closed on ambiguity (S3, S7). Route: inline.
- [ ] T8 frontend: generic guided client/hook/types, consent copy and method selector per flow, system copy, no activation vocabulary (S3, S9). Route: inline.
- [ ] T9 seed: Sistemas `1.1` declaring `guided-flow`; `1.0` unchanged (S1, S7). Route: inline.
- [ ] T10 docs, full verification, independent read-only verifier over this document (S1–S11). Route: delegated verifier.

## Log

- **L1 (Owner request, verbatim, key goal and acceptance criteria):** "A skill that produces a persistible, verifiable entity can declare a guided flow, and one generic engine runs it. Sistemas is the first new case. The method text stays in the skill; the flow contract (what it produces, where it lands, when it is complete, what it indexes) is declared and server-validated." / "The engine must be agnostic: no character-specific branches in generic code." / "A published Sistemas skill that declares the guided flow offers the consent card on 'crear un sistema' intent, with a method selector (factory + eligible systems methods)." / "Accepting a proposal persists a system entity at the agreed location, validates OKF minimums, indexes it, and echoes the method; rejecting writes nothing and indexes nothing." / "The character flow keeps its current behavior byte-identically (regression suite green)." / "A method from another flow is rejected at session start and at legacy activation/rollback routes with a clear 422; no mutation on rejection." / "Invalid or incomplete flow declarations fail at publish (fail closed); only published, validated skills can bind a flow; the client never supplies the binding." / "No character-specific branch appears in the generic engine; character behavior is one profile among others." / "Existing stored activations and session snapshots are preserved." / "Docs updated (`tool-workshop.md`, `skill-runtime-consumption-contract.md`, the subsystem doc, and the new feature doc)." Full request: session log 2026-10-22.
- **L2 (discovery):** the Sistemas seed lives only on the unmerged `feat/sistema-foundational-skill` branch; `feat/cronologia-foundational-skill` is stacked on it; `feat/skill-chat-guided-method` is a sibling off `master`. Merging Sistema + chat method conflicts in 5 files (4 FE tests + `messages.ts` + `methodology_library.py`).
- **L3 (Owner decision):** Sistemas only; `lore/<slug>.md` + `type: Sistema`; manifest `guided_flow` declaration validated by the compiler; `target_section` is kernel-owned (not in the manifest); eligibility = declaration first + lineage inheritance; imported skills inherit only; one generic UI; minimums identity + origin + limit; base = integration line above.
- **L4 (integration evidence):** merge commit `a73b8915`; frontend conflict resolution keeps the chat-availability product change and the Sistemas trigger-collapse UX; `methodology.state.triggerToggle` restored, activation keys stay removed. BE 4010 passed, 18 skipped, 2 known order-dependent `test_gateway_hooks` failures green in isolation; FE 1470 passed; typecheck clean.
