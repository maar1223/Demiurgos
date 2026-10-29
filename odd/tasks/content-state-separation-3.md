# Content/state separation — step 3 (default the content root to Documents/Demiurgos)

Branch: `feat/content-state-separation-3` · Base: `master` (`1af3e041`) · Tests: `../../.venv/bin/python -m pytest tests -q` from `src/tools/demiurgos-suite/wiki` · Delivery: work-unit commits on the feature branch; push/PR are the Owner's decision. Forecast: ~320 authored lines, one review slice.

## Specs

S1 — The bootstrap default of the content root becomes `<OS documents folder>/Demiurgos` on both platforms. Today it is `<install_root>/data`: `~/.demiurgos/data` on POSIX and `%LOCALAPPDATA%\Demiurgos\data` on Windows.
Acceptance: with neither `DEMIURGOS_DATA_ROOT` nor a pointer file, the installer and the launcher bootstrap a pointer whose `data_root` is `<documents>/Demiurgos`; no code path still defaults to `<install_root>/data`.

S2 — "Documentos" is resolved through the operating system's own contract, never hardcoded: on POSIX, `XDG_DOCUMENTS_DIR` read from `${XDG_CONFIG_HOME:-$HOME/.config}/user-dirs.dirs` with `$HOME/Documents` as the fallback; on Windows, `[Environment]::GetFolderPath('MyDocuments')` with `%USERPROFILE%\Documents` as the fallback.
Acceptance: on a desktop whose documents folder is localized (this machine: `XDG_DOCUMENTS_DIR="$HOME/Documentos"`), the bootstrap uses `~/Documentos/Demiurgos` and creates no `~/Documents`; a redirection of the folder (OneDrive Known Folder Move) is followed on Windows because the shell API resolves it.

S3 — The resolution order does not change, quoted from `INSTALL_LAYOUT.md` §2.4:
"existing env `DEMIURGOS_DATA_ROOT` → existing pointer file → bootstrap-once the default"
Acceptance: an env override never writes a pointer; an existing pointer is preserved byte-for-byte; only the third step changes.

S4 — No migration and no reorientation of existing pointers. The Owner's machine holds `~/.config/demiurgos/data-root.json` → `/mnt/3C2A86E52A869C10/proyectos_opencode/demiurgos` and is out of scope by decision ("ahora mismo no existe Demiurgos en mas ninguna maquina sino en la mia propia, asi que si hay que migrar algo solo seria en esta pc").
Acceptance: a pre-existing pointer pointing at `<install_root>/data` stays byte-identical after an install or a launcher start; nothing copies, moves or deletes author content.

S5 — The installer keeps seeding exactly what it seeds today, now under the new root: the folders `mundos`, `ideas`, `data`, `config`, and the `<data_root>/.env` seed with `DEMIURGOS_AUTH_MODE=local-dev`, `DEMIURGOS_LANGUAGE`, the bug-report relay URL, the bot handle and the optional `DEMIURGOS_WORLD`.
Acceptance: a fresh install under the new default creates those four folders and the `.env` inside `<documents>/Demiurgos`; an existing `.env` is still preserved byte-for-byte.

S6 — The `.env` keeps never shipping inside the payload.
Acceptance: no `.env` appears under `<install_root>/app/**` after an install.

S7 — After this step the separation is effective on a NEW Windows install: the content root lives in Documents and the state dir stays in `%LOCALAPPDATA%\demiurgos\data`. Installs whose pointer predates this step keep the inert configuration until the Owner reorients them, and the docs must say exactly that.
Acceptance: a fresh install's content root differs from the resolved state dir; the Windows note in `CONTENT_AND_STATE.md` is rewritten to scope the inertness to pre-step-3 pointers.

S8 — The contract docs stay true: `CONTENT_AND_STATE.md` (default table + Windows note) and `INSTALL_LAYOUT.md` (§1 data-root row, §2.4, §3). The CLI stack's pointer (`install.sh` → the checkout, `INSTALL_LAYOUT.md` §4) is deliberately out of scope.

