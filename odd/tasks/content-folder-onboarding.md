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

S9 — Onboarding offers it, before the first world. A `content_folder` step enters `STEP_ORDER` before `world` in the derived flow (the tuple also carries the optional remote steps between them; the visual chain is step0 → account → content_folder → world), is non-blocking, and never resurrects onboarding for an install that already completed it.
Acceptance: a fresh install reaches the step; an install whose onboarding is already complete keeps `completed: true` and never sees it again.

S10 — The backup picker warns in the UI about a destination that overlaps the content root, so the API's 400 never arrives as a surprise.
Acceptance: choosing such a folder shows the reason before the request is sent.

## Tasks

| ID | Task | Specs | Route | Status | Commit |
|---|---|---|---|---|---|
| T0 | Installer: `--data-root`/`-DataRoot` persists the choice; env keeps its meaning and seeds `.env`; visible notice | S1-S5 | inline | done + post-verification fixes (empty flag fails, pointer JSON-escaped) | `e01797eb` + fix commit |
| T1 | `GET /api/data-root` with disk facts | S6 | inline | done (14 cells; mutation check: each guard removal fails its own cells) | `c9d2bf0d` |
| T2 | `POST /api/data-root` with the guards | S7, S8 | inline | done (same commit) | `c9d2bf0d` |
| T3 | `content_folder` step in `STEP_ORDER` | S9 | inline | done (RED: missing import -> 16 passed; 3 old flow pins updated) | `b55ef511` |
| T4 | Frontend step: show, change, diagnose | S9, S10 | inline | done | `b55ef511`, `37568d64` |

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

L10 (T3) — `content_folder` enters `STEP_ORDER` between `account` and `world`, is NOT blocking, and is satisfied by an existing world (`content_folder_done = recorded or world_exists`). Three cells encoded the old flow (`current_step` world right after the account) and were updated in the same commit, not worked around. `commit_account_created` now writes `current_step = "content_folder"` so the persisted hint matches the derived flow.

L11 (T4) — Component `ContentFolderStep` + `api/contentRoot.ts` + 15 catalogue keys (es/en). The step shows world count and free space from the API, offers the change form only when the environment does not pin the root, and after a change shows the restart panel instead of the continue button — because a world created before the restart would land in the folder the process booted with. A refusal from `POST /api/data-root` is shown as its own message.

L12 (a guard I did not write, that caught me) — `frontend/src/i18n/__tests__/catalogueGuard.test.ts` rejects voseo in the Spanish catalogue: my first copy used "podés" and "Reiniciá". Rewritten to neutral Spanish ("puedes", "Reinicia", "desde aquí"). The frontend suite would have failed in CI otherwise.

L13 (evidence) — Backend: **4423 passed, 24 skipped**. Frontend: 1583 tests in 128 files green, `tsc --noEmit` clean, `npm run build` OK (chunk-size warning pre-existing). The served `frontend/dist` was rebuilt, so the step can be seen with a forced reload.

L14 (S10, closed) — `lib/contentRootOverlap.ts` mirrors `backup/state.py`: equal, inside or containing, in both directions. The picker refuses locally before sending, and the card warns when an already-chosen destination overlaps (the case where the content folder moved after the destination was picked). 11 cells on the helper and 2 on the section; the mock's default content root is a sibling so the pre-check stays out of the way of the other 18 cells. One difference from the server, recorded on purpose: a Windows path compares case-insensitively and a POSIX one does not, and `C:\` keeps its separator because `C:` is not a folder that reads as itself.

L15 (final verification) — Backend **4423 passed / 24 skipped**. Frontend **1596 tests in 129 files**, `tsc --noEmit` clean, `npm run build` OK. `frontend/dist` rebuilt, so the step and the backup warning are visible with a forced reload. Branch `feat/content-folder-onboarding`: 5 commits, stacked on the step-3 branch, not pushed — push/PR are the Owner's decision.

L16 (independent verification, item 1) — A read-only verifier ran over the whole step-4 delta against baseline `ee8cdcef`, in a scratch copy, and found **two blockers** the suite did not see:

| Blocker | Why it mattered | Fix |
|---|---|---|
| **B1 — the change was unreachable in the shipped app.** `scripts/start-demiurgos.sh` (and the three `.ps1` launchers) always `export DEMIURGOS_DATA_ROOT` from the resolved pointer, so `origin == "env"` in production; the router refused every POST on that condition and the UI hid the form `origin === "env"` | The whole point of step 4 (choose another folder from the app) silently did not work — only a test that mimicked the launcher's environment could see it | `env_pins_root()`: the environment pins only when it DISAGREES with the pointer (or when there is no pointer). The payload reports `pinned`; the UI branches on it instead of on `origin` |
| **B2 — `--data-root ""` / `--data-root=` installed to the default with exit 0** | An explicit empty value is never a legitimate choice; silently falling back to Documents is exactly the "author did not notice" failure this step exists to remove | The flag now requires a non-empty path and fails with usage |

Advisories acted on: the pointer is JSON-escaped before it is written (a folder containing `"` or `\` used to produce an unreadable record or a silently different path); `restart_required` is now false when the POST repeats the folder already in use; `pending_restart` is false when the root is pinned (a restart cannot outrank the environment); the browser helper collapses `.`/`..` lexically like the server resolves them.

Advisories left open, with the reason: the browser cannot resolve symlinks (the server still refuses, so the pre-check stays a courtesy); UNC paths are out of domain for that courtesy; `payload_manifest.json`'s `source_commit` records the parent commit because the generator stamps HEAD.

Regression cells committed from the verifier's report: launcher-exported env does not freeze the folder, an empty flag fails, the pointer round-trips a quote and a backslash, a world keeps an old install complete, and dot segments collapse.

L17 (final) — After the verification fixes: backend **4430 passed / 24 skipped**, frontend **1598 tests in 129 files**, `tsc --noEmit` clean, `npm run build` OK. PR #54 (base `feat/content-state-separation-3`) **16/16 checks green**, including the four backend platforms, PowerShell 5.1 and both payload audits. One self-inflicted catch worth recording: the installer guard `test_no_git_at_all_in_installer` forbids the substring `git`, and my escaping comment said "le-git-imately" — reworded, zero occurrences. The `item 1` independent verification is closed: two blockers found, both fixed with regression cells that fail against the pre-fix code.
