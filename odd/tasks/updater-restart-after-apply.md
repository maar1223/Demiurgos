# Updater apply must restart the stack after install

Objective: when the in-app updater applies a version, the running stack ends on the installed version without a manual restart. Today the installer only installs and flips `current`; the old API keeps serving, so the UI reloads the old version and tells the user to restart.
Status: backlog for the next release batch. Not implemented.
Runners: `.venv/bin/python -m pytest src/tools/demiurgos-suite/wiki/tests/ -q`; `cd frontend && npx vitest run`; `cd frontend && npm run typecheck`.

## Specs

- **S1 (root cause).** `POST /api/update/apply` spawns the installer detached and returns 200; `install-demiurgos.sh` installs and flips `current`, then prints "Start Demiurgos with: … start". It never restarts the API or the gateway. The API process keeps serving the previous version from its already-loaded code. The frontend labels the action "Instalar y reiniciar" and its comments assume "the installer restarts the whole stack".
  Acceptance: an updater-driven apply ends with the API and gateway running the installed version, verified by `/api/config` returning the new `app_version`, with no manual restart.
- **S2 (restart trigger).** The restart is opt-in for updater-driven installs only: `apply_update` sets `DEMIURGOS_RESTART_AFTER_INSTALL=1` in the installer environment; `install-demiurgos.sh` runs `current/scripts/start-demiurgos.sh restart` as its last step only when that flag is set. A fresh or manual install keeps today's byte-identical behavior (prints the start hint).
  Acceptance: the flag is set only by the update router; the installer without the flag never starts or stops services; the restart happens after a successful install and never after a failure.
- **S3 (UI truthfulness).** After the apply, the UI confirms the served version (`/api/config` `app_version`) before reloading. If the backend never went down or still serves the old version past a bounded window, it shows "instalado; reiniciá para aplicar" instead of the generic "el servidor tardó demasiado".
  Acceptance: no false "updated" reload on the old process; the explicit restart state is reachable and test-covered.
- **S4 (Windows parity).** `install-demiurgos.ps1` honors the same flag and restarts through the PowerShell launcher.
- **S5 (evidence).** RED before each behavior rule; backend installer/router tests; frontend `UpdateSection` tests; one live probe on Linux: apply from 0.4.0 to the next candidate and confirm `/api/config` reports the new version without manual intervention.

## Tasks

- [ ] T1 `install-demiurgos.sh` + `apply_update` env flag + tests (S1, S2).
- [ ] T2 `install-demiurgos.ps1` parity (S4).
- [ ] T3 `UpdateSection` version confirmation + copy + tests (S3).
- [ ] T4 full verification and live apply probe (S5).

## Log

- **L1 (Owner request, verbatim):** "si, lo anotas para el proximo lote" — about deferring the updater restart fix.
- **L2 (diagnosis evidence, 2026-11-07):** installing v0.4.0 from the UI produced `~/.demiurgos/app/0.4.0`, `current -> app/0.4.0` and `install-demiurgos: installed 0.4.0 at …/current`, but the API process still ran from `app/0.3.1` (`/proc/<pid>/cwd`) and `/api/config` reported `0.3.1`. The installer log ends with `Start Demiurgos with: … start-demiurgos.sh start`. The UI showed the restart notice; a manual `start-demiurgos.sh restart` fixed it and `/api/config` then reported `0.4.0`.
- **L3 (code evidence):** `updater.py` docstring says the frontend expects "the installer restarts the stack"; `frontend/src/api/updates.ts` repeats it; `UpdateSection.tsx` polls `getAuthStatus` (which returns 200 with `authenticated: false`) and reloads without checking the version; `install-demiurgos.sh` has no restart call and ends with the start hint.
