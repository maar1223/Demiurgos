# Guided ficha body render by narrative-level specimen

Branch: `feat/guided-ficha-body-render`, based on `master` (`78a3747`). Delivery: work-unit commits; no push/PR unless the Owner asks.
Runners: `.venv/bin/python -m pytest src/tools/demiurgos-suite/wiki/tests/`; `cd frontend && npx vitest run`; `cd frontend && npm run typecheck`.

## Specs

- **S1** "ok, y tienes que organizar que ejemplo sigue segun la profundidad del personaje, tienes eso en cuenta verdad?" — The body of a guided character sheet is rendered from the specimen pinned for the resolved narrative level (1º principal, 2º secundario, 3º relleno). Only the specimen STRUCTURE and LABELS are used; the illustrative example prose is never copied.
- **S2** "pero ya no tenias unos modelos de ejemplo en la skill de creacion de personajes? para eso existe." — Every canonical label maps to the candidate fields the session already holds (canon, proposals, observations). A value that does not map to a canonical label is still written as a `**Etiqueta:** valor` fallback instead of being dropped. A label with no value renders `_(pendiente)_`.
- **S3** "como asi que no es la "ficha linda" y si no lo es, que hay de incompatible con que lo sea o con que emprendamos el camino para que sea asi?" — The body is Markdown, never a YAML dump: no ```` ```yaml ```` blocks, no duplicated `Identity`/`Canon Anchors` sections, accents preserved (`allow_unicode=True`). Provenance stays only in the frontmatter.
- **S4** Decision B, verbatim: "ve con el B" (make the narrative level explicit instead of relying on the silent 1º fallback). The level is asked/recorded in the conversation when it is not known yet, and the destination card shows it ("Ficha de 1º nivel", "Ficha de 2º nivel", "Ficha de 3º nivel").
- **S5** The character body change is character-only: the generic flows (`sistema`, `cronologia`, `entidad`) keep their body byte-identically.
- **S6** Tests pin every rule above, including a structural check that the labels used by the renderer still exist in the pinned specimen carriers, so carrier drift is caught.

## Assumptions

- The pinned carriers are the format authority; their example prose is not content. The renderer keeps their level-specific shape: sectioned bullets for 1º, flat bold labels for 2º and 3º.
- The guided minimum requires identity + desire, so a `Deseo` label is rendered even though the specimens express it as `Metas`/`Conflicto`. This is the only additive label.
- Existing graph evidence (`conflicts`, `unresolved_references`) is preserved as trailing sections instead of being silently dropped.

## Tasks

- [x] T1 branch + feature document + Engram mirror (S1–S6). Route: inline. Evidence: branch `feat/guided-ficha-body-render`; this file + Engram topic `odd/guided-ficha-body-render/tasks`.
- [x] T2 `guided_character_body.py`: per-level skeletons, field→label mapping, `_(pendiente)_` gaps, fallback, Unicode-safe prose; unit tests (S1–S3, S6). Route: inline. Evidence: 13 tests RED (module missing) → GREEN; `test_guided_character_body.py` 14 passed.
- [x] T3 wire the renderer into `serialize_entity` for `entity_type == "personaje"` only; update the existing character serializer test; assert generic flows stay byte-identical (S3, S5). Route: inline. Evidence: `test_guided_character_domain.py` 58 passed including the generic `## Identity` body regression; full BE 5112 passed/26 skipped.
- [x] T4 decision B: provider flow hint asks/records the level, public state exposes `target_level`, sidebar card + es/en copy, BE/FE tests (S4). Route: inline. Evidence: `test_guided_character_provider.py`, `test_guided_context_budget.py`, `test_guided_character_api.py`, `AIAssistantSidebar.test.tsx` 67 passed; typecheck clean; full FE 1768 passed.
- [x] T5 docs + full verification + independent verifier (high risk: persisted ficha format). Route: delegated verifier. Evidence: docs §10.1/§10.7/§10.8; `payload_manifest.json` regenerated (190 files, includes `guided_character_body.py`); full BE 5112 passed/26 skipped; FE 1768 passed; `npm run typecheck` clean.

## Log

- **L1 (Owner request, verbatim):** "continuaemos desde checkpoint". Checkpoint `nec/checkpoint` scope: render the ficha body following the level specimen, and make the narrative level explicit (decision B).
- **L2 (Owner decision, verbatim):** "ve con el B".
- **L3 (baseline, 2026-11-08):** `master == origin/master` at `78a3747`, clean tree. Focused baseline: `test_guided_character_domain.py` + `test_convergence_injection.py` 87 passed.
- **L4 (implementation, 2026-11-08):** `guided_character_body.py` renders 1º (7 sectioned bullets), 2º and 3º (flat bold labels) from hardcoded skeletons derived from the pinned carriers; every label is asserted against its carrier. `serialize_entity` renders the character body for `entity_type == "personaje"` and keeps the YAML body for the other flows. `resolve_candidate_nivel` now unwraps stored `{"value": …}` records (a real delta previously fell back to 1º silently). Decision B: `GuidedRequest.flow_entity_type` adds the level instruction for characters, `_guided_public_state` exposes `target_level`, and the destination card shows "Ficha de {nivel} nivel". Verified: full BE 5112 passed/26 skipped; FE 1768 passed; typecheck clean; `payload_manifest.json` regenerated so the packaged app boots.
