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
- [ ] **WU-1** `scripts/start-demiurgos.sh`: add a sourcing guard so `main` runs only when executed (`BASH_SOURCE[0]` == `$0`), not when sourced (the hermetic layout probe). Fixes A.
- [ ] **WU-2a** `test_installer_contract.py`: add `POSIX_RUNNER = skipif(os.name == "nt")` and decorate the POSIX installer classes that shell out to `bash`. Fixes B1.
- [ ] **WU-2b** `test_installer_contract.py`: carry Windows-essential env vars (`SystemRoot`, `windir`, `PATHEXT`, `ComSpec`, `TEMP`, `TMP`) into the PS subprocess env helpers. Fixes B2.
- [ ] **WU-3** `test_import_router.py`: mock the `.docx` conversion in `TestCancelDuringAnalyze` (use `_docx_seams`) so the test is converter-independent. Fixes C.
- [ ] **WU-A2**: reproduce/instrument the macOS boot-smoke port leak in CI; fix or file with evidence.

## Acceptance criteria
- All 7 previously-red jobs reach GREEN on the PR (all 4 backend, both launchers, ps51).
- No previously-green job regresses.
- POSIX installer cells still RUN and pass on Linux/macOS (gate only skips Windows).

## Checks
- Launcher probe (all bash versions): `bash -c 'source "$1" __probe__ || true; printf %s "${APP_ROOT:-UNSET}|${PYTHON_BIN:-UNSET}"' bash scripts/start-demiurgos.sh` → rc=0 + paths.
- `pytest tests/ -k "TestCancelDuringAnalyze"` with `markitdown` blocked (repro) → passes.
- `pytest test_installer_contract.py` on Linux → POSIX cells run/pass.
- CI: `.github/workflows/ci.yml` via a PR.

## Progress
- Diagnosed all four root causes with job-log evidence + local reproduction.