S10 — Owner decision (this session): a backup destination that overlaps the content root is refused — equal to it, inside it, or containing it — at selection time and again when a run starts. Quoted from the Owner: "vamos con la 1 segun tu recomendacion y luego continuamos".
Acceptance: `write_destination` raises and persists nothing for all three shapes (symlinks resolved); `run_backup` refuses a persisted overlapping record with a remedy and publishes nothing (`meta/`, `snapshots/`, `current/`, `world-trash-index/` never appear inside the content root); the API answers 400 with a readable reason; a sibling folder is still accepted. The inventory-exclusion half of the original proposal is deliberately dropped: excluding the names `current`/`snapshots`/`meta` by name would also hide an author folder that legitimately carries one of them, and the refusal covers the same class.

S9 — Verification: every unit runs its own focused tests; the whole suite must stay at or above the 2b baseline of 4375 passed / 24 skipped.
Acceptance: `4375+ passed, 24 skipped` and the new cells green.

## Tasks

| ID | Task | Specs | Route | Status | Commit |
|---|---|---|---|---|---|
| T1 | POSIX launcher: documents resolver + new bootstrap default | S1-S4 | inline | done (RED: 4 failed -> GREEN: 13 passed) | `a6ffdeb7` |
| T2 | Windows launchers (`start-demiurgos.ps1`, `start-api.ps1`, `start-gateway.ps1`): same default | S1-S4 | inline | done (RED: 1 failed -> GREEN: 47 passed) | `dcb5f29c` |
| T3 | POSIX installer: same default + folder creation, with the behavioral acceptance cell | S1, S3-S7 | inline | done (RED: 2 failed -> GREEN: 106 passed/5 skipped) | `5c0177c5` |
| T4 | Windows installer: same default | S1, S3-S7 | inline | done (RED: 2 failed -> GREEN: 41 passed/5 skipped) | `e83541dd` |
| T5 | Contract docs | S7, S8 | inline | done | `a0dc865f` |
| T6 | Backup-destination overlap guard (`state.assert_destination_outside_content_root` + `write_destination` + `run_backup` + router 400) | S10 | inline | done (RED: 9 failed -> GREEN: 11 passed; 6 router fixtures moved) | `414b82d1` |
| T3b | `test_install_auth_gated_write.py`: fixture moved to the new bootstrap default (found by the full suite) | S5 | inline | done (RED: 1 failed -> GREEN: 1 passed) | `4fad597e` |

Risk lines: T1-T4 `Risk: item 3` (the data-root default is a documented layout contract consumed by installer, launcher, backend and docs; the existing behavioral pin is rewritten in the same unit) plus `item 6` on T1/T3, whose only regression net is the tests this unit ships. T5 `Risk: item 3` (contract document, no code).

## Log

L1 (Owner, verbatim) — "Arrancamos el paso 3 de la separación contenido/estado. Antes de tocar código, listame las unidades de trabajo con su riesgo y decime el alcance."

L2 (Owner, verbatim) — "ok, ahora mismo no existe Demiurgos en mas ninguna maquina sino en la mia propia, asi que si hay que migrar algo solo seria en esta pc"
Decision: no migration unit. The only machine with an install already carries a pointer, and `INSTALL_LAYOUT.md` §2.4 forbids reorienting an existing pointer silently.

L3 (evidence, this machine) — `~/.config/demiurgos/data-root.json` → `{"schema_version": 1, "data_root": "/mnt/3C2A86E52A869C10/proyectos_opencode/demiurgos"}`; `~/.demiurgos` absent; `XDG_DOCUMENTS_DIR="$HOME/Documentos"`, `xdg-user-dir DOCUMENTS` → `/home/miguel-angel/Documentos`. Consequence for S2: hardcoding `~/Documents` would create a second, English folder on a localized desktop.

