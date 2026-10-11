# ODD — Remaining pre-existing CI debt (post PR #182)

**Branch**: `fix/ci-debt-remaining` · **Base**: `master` `6e4d342`
**Route**: direct inline (already-understood mechanical edits after full diagnosis)
**RDD**: off (user-owned switch disabled) — ordinary functional checks only

## Objective
Turn the remaining RED GitHub Actions jobs on `master` GREEN without weakening any
contract, after #182 fixed the rest of the pre-existing CI debt.

## Problem / evidence
`master` run `38014846533` still fails 7 jobs, from 4 root causes (verified from job
logs + local reproduction):

| ID | Jobs | Root cause |
|----|------|-----------|
| A  | Launcher (macos-14, windows-latest) | Sourcing probe `bash -c 'source launcher __probe__'`: `main` runs on source; `set -euo pipefail` aborts the `bash -c` before the probe's `printf` on bash 3.2 (macOS) / git-bash (Win). rc=2/1, stdout empty. |
| B1 | PowerShell 5.1 contract (windows) | `test_installer_contract.py` POSIX classes run on Windows; `subprocess(["bash", ...])` resolves to `C:\Windows\System32\bash.exe` (WSL, no distro) → UTF-16 error → 16 failures. |
| B2 | PowerShell 5.1 contract (windows) | The 5 Windows PS cells fail because the PS subprocess env dict omits `SystemRoot`/Windows-essential vars → `powershell.exe` 5.1 prints "Loading managed Windows PowerShell failed with error 8009001d". |
| C  | Backend wheels-only (×4) | `TestCancelDuringAnalyze` uses a `.docx` source without mocking conversion; CI backend installs only the mandatory closure (no `markitdown`) → `conversion_unavailable` → `analyze` fails at the conversion gate (import_router.py:551-578) before reaching the enricher. Reproduced locally by blocking `markitdown`. |
| A2 | Launcher (macos-14) | `test_launcher_boot_smoke` macOS: `stop` returns 0 but port stays listening (leaked launcher process). **Unresolved** — needs CI-side instrumentation. |

## Scope (authorized)
Fix A, B1, B2, C in the source + test files. Diagnose A2 via CI. No product behavior
change; test/CI-contract repairs only (plus the launcher sourcing guard).

## Out of scope
- Enabling/adjusting Actions billing or budgets.
- Any change to the narrowed support matrix (#3579) or delivery gates.

## Tasks
- [x] **WU-1** `scripts/start-demiurgos.sh`: sourcing guard (`BASH_SOURCE[0]` == `$0`). Fixes A (macOS). + gate the POSIX sourcing probes to POSIX for the Windows cell (N3).
- [x] **WU-2a** `test_installer_contract.py`: `POSIX_RUNNER` (skipif nt) on the 9 POSIX cells. Fixes B1.
- [x] **WU-2b** `test_installer_contract.py`: carry Windows-essential env vars into the PS subprocess env. Fixes B2 (the 8009001d error).
- [x] **WU-3** `test_import_router.py`: mock the `.docx` conversion in `TestCancelDuringAnalyze`. Fixes C.
- [x] **WU-4** `test_installer_contract.py`: fixture stub uv published for the HOST target (was hardcoded x86_64-linux). Fixes aarch64/macOS installer cells.
- [x] **WU-5** `ci.yml` backend job: provision the no-op browser stubs up-front. Fixes the launcher-cell guard failures.
- [x] **WU-6** `test_backup_inventory.py` / `test_backup_name_safety.py`: skip case/NFC-collision cells on case-folding/normalizing filesystems (macOS).
- [x] **WU-7** `hermes_probe_support.py`: separator-portable layout self-check (`as_posix()`). Fixes the Windows backend collection errors.
- [x] **WU-8** `install-demiurgos.ps1`: nested `Join-Path` (PS 5.1 has no 3-arg `Join-Path`). Fixes the `uv.ps1` binding error.
- [x] **WU-9** `ci.yml` backend job: scope it to the backend suite (ignore the launcher/installer contract files, which run in their dedicated jobs). Fixes the macOS/Windows backend cross-platform red + the Windows hang.
- [x] **WU-10** `start-demiurgos.sh`: robust `command_of_pid` on macOS + cmdline in the skip diagnostic. macOS boot-smoke leak.
- [~] **WU-11** Windows PS launcher boot: `_boot_ps_launcher` now dumps the `demiurgos-api.err.log` on failure (diagnostic). The 3 ps51 cells still fail booting the installed app — needs the err-log evidence from a Windows run to fix.
- [x] **WU-12** Windows backend: gate the 9 platform-specific files to the OS/capability that can run them (payload_audit 44, hermes_probe_support 13, sync_folder FUSE 3, data_root XDG 4, launcher_boot_rollback 4, launcher_hermes_home 3, installer_hermes_isolation 1, install_auth_gated_write 1, hermes_profile_config 1). Local: 3793 passed, no regressions.

## BLOCKER — GitHub Actions billing
Since `33c7395` GitHub Actions refuses to start jobs:
`The job was not started because recent account payments have failed or your spending limit needs to be increased.`
So WU-11/WU-12 cannot be validated on CI until the account's billing is resolved. The last VALID run was `38021719503` (12/14 jobs green; PS51 + backend Windows red).


## Progress (CI evidence)
- Baseline `master`: 7 red jobs. After WU-1..WU-10:
  - GREEN: Frontend ×3, Installer musl, Installer smoke, Static serving, Launcher (ubuntu + windows), Backend (x86_64 + aarch64 + macos-arm64).
  - PS51: 21 → 3 failed. Launcher macOS: 3 → 1 (ownership fixed pending re-run). Backend Windows: was a collection error (masked failures) → now 74 surfaced.
- Local: probe rc=0; `TestCancelDuringAnalyze` passes with markitdown blocked; installer-contract 103 passed/5 skipped; launcher portable+root 38; backup 49.


## Checks
- Launcher probe (all bash versions): `bash -c 'source "$1" __probe__ || true; printf %s "${APP_ROOT:-UNSET}|${PYTHON_BIN:-UNSET}"' bash scripts/start-demiurgos.sh` → rc=0 + paths.
- `pytest tests/ -k "TestCancelDuringAnalyze"` with `markitdown` blocked (repro) → passes.
- `pytest test_installer_contract.py` on Linux → POSIX cells run/pass.
- CI: `.github/workflows/ci.yml` via a PR.
