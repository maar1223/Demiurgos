# System restart dispatches the running app root, not `current`

Objective: after an update flips `~/.demiurgos/current`, an in-app restart must bring up the installed version. Today `/api/system/restart` re-runs the launcher of the app that is currently executing, so it restarts the previous version.
Status: backlog. Not implemented.
Runners: `.venv/bin/python -m pytest src/tools/demiurgos-suite/wiki/tests/ -q`; `cd frontend && npx vitest run`; `cd frontend && npm run typecheck`.

## Specs

- **S1 (root cause).** `_system_launcher_path()` returns `_CODE_ROOT / "scripts" / "start-demiurgos.sh"`. `_CODE_ROOT` is the running app's directory (`app/0.4.0`), so after the updater installs `0.4.2` and flips `current`, the restart endpoint dispatches the **0.4.0** launcher, which derives its own root from its path and restarts 0.4.0. The user sees `POST /api/system/restart 200` and the same old version.
  Acceptance: an in-app restart after an update starts the version `current` points at, verified by `/api/config` `app_version` and the API process cwd.
- **S2 (resolution).** When an installed layout is detected (`installed root/current` exists), the restart launcher is `installed_root/current/scripts/start-demiurgos.{sh,ps1}`, resolved at **dispatch time** (not boot) so an update that happens while the process is running is honored. A dev checkout with no `current` keeps `_CODE_ROOT`.
  Acceptance: boot-time and post-update restarts both resolve the same installed version; the dev checkout path is unchanged.
- **S3 (updater installer parity).** The same rule applies to `_UPDATE_INSTALLER`: after an update flips `current`, the next apply must execute the newly installed installer. If the installer path is cached at boot, document why the first apply after an update may use the previous installer.
- **S4 (evidence).** RED before each behavior rule; a router test for both resolutions; one live probe: install a newer version, call restart, confirm the cwd and `/api/config`.

## Tasks

- [x] T1 resolve the system launcher through `current` at dispatch time (S1, S2). Evidence: `create_system_control_router` accepts a callable `launcher_path` and resolves it in `_dispatch`; `api_server._install_root()` recognizes `current`, `DEMIURGOS_ROOT=.../current` and `.../app/<version>`; `_system_launcher_path` uses `<install_root>/current` at call time. Tests: `test_system_control.py::test_restart_resolves_a_callable_launcher_at_dispatch`, `test_system_launcher_resolution.py` 4 passed.
- [x] T2 document the updater installer boot cache (S3). The installer is resolved at boot from `_CODE_ROOT`; that is safe after 0.4.2 because the running updater dispatches its own installer (which supports the restart flag), and a failed restart now falls back to `current` through T1. The first update from 0.4.0 used the old installer by design.
- [x] T3 tests + full verification (S4). Evidence: focused 17 passed; full backend suite green at closure; live probe at the next release (0.4.2 → 0.4.3) validates cwd + `/api/config`.

## Log

- **L1 (Owner report, verbatim):** "volvio a pasar lo mismo, decia instalar y reinicar pero no se está reiniciando nada. Y reinicio desde el perfil y tampoco hace nada"
- **L2 (evidence, 2026-11-08):** after the in-app apply installed 0.4.2 (`~/.demiurgos/app/0.4.2`, `current -> app/0.4.2`), the running API process was still `app/0.4.0` and `/api/config` reported `0.4.0`. The API log showed `POST /api/update/apply 200` and `POST /api/system/restart 200`. A manual `~/.demiurgos/current/scripts/start-demiurgos.sh restart` fixed it: the new process ran from `app/0.4.2` and `/api/config` reported `0.4.2`.
- **L3 (code evidence):** `api_server._system_launcher_path()` uses `_CODE_ROOT`, the running app root, not `_install_root()/current`; the updater's `_UPDATE_INSTALLER` is resolved the same way at boot.
- **L4 (context):** the 0.4.0 updater could not auto-restart the first apply (the restart flag only exists in 0.4.2), which is expected. The separate defect here is the manual restart path; the next update should auto-restart, but a failed auto-restart would still fall back to the old root.
- **L5 (implementation evidence, 2026-11-08):** `system_control._dispatch` resolves a callable launcher; `api_server._install_root` covers the three installed shapes; `_system_launcher_path` returns `<install_root>/current/scripts/start-demiurgos.*` at dispatch time. Focused 17 passed. This ships as 0.4.3; the live probe is the 0.4.2 → 0.4.3 update.