L4 (evidence) — the bootstrap default is duplicated in six code sites: `scripts/start-demiurgos.sh:122`, `scripts/install-demiurgos.sh:436`, `start-demiurgos.ps1:103`, `start-api.ps1:56`, `start-gateway.ps1:67`, `scripts/install-demiurgos.ps1:461`. Decision: keep the resolver inline in each script (the `Resolve-DataRoot` precedent) instead of adding a shared `scripts/lib` helper, which would enter the runtime payload and force a `payload_manifest.json` regeneration plus a payload-audit change for a 12-line function.

L5 (T1/T2, launchers) — `documents_dir()` (POSIX, pure shell: parses `XDG_DOCUMENTS_DIR` out of `user-dirs.dirs`, expands `$HOME`, falls back to `$HOME/Documents`) and `Get-DocumentsDir` (PowerShell: `[Environment]::GetFolderPath('MyDocuments')`, falls back to `%USERPROFILE%\Documents`). Both replace `<install_root>/data` with `<documents>/Demiurgos` in the bootstrap-once branch only. Verification: the launcher cells run the REAL script through a sourcing probe with a hermetic `HOME`/`XDG_CONFIG_HOME` — they prove the localized folder wins, no English folder is created next to it, the pointer is written at the byte-compatible location, and an existing pointer is preserved byte-identical. The PowerShell cells are static text pins (no PowerShell on this Linux host): residual gap recorded, not hidden.

L6 (T3, POSIX installer) — same resolver inline; the behavioral cell runs the REAL installer in its seed-only/full mode and asserts the pointer, the four seeded folders and the `.env` under `<home>/Documentos/Demiurgos`, and that `<install_root>/data` is never created. Full `test_installer_contract.py`: 106 passed, 5 skipped.

L7 (T5, docs) — `CONTENT_AND_STATE.md` default table + the Windows note scoped to pre-step-3 pointers; `INSTALL_LAYOUT.md` §1 row and §2.4 rule, including why the folder is not hardcoded.

L8 (T3b, uncovered by the full suite) — `test_install_auth_gated_write.py` modelled `<install_root>/data` as the seeded root and failed after the change. The fixture moved to `<home>/Documents/Demiurgos`; the guarded contract (a fresh install never boots into a 401 for gated writes) is unchanged. No other test pinned the old default (grep for `install/data` in the suite: no hits).

L9 (closure) — Full suite from `src/tools/demiurgos-suite/wiki` with the repo `.venv`: **4384 passed, 24 skipped** (2b baseline 4375/24; +9 cells). `payload_audit.sh`: 832 deny findings / 0 content-scan hits, all pre-existing — no payload file was added, so `payload_manifest.json` is unchanged. `git status` clean except this document.

Risk: item 3 (the data-root default is a documented, shared layout contract — installer, launcher, backend and docs all consume it) and item 6 on T1/T3 (their tests are the only regression net). No data was moved, copied or deleted; every pre-existing pointer stays byte-identical, so item 1 does not apply.

L10 (T6, guard decided by the Owner after the review) — the guard lives in `backup/state.py` as a pure pair check (`assert_destination_outside_content_root`), called from `write_destination` (so no caller can persist an overlapping pair) and again from `run_backup` before any probe or write (so a record written earlier, or hand-edited, still cannot publish). The router maps `BackupStateError` to a 400 with the reason instead of a 500. Empirical evidence that motivated it, from a probe over the real inventory: a content root holding the destination layout reports `INCLUDED: ['meta', 'meta/manifest.json', ..., 'snapshots', 'snapshots/<id>/mundos/viejo.md']` with `EXCLUDED: []`. Test blast radius: six cells in `test_backup_router.py` modelled the destination inside the content root (`root / "chosen"`); they now use a sibling, which is what the contract requires. `Risk: item 3` (a new refusal on a public API payload, and a new refusal on the run path) + `item 6` (the tests are the only net).

L11 (closure) — Full suite: **4395 passed, 24 skipped** (4384 before the guard, +11 cells). `Risk: item 3 + item 6` for T6, recorded in L10. Nothing on the Owner's machine changed: his pointer still resolves the content root to the checkout and his `config/backup.json` destination (`~/Documentos/Demiurgos`) stays accepted, because the two paths are siblings — the guard only fires when they overlap.
