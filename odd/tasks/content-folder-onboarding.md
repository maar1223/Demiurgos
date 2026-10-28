# Step 4 — the author chooses where their worlds live

Branch: `feat/content-folder-onboarding` (stacked on `feat/content-state-separation-3`, PR #53) · Base: `feat/content-state-separation-3` · Tests: `../../../../.venv/bin/python -m pytest tests -q` from `src/tools/demiurgos-suite/wiki` · Delivery: work-unit commits on the stacked branch; push/PR are the Owner's decision.

## Specs

S1 — Install-time choice, persisted. Quoted from the Owner: "no es interesante que durante la instalacion de Demiurgos el usuario pueda escoger en que carpeta quiere que vivan sus mundos? inclusive en que disco quieren que vivan?"
Acceptance: `--data-root PATH` (POSIX) and `-DataRoot PATH` (Windows) set the content root, **write the pointer** to that absolute path, create the four content folders and seed `.env` when absent. A relative path is normalized against the installer's cwd before anything is written.

S2 — The installer asks nothing. Quoted from the Owner's decision: "vamos con el 1", where option 1 was "bandera + aviso, y el picker en el primer arranque".
Acceptance: neither installer reads stdin for the data root; no `read`, no `Host.UI.PromptForChoice`, no TTY detection. An unknown argument fails with usage instead of silently installing to the default.

S3 — The choice is visible. The installer prints where the content will live, how to change it, and — when the root came from `DEMIURGOS_DATA_ROOT` without the flag — that the choice did **not** get recorded.
Acceptance: the output names the absolute content root and the flag; the env-only path says explicitly that the pointer was not written.

S4 — The env keeps its meaning and loses its trap. `DEMIURGOS_DATA_ROOT` still wins and still leaves the pointer untouched, but it now seeds `.env` (when absent) and creates the content folders. Verified defect this fixes: an install with the env set left no `.env`, so `DEMIURGOS_AUTH_MODE` was absent and the app failed closed (401 on gated writes) — the incident `test_install_auth_gated_write.py` exists to prevent.
Acceptance: `DEMIURGOS_DATA_ROOT=<empty dir>` + seed-only produces the four folders and a seeded `.env`, and writes no pointer.

S5 — Explicit beats preserved. A pointer that already exists and points elsewhere is re-oriented **only** when the flag was given, and the change is announced. Without the flag the pointer stays byte-identical.
Acceptance: `--data-root B` over a pointer pointing at A rewrites it to B and says so; an env-only run over a pointer leaves the bytes unchanged.

S6 — The app can report the content root. `GET /api/data-root` returns the resolved path, its origin (`env`/`pointer`), whether the folder is usable, and the disk facts the picker needs (free space, filesystem, sync/network/removable verdict), reusing `sync_folder.classify_target`. An unconfigured root is reported honestly instead of a 500.
Acceptance: every field is derived, never guessed; a streaming/network target is reported as such before the author can pick it.

S7 — The app can change it, safely. `POST /api/data-root` writes the pointer atomically through `data_root.write_pointer` and refuses: a path that is a file, the state root (or inside it), and a target that is empty while the current root holds worlds. Nothing is ever moved or copied.
Acceptance: a refused request persists nothing; an accepted one leaves the previous content untouched and reports the new path.

S8 — Decision (the Owner did not answer (a)/(b)/(c); the conservative branch is taken and recorded here): changing to a folder that holds no content while the current root holds worlds is **refused** until the chosen folder already holds content. Reversible by relaxing one predicate if the Owner prefers a warning.
Acceptance: the refusal names both folders and never leaves the old content unreachable.

S9 — Onboarding offers it, before the first world. A `content_folder` step enters `STEP_ORDER` immediately before `world`, is non-blocking, and never resurrects onboarding for an install that already completed it.
Acceptance: a fresh install reaches the step; an install whose onboarding is already complete keeps `completed: true` and never sees it again.

S10 — The backup picker warns in the UI about a destination that overlaps the content root, so the API's 400 never arrives as a surprise.
Acceptance: choosing such a folder shows the reason before the request is sent.

## Tasks

| ID | Task | Specs | Route | Status | Commit |
|---|---|---|---|---|---|
| T0 | Installer: `--data-root`/`-DataRoot` persists the choice; env keeps its meaning and seeds `.env`; visible notice | S1-S5 | inline | done (RED: 5 failed -> GREEN: 5 passed; installer contract 113 passed/5 skipped) | `e01797eb` |
| T1 | `GET /api/data-root` with disk facts | S6 | inline | done (14 cells; mutation check: each guard removal fails its own cells) | `c9d2bf0d` |
| T2 | `POST /api/data-root` with the guards | S7, S8 | inline | done (same commit) | `c9d2bf0d` |
| T3 | `content_folder` step in `STEP_ORDER` | S9 | inline | pending | — |
| T4 | Frontend step: show, change, diagnose | S9, S10 | inline | pending | — |

Risk lines: T0 `Risk: item 1` (defines where persisted content lives) + `item 3` (the installer's documented env contract changes) · T2 `Risk: item 1` (moves the pointer, hides/loses reach to existing content if wrong) · T3 `Risk: item 3` (`STEP_ORDER` is shared with the frontend and with `status_from`) · T1/T4 `Risk: item 6`. Item 1 units get one independent verifier at the feature's end.

## Log

L1 (Owner, verbatim) — "y por cierto, no es interesante que durante la instalacion de Demiurgos el usuario pueda escoger en que carpeta quiere que vivan sus mundos? inclusive en que disco quieren que vivan? me pareceria algo util a que obligatoriamente sea en una carpeta en especial"

L2 (Owner, verbatim, after the three options were explained) — "vamos con el 1"
Option 1 = no installer prompts: the flag decides, the output says where the content lives, and the human choice happens in the picker at first run.

L3 (evidence, before designing) — install with only `DEMIURGOS_DATA_ROOT` set, hermetic, seed-only:

```
install-demiurgos: using DEMIURGOS_DATA_ROOT=/tmp/.../worlds (env override; pointer untouched)
carpeta elegida: vacía · puntero: NO · .env: NO · DEMIURGOS_AUTH_MODE: ausente (-&gt; la app falla cerrada)
```

Consequence: the choice did not survive the install, and any later start without the env var would bootstrap the Documents default and look at a different folder, silently. That is why S1 writes the pointer and S4 seeds `.env`.

L4 (scope decision) — the branch stacks on `feat/content-state-separation-3` because PR #53 is open and T0 edits the same bootstrap function; a stacked PR keeps the diff reviewable. Push/PR stay the Owner's decision.

L5 (T0, installer) — `--data-root`/`-DataRoot` are the install-time choice and they persist; the env keeps its run-time meaning, now creates the folders and seeds `.env`, and says out loud that it did not record the choice. Observed RED first (5 cells), then green; the whole `test_installer_contract.py` stayed green (113 passed / 5 skipped). No shellcheck on this host: `bash -n` plus the behavioural cells are the check, and the `.ps1` stays ASCII.

L6 (T1/T2, API) — Tests were written after the module here, so no RED was observed; a mutation check replaced that proof: disabling the state-overlap guard fails the three `machine_state` cells and disabling the worlds guard fails `an_empty_folder_never_hides_existing_worlds`; restoring returns 14 green. Recorded rather than hidden.

L7 (payload lesson, this cost a full-suite round) — `api_server.py` imports a new module, so the runtime payload must list it: 20 failures across the payload-boot, semantic-e2e, sync-lore and installer-boot suites were all `ModuleNotFoundError: content_root_router`. Fix: `scripts/derive_payload_manifest.py` (169 files, +1). Any new runtime module needs that regeneration before the suite can be believed.

L8 (a saved choice needs a restart) — `_project_root()` caches into `PROJECT_ROOT` and every store is built from it, so rewriting the pointer cannot rebind the running process safely. POST therefore returns `restart_required` and GET reports `pending_restart` while the pointer and the folder in use disagree. The UI step (T4) must offer a restart, not a silent reload.

L9 (closure so far) — Full suite: **4417 passed, 24 skipped** (4395 before this feature, +22 cells). `Risk` for T1/T2 as recorded above; T2 is `item 1` and still owes its independent verifier at the feature's end.
