# Remove the "Offline / dispositivo" card from Preferencias

**Feature id**: `remove-offline-card-preferencias`
**Branch**: `feat/profile-information-architecture-08-consistency`
**Status**: in progress
**Author decision**: option A — remove the card AND the `offline` readiness payload.

## Objective

Preferencias stops rendering the "Offline / dispositivo" card, and the readiness
endpoint stops returning the `offline` breakdown that only that card consumed.

## Problem

The card is noise:

1. It states the same single bit three times: the card badge ("Configurado"),
   the "Núcleo local" row (`Listo`) and `local_ready` are all derived from
   `cards["offline"]`, itself the local storage round-trip probe
   (`readiness.py:164,178`).
2. That bit has no reachable state and no action: if the local disk round-trip
   fails, Demiurgos does not run at all, so the page cannot be read; and the
   card offers nothing to do.
3. "Remoto" lists what the user does NOT have, duplicating surfaces that own
   that state (Conexiones shows the assistant state; Captura de ideas owns
   Telegram), with no link and no action.
4. It is the last survivor of a card family already pruned twice by the same
   rationale (backup card removed — REQ-PIA-10 superseded; "Listo para trabajar"
   essential badges removed — REQ-PIA-02 narrowed). `keepCards` filters
   explicitly to `offline` (`ProfilePage.tsx:1152`), so Preferencias is now the
   locale form plus this orphan.
5. It duplicates a concept that already exists in another contract:
   `onboarding.py` has `REMOTE_STEPS = {ai, telegram, backup_handoff}` while
   `readiness.py` defines its own `REMOTE_CARDS = (telegram, backup, assistant)`.

## Why

The Author's stated principle for this area: remove everything that is
redundant or adds no real value. This is the same call already applied to the
backup card and the essential-badges block.

## Scope

### In scope
- `frontend/src/pages/ProfilePage.tsx` — drop the cards block and the offline
  rendering; keep the locale badge path (`cardState`/`cardLabel`/`STATE_META`
  for `locale`) and the inline locale form.
- `frontend/src/pages/ConfigurationCenter.tsx` — drop the `offline` `CARD_DEFS`
  entry and the now-unused `REMOTE_LABELS`.
- `frontend/src/api/types.ts` — drop `OfflineBreakdown` and the `offline` field.
- `frontend/src/__tests__/*` — drop the `offline:` fixture entries and the
  assertions on the removed card.
- `src/tools/demiurgos-suite/wiki/readiness.py` — drop `project_offline` and
  `REMOTE_CARDS`.
- `src/tools/demiurgos-suite/wiki/api_server.py` — drop the `offline` key from
  the readiness response and the `project_offline` import.
- `src/tools/demiurgos-suite/wiki/tests/{test_readiness,test_api_server}.py`.

### Out of scope (do NOT touch)
- `project_cards` and the generic `cards` map, including `cards["offline"]`.
  Only the breakdown projection goes; the card map keeps its shape.
- `onboarding.py` / the onboarding status contract, including its own
  `remote_pending` from `REMOTE_STEPS`. That is a different contract.
- Routing, section ids, the status header, and the locale form behaviour.

## Tasks

| ID | Task | Route |
|---|---|---|
| T1 | Remove the offline card + dead cards block from `ProfilePage.tsx`, and the imports that become unused | delegated (writer) |
| T2 | Remove `offline` from `CARD_DEFS` and `REMOTE_LABELS` in `ConfigurationCenter.tsx` | delegated (writer) |
| T3 | Remove `OfflineBreakdown` + the `offline` field in `types.ts` | delegated (writer) |
| T4 | Migrate the frontend test fixtures and drop the removed-card assertions | delegated (writer) |
| T5 | Remove `project_offline` + `REMOTE_CARDS` and the response key in the backend | delegated (writer) |
| T6 | Update `test_readiness.py` + `test_api_server.py` | delegated (writer) |
| T7 | Verify: backend pytest, frontend vitest, frontend typecheck | parent |

## Acceptance criteria

- Preferencias renders the inline locale form and nothing else; no
  "Offline / dispositivo" heading exists anywhere in the UI.
- `GET /api/onboarding/readiness` no longer contains an `offline` key, and
  `cards` keeps its existing shape.
- The onboarding status contract is byte-identical in behaviour.
- No unused import, constant, type, or test fixture is left behind.

## Checks

- `pytest src/tools/demiurgos-suite/wiki/tests/test_readiness.py src/tools/demiurgos-suite/wiki/tests/test_api_server.py src/tools/demiurgos-suite/wiki/tests/test_onboarding.py -q`
- `cd frontend && npm run typecheck`
- `cd frontend && npm test`

## Spec deltas to record as an amendment

1. **REQ-PIA-02 narrowed (again)**: `preferencias` content becomes
   "inline locale form" only — the `offline/device readouts` clause is removed.
   This repeats the narrowing already recorded for the essential-badges block.
2. **REQ-PIA-10**: the `offline` `CARD_DEFS` entry is removed as dead, exactly
   as the `backup` entry was. REQ-PIA-10 is already superseded.
3. **CON-PIA-01 superseded for this delta**: the constraint reads "No backend or
   auth-contract change", and removing the `offline` field from the readiness
   response IS a (subtractive) backend contract change. Recorded explicitly
   rather than smuggled.
4. **OC5 / OC12 / OC21 superseded for the offline card** (found by independent
   verification): the on-disk product contract
   `docs/architecture/onboarding-and-configuration.md` records CLOSED decisions
   that enumerate this exact card:
   - `:129` — "El estado offline es **visible** en el Centro de Configuración
     (tarjeta offline/dispositivo, sección 12), nunca un bloqueo silencioso."
     `[DECISIÓN CERRADA — OC5]`
   - `:285` — the section-mapping table row
     `| Offline/dispositivo | Estado de conexión y capacidades locales (sección 5) |`
   - `:340` — OC12 enumerates `offline/dispositivo` among the Configuration
     Center cards.
   - `:349` — OC21 lists `Offline/dispositivo` among the badge criteria.
   Removing the card supersedes those rows. The OC5 intent — never a *silent*
   blocker — is preserved by construction: the local core works offline and
   nothing blocks on connectivity; what is retired is the explicit readout.
   **This is the strongest argument for option B** (a single honest line) if the
   Author wants to keep the visibility mandate literally satisfied.

## Progress

- [x] T1..T6 implemented by one writer, then verified by the parent (452 backend
      tests, typecheck, 1281 frontend tests, live endpoint + rebuilt bundle)
- [x] T7 verified
- [x] Independent adversarial verification: `sound with nits`, nothing unsafe to
      ship; its two doc nits fixed, its traceability finding recorded as delta 4
- [ ] Spec amendment persisted in Engram
- [ ] Author decision on committing
