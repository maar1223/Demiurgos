# MVP readiness audit — wave 0 (AUD-01, AUD-02, AUD-03)

Branch: `fix/mvp-audit-wave-0` · Base: `master` (`4ace3ce`) · Tests: `.venv/bin/python -m pytest src/tools/demiurgos-suite/wiki/tests/ -q`, `cd frontend && npx vitest run` · Delivery: work-unit commits on the feature branch; push/PR are the Owner's decision. Forecast: ~200 authored lines.

## Specs

S1 — AUD-01 fix, quoted verbatim from `docs/MVP_READINESS_AUDIT.md`: "regenerar el manifiesto y agregar un gate de frescura en CI que falle cuando el manifiesto difiera de la salida del derivador."

S2 — AUD-01 acceptance, quoted verbatim: "`test_payload_boot.py` verde; gate de frescura verde en PR; paquete de release bootea `/health` y `/` en las cuatro celdas."
Acceptance in this environment: `test_payload_boot.py` green; the freshness command green on the current tree and red on a deliberately stale manifest; the four backend cells, `Installer smoke` and `PowerShell 5.1 contract` green in CI after push (the release-package boot is AUD-16, P2, out of wave 0).

S3 — AUD-02 acceptance, quoted verbatim: "CI verde en `master` y en PR; un fallo de frontend no saltea el backend; `test_payload_boot` corre siempre."
Acceptance: the backend/launcher/static-serving/ps51 jobs take the built dist from a build job that does not itself run the frontend tests, so a frontend test failure no longer skips the backend.

S4 — AUD-03 fix, quoted verbatim: "elegir un único layout y alinear paquete, launcher, backend, docs y tests".

S5 — AUD-03 acceptance, quoted verbatim: "instalación Windows real arranca con el comando impreso; `/api/system` reinicia; el rollback encuentra la versión previa."
Acceptance in this environment: the packaged tree places the Windows launcher at `<current>\scripts\start-demiurgos.ps1`, matching `docs/architecture/INSTALL_LAYOUT.md` and every consumer; a drift guard fails if the packaging stops placing it there; the Windows fixture cells in `test_installer_contract.py` stay green. A real Windows install is not reachable here.

S6 — Existing behaviour that shares the changed code must not regress. Acceptance: the POSIX fixture install+boot cell stays green; the full frontend suite stays at 1734 passed; `payload_audit` parity cells unchanged.

## Tasks

| ID | Task | Specs | Route | Status | Commit |
|---|---|---|---|---|---|
| T1 | Regenerate `payload_manifest.json`; add `--check` freshness mode to the derivator | S1, S2 | inline | done (RED: `test_payload_boot` 4 errors -> GREEN: 4 passed) | `097201c` |
| T2 | Add the manifest-freshness CI job + its tests | S1, S2 | inline | done (RED: `--check` failed on a trimmed manifest -> GREEN: 4 passed) | `097201c` |
| T3 | Decouple backend/launcher/static-serving/ps51 from the frontend test result | S3 | inline | done (no unit test: workflow topology; YAML parsed) | `097201c` |
| T4 | Package the Windows launcher at `scripts/start-demiurgos.ps1`; fix the printed path and the shortcut preference | S4, S5 | inline | done (GREEN: installer contract 119 passed, 5 skipped) | `30ca73d` |
| T5 | Add the packaging-layout drift guard test | S4, S5 | inline | done (RED: 4 violations on the old workflow -> GREEN: 4 passed) | `30ca73d` |
| T6 | Verification: targeted backend suites, POSIX installer contract, frontend suite, manifest check | S2, S6 | inline | done (4600 passed, 8 skipped; launchers 49 passed; frontend 1734 passed) | — |

## Log

L1 (Owner request, verbatim): "sigamos desde checkpoint con los que tenemos pendiente de la auditoria"

L2 (evidence) — CI run `41494138986` on `4ace3ce`: failures are `Backend wheels-only` (all four cells), `Installer smoke (file:// fixture)` and `PowerShell 5.1 contract (windows)`. All three trace to AUD-01: the fixture payload is built from `payload_manifest.json`, which omits the four `conflict_*.py` modules that `api_server.py:69` imports at top level. `Frontend (windows-latest)` is now green, so the AUD-02 test-isolation half is already resolved; only the `needs: frontend` coupling remains.

L3 (evidence) — locally, after `python scripts/derive_payload_manifest.py`: `test_payload_boot.py` goes from 4 errors to 4 passed, and `test_installer_contract.py -k test_install_then_boot_serves_health_and_root` passes. The derived manifest adds exactly the four conflict modules and bumps `source_commit`.

L4 (decision) — the derivator embeds `source_commit` = current `HEAD`, so a naive `git diff --exit-code` gate can never pass after the manifest is committed (a commit cannot contain its own sha). The freshness check therefore compares every field except `source_commit`.

L5 (decision) — AUD-03 is fixed at packaging time: the repo keeps `start-demiurgos.ps1` at the root for the dev checkout (the launcher already derives `APP_ROOT` from both locations), and the release stage places it at `scripts/start-demiurgos.ps1`, which is the frozen contract path every consumer already uses. This is the smallest change that makes the installed layout single and correct.

L6 (scope) — AUD-04 needs an Owner product decision (provision Hermes in the default install vs an honest opt-in) and is not part of wave 0.

L7 (verification) — after the changes: `test_payload_boot.py` 4 passed; `test_payload_manifest_freshness.py` 4 passed; `test_release_payload_layout.py` 4 passed; `test_installer_contract.py` 119 passed, 5 skipped (Windows cells skipped on Linux); the CI-equivalent backend command 4600 passed, 8 skipped, 40 deselected; launcher suites 49 passed, 4 skipped; frontend 138 files / 1734 tests passed (unchanged, no frontend code touched). Both workflows parse as YAML.

L8 (regression caught by verification) — the first edit to `scripts/lib/desktop-shortcut.ps1` used a `§` character and failed `test_windows_desktop_shortcut.py::test_helper_is_ascii_only`; the shipped `.ps1` files are ASCII-only because Windows PowerShell 5.1 mis-decodes BOM-less UTF-8. Fixed and the suite went green.

L9 (pending) — AUD-01/02 acceptance still needs a green CI run after the push (`master` or a PR); AUD-03's real-Windows acceptance needs a Windows install, and the packaged-payload Windows boot is AUD-16 (P2).
