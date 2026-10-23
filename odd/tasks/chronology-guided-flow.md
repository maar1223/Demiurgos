# Chronology guided flow (Cronología as the third flow)

Branch: `integration/guided-flows`. Delivery: work-unit commits, no PR. Runner: `.venv/bin/python -m pytest src/tools/demiurgos-suite/wiki/tests/`; `cd frontend && npx vitest run`; `cd frontend && npm run typecheck`.

## Specs

- **S1** Owner authorization: "si, sigue con el cableado" — wire the existing Cronología method into the guided engine built by `agnostic-guided-flows` (which left it out of scope in its S11).
- **S2** Chat intent for a chronology (`"quiero crear una cronología"` / `"I want to create a chronology"`) offers the guided consent card with the chronology copy, and the method selector lists the eligible chronology method (`narrative-chronology-creation`), never a character or system method.
- **S3** Accepting a proposal persists the entity at `lore/<slug>.md` with `type: Cronologia`, validates the OKF minimums (identity + `evento`), indexes it in the graph, and echoes the method; rejecting writes and indexes nothing.
- **S4** Character and System flows keep their current behavior byte-identically (existing regression suites green, character serializer bytes unchanged).
- **S5** A chronology method declares `guided_flow` in its manifest; invalid declarations fail closed at publish (kernel-owned section, minimums and target). The shipped seed carries the declaration.
- **S6** UI copy exists in es/en for the chronology consent card and its identity question; the client never supplies the binding or the copy.
- **S7** Full backend and frontend suites plus typecheck are green, with the new behavior pinned by tests.
- **S8** Documentation reflects the third flow: `skill-runtime-consumption-contract.md` §2/§2.1 and the subsystem doc §10.7.

Scope assumptions (explicit):
- The chronology seed files live only on `feat/cronologia-foundational-skill`; only that seed directory is imported, not the branch.
- The shipped seed is bumped `1.0` → `1.1` and declares the flow, following the Sistemas precedent (`1.0` unchanged in history, `1.1` declares).

Out of scope: editing existing chronology personas, the Skill Mother canvas declaration UI, publishing, PRs, version bumps beyond the seed's `1.1`, and RDD.

## Tasks

- [x] T1 seed: import `data/methodology/seeds/narrative-chronology-creation/` from `feat/cronologia-foundational-skill`; bump to `1.1` with the `guided_flow` declaration; regenerate `checksums.json`. Inline. Evidence: catalog loads 3 entries and compiles clean; `checksums.json` regenerated from disk bytes.
- [x] T2 kernel: `GUIDED_CHRONOLOGY_FLOW`, `ENTITY_TYPE_BY_FLOW`, `FOUNDATIONAL_METHOD_BY_FLOW`, `GUIDED_FLOW_IDS`, `UI_COPY_KEYS` += `chronology`. Inline. Evidence: `test_guided_flow.py` 16 passed (RED first: copy key rejected).
- [x] T3 domain: chronology identity copy in `_IDENTITY_COPY_BY_FLOW`. Inline. Evidence: identity question es/en + event gate; `test_guided_character_domain.py` chronology tests.
- [x] T4 server: chronology consent suggestion text. Inline. Evidence: `test_chronology_consent_copy_is_flow_specific`.
- [x] T5 frontend: `ui_copy_key` union, `toFlowEcho` admission, consent flow key resolution, `assistant.consent.body.chronology` es/en. Inline. Evidence: chronology consent card test selects the method and submits it; flow echo admitted.
- [x] T6 tests backend: chronology profile, minimum-question gate, serializer envelope, consent copy, seed declaration. Inline. Evidence: `test_guided_flow.py` 16, `test_guided_character_domain.py` 54, `test_guided_flow_api.py` 14, `test_methodology_seed.py` 42.
- [x] T7 tests frontend: flow echo admission, consent body selection. Inline. Evidence: `AIAssistantSidebar.test.tsx` 35 passed, `semanticIntent.test.ts` passed.
- [x] T8 payload manifest, docs, full verification. Inline. Evidence: `payload_manifest.json` 159 payload files (+3 seed files, source_commit `3e7608db`); docs updated in `skill-runtime-consumption-contract.md` §2.1 and the subsystem doc §10.7; BE 4069 passed / 18 skipped with only the 2 known order-dependent `test_gateway_hooks` failures (green in isolation); FE 1476 passed; typecheck clean.

## Log

- **L1 (Owner request, verbatim):** "si, sigue con el cableado". Context: after auditing that Personajes and Sistemas run through the guided engine and Cronología is only half-wired (method published, kernel tables present, no flow registration).

- **L2 (implementation discovery, 2026-10-22):** registering the flow was not enough. `_resolve_input_flow` iterated a hardcoded `(GUIDED_CHARACTER_FLOW, GUIDED_SYSTEM_FLOW)` and five other call sites plus `SUPPORTED_FLOW_TYPES` repeated the same literal set, so chat intent could never reach a third flow. Replaced every site with the kernel-owned `GUIDED_FLOW_IDS` (`sorted()` for a deterministic resolution order) and made `SUPPORTED_FLOW_TYPES` derive from it. `GUIDED_FLOW_IDS` was previously unused, which is why the omission was invisible.
- **L3 (scope, 2026-10-22):** the chronology seed only existed on `feat/cronologia-foundational-skill`; only the seed directory was imported, the rest of that branch stays untouched. The seed ships as `1.1` with the declaration and `1.0` remains in the published history, following the Sistemas precedent.
- **L4 (counts, 2026-10-22):** adding a third foundational seed updates explicit seed-count and seed-order locks across `test_methodology_seed`, `test_methodology_library`, `test_guided_character_api`, `test_payload_boot`, `test_per_flow_activation` and `test_api_server`. These are contract locks, not incidental assertions; each was updated with the new expected value, never loosened.
