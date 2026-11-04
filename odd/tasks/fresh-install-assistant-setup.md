# Feature: fresh-install-assistant-setup

Branch: `master` (local integration) | Delivery: local merge, **no PR** (the Owner is the sole programmer) | Backend tests: `.venv/bin/python -m pytest src/tools/demiurgos-suite/wiki/tests/ -q` | Frontend tests: `cd frontend && npm test -- --run`

Objective: a fresh Demiurgos install can configure the Hermes assistant from the UI and the gateway API server authenticates, without any manual `config.yaml` / `.env` edit. The Owner's last checkpoint (`nec/checkpoint`, session 2026-11-04) leaves this as the next work item.

## Specs

S1. **A missing `config.yaml` is a valid empty state, not an error.**
`GET /api/profile/assistant` on an active Hermes profile without `config.yaml` returns **200** with the "needs configuration" status instead of 503. The response keeps every field the panel needs: `provider`, `base_url`, `model`, `model_metadata` (empty id), `key_configured: false`, `revision: 0`, `models` (server catalog), `active_profile`, `runtime_state`, and `gateway_running` when the host wires liveness. Owner's checkpoint: "`GET` debe devolver estado "necesita configuración" (200) sin `config.yaml`".

S2. **A missing `config.yaml` is created by the save paths.**
`PUT /api/profile/assistant` and `PUT /api/profile/assistant/configuration` create the profile's `config.yaml` (and the parent directory) when missing, instead of failing with 503. Owner's checkpoint: "`PUT`/`/configuration` debe crear la config si falta (hoy `_read_config` corta con 503)."

S3. **A truly unresolvable profile still fails closed.**
When the active profile cannot be resolved at all (no `HERMES_HOME`, no `HOME`/`LOCALAPPDATA`), the routes keep answering **503** with the resolution error. Creating a missing directory under a resolved root is allowed; inventing a root is not. Every configured-profile behavior is unchanged.

S4. **The launcher bridges the gateway key.**
`scripts/start-demiurgos.sh` exports the data-root `HERMES_GATEWAY_KEY` to both children and exposes `API_SERVER_ENABLED=true` plus `API_SERVER_KEY=<same key>` to the gateway, so the gateway's API server authenticates the Demiurgos client. Owner's checkpoint: "`scripts/start-demiurgos.sh`: puentear `API_SERVER_KEY` desde `HERMES_GATEWAY_KEY` del data root (exportar al gateway o escribir el `.env` del perfil) para que el API server autentique."

S5. **A fresh install has a gateway key.**
Fresh installs seed `$DATA_ROOT/.env` without `HERMES_GATEWAY_KEY` (assumption verified in `scripts/install-demiurgos.sh:seed_env_file`). On boot the launcher generates a cryptographically random key (>= 16 chars, the Hermes `has_usable_secret(min_length=16)` guard) and persists `HERMES_GATEWAY_KEY=<key>` in `$DATA_ROOT/.env` exactly once, preserving every other line. An existing usable key (`>= 16`) is never replaced; a present-but-unusable key is regenerated (the runtime refuses it). Because the gateway loads `$HERMES_HOME/.env` with `override=True`, the launcher also reconciles `API_SERVER_ENABLED=true` and `API_SERVER_KEY=<key>` in the product profile's `.env`, and reports a clear warning if that reconcile fails. The data-root/env files are not rewritten when the values already match.

S6. **The provisioner seeds the dedicated profile.**
`scripts/provision-hermes.sh` writes a minimal `$HERMES_HOME/config.yaml` (`model: {}`) and `$HERMES_HOME/.env` with `API_SERVER_ENABLED=true` when they are missing — including when `is_provisioned` skips `run_setup`. Existing files and lines are preserved (a last line without a trailing newline is terminated before appending); re-running is a no-op. Owner's checkpoint: "`scripts/provision-hermes.sh`: sembrar `config.yaml` mínimo (`model: {}`) y `.env` con `API_SERVER_ENABLED=true` si faltan, incluso cuando `is_provisioned` salta `run_setup`."

S7. **Windows parity.**
`scripts/provision-hermes.ps1`, `start-gateway.ps1` and `start-demiurgos.ps1` implement the same seed/bridge/generate behavior with PowerShell 5.1-compatible, ASCII-only code. `start-gateway.ps1` works standalone (it loads the data-root `.env` itself); `start-demiurgos.ps1` exports `HERMES_GATEWAY_KEY` to the API child.

S8. **The UI renders the configuration wizard from the empty status.**
With the 200 empty status, `AssistantSettingsPanel` renders the connection step (no error card), and the endpoint field defaults to the selected provider's known URL. No credential is displayed. Owner's checkpoint: "Ajustar frontend `AssistantSettingsPanel`/tipos para renderizar el formulario en ese estado."

S9. **Fresh-install proof.**
A hermetic test with a temporary `HOME` that has **no** `~/.hermes` covers: provisioning seeds `config.yaml`/`.env`; `GET` returns 200 for the unconfigured profile; a save creates the config; the gateway receives `API_SERVER_KEY`/`API_SERVER_ENABLED`; and a second provision/build leaves bytes unchanged. Owner's checkpoint: "Tests: instalación hermética con `HOME` temporal SIN `~/.hermes` → instalar, panel guarda config, gateway API server conectado; tests backend de GET/PUT sin config; test del puente de clave; test del seed del instalador."

## Tasks

- T1 — S1: tolerate a missing `config.yaml` on `GET` (empty status, catalog, revision 0). Route: inline. Status: **done** (RED→GREEN: `TestConfiglessProfile`).
- T2 — S2/S3: create the config on `PUT` and `/configuration`; keep the unresolvable-profile 503; `_atomic_write` creates the profile directory. Route: inline. Status: **done** (`TestConfiglessProfile` + updated `test_unresolvable_profile_fails_closed`).
- T3 — S4/S5: POSIX launcher key ensure + bridge (data-root `.env`, product profile `.env`, gateway/API env). Route: inline. Status: **done** (`test_launcher_gateway_key.py`, 8 passed).
- T4 — S7: Windows launcher parity (`start-gateway.ps1`, `start-demiurgos.ps1`). Route: inline. Status: **done** (text + ASCII contract; pwsh unavailable on this host, so no execution).
- T5 — S6/S7: provisioner seed (POSIX + PS1), including the `is_provisioned` fast path. Route: inline. Status: **done** (`test_provision_hermes.py`, 15 passed).
- T6 — S8: frontend empty-status rendering + default endpoint. Route: inline. Status: **done** (`AssistantSettingsPanel` + test).
- T7 — S9: backend, launcher, provisioner and frontend tests; run the complete suites. Route: inline. Status: **done** (evidence in L6).
- T8 — review corrections (S2/S5/S6): fix the verifier blocker and advisories. Route: inline. Status: **done** (evidence in L7).

## Log

L1 (Owner, 2026-11-04): "continua desde checkpoint"

L2 (checkpoint `nec/checkpoint`, 2026-11-04 12:30): "## Plan para la próxima sesión ... 2. Feature nueva `odd/tasks/fresh-install-assistant-setup.md` (crear doc antes del primer write): `scripts/provision-hermes.sh`: sembrar `config.yaml` mínimo (`model: {}`) y `.env` con `API_SERVER_ENABLED=true` si faltan, incluso cuando `is_provisioned` salta `run_setup`. `scripts/start-demiurgos.sh`: puentear `API_SERVER_KEY` desde `HERMES_GATEWAY_KEY` del data root (exportar al gateway o escribir el `.env` del perfil) para que el API server autentique. `assistant_settings.py`: `GET` debe devolver estado "necesita configuración" (200) sin `config.yaml`, y `PUT`/`/configuration` debe crear la config si falta (hoy `_read_config` corta con 503). Ajustar frontend `AssistantSettingsPanel`/tipos para renderizar el formulario en ese estado. Tests: instalación hermética con `HOME` temporal SIN `~/.hermes` → instalar, panel guarda config, gateway API server conectado; tests backend de GET/PUT sin config; test del puente de clave; test del seed del instalador."

L3 (evidence, exploration): `scripts/install-demiurgos.sh:seed_env_file` seeds only `DEMIURGOS_AUTH_MODE`, `DEMIURGOS_LANGUAGE`, `DEMIURGOS_BUGREPORT_*`, `DEMIURGOS_WORLD`; no `HERMES_GATEWAY_KEY`. The pinned Hermes runtime enables `api_server` only when `API_SERVER_KEY` passes `has_usable_secret(min_length=16)` and loads `$HERMES_HOME/.env` with `override=True` (verified in `~/.demiurgos/hermes-agent/gateway/config_env.py` and `hermes_cli/env_loader.py`). Therefore the launcher must both generate the key and reconcile it in the profile `.env`; exporting alone would be overridden by a stale profile line.

L4 (evidence, exploration): `assistant_settings._read_config` raises when `config.yaml` is absent and is called by `GET`, `PUT`, `/configuration`, `/configuration/key` and `current_config_revision`. `_atomic_write` refuses a missing parent directory. The panel already tolerates an empty `model_metadata` id (`modelDone` requires a real id) and starts at the connection step when the status has no model.

L5 (RED→GREEN, backend): `TestConfiglessProfile` failed 5/5 before the change (`503` on GET/PUT/save/delete and on a resolved-but-missing root) and passes after allowing a missing config, creating the profile directory on write, and keeping the unresolvable-root 503.

L6 (full verification, 2026-11-04): backend `src/tools/demiurgos-suite/wiki/tests/` → **4915 passed, 21 skipped, 1 failed**; the only failure is `test_semantic_e2e.py::TestLiveHermesFirstE2E::test_live_guided_start_semantic_first` (`IndexError: order[0]`), which reproduces unchanged on a clean `origin/master` worktree against the same live gateway and is unrelated to this feature. Frontend: `npm run typecheck` clean; `npm test -- --run` → **1735 passed** (138 files). `bash -n` on both modified shell scripts and `py_compile` on `assistant_settings.py` are clean. Targeted suites: assistant settings 25, launcher gateway key 8, provisioner 15, fresh-install E2E 1, launcher/portable 153.

L7 (independent verification, 2026-11-04): `gentle-ai-verify` reviewed `2e43868..HEAD` in a scratch copy. Verdict: S1-S5, S7 (static), S8, S9 PASS; S6 FAIL (blocker B1: appending to a `.env` without a trailing newline concatenated `X=1API_SERVER_ENABLED=true`). Advisories: A1 CRLF quoted-key strip order (secret mangled), A2 a failed save on a fresh profile left a 0-byte `config.yaml`, A3 suppressed bridge errors, A4 an existing short key left the API server disabled, A5 config-as-directory (pre-existing read semantics, accepted). Correction batch: newline guard in `seed_profile`; CR-before-quotes strip; `_restore_config` removes a config the failed save created; bridge failures now warn; keys shorter than 16 regenerate (POSIX + PS1); regression tests added for B1, A1, A2 and A4. Targeted suite: **104 passed**. Native RDD review is unavailable on this repo's FUSE/ntfs-3g mount (`review mode status` → unavailable; RAR refuses a fixed-owner filesystem), so the independent verifier is the review evidence.

L8 (bounded recheck, 2026-11-04): the same verifier rechecked only B1/A1/A2/A4 on correction commit `2863478` in a fresh scratch copy → **all PASS**, no regression in the touched success paths (normal save, existing-config rollback, long-key preservation, quoted/plain LF+CRLF parsing). Focused suites: **104 passed**; `bash -n` clean; the three `.ps1` files still decode as ASCII. Full backend suite after the corrections: **4919 passed, 21 skipped, 1 failed** — the same pre-existing live-gateway `test_live_guided_start_semantic_first` reproduced on `origin/master`. Ready for the Owner's push/PR/release decision; nothing was pushed or published.

L9 (Owner preference, 2026-11-04): "ok pero recordamos que no estamos haciendo PR porque el programador soy yo y solo yo". Standing delivery rule: integrate on `master` locally, no pull requests. The six work-unit commits were fast-forwarded into local `master` (no push, no PR); the feature branch was removed.
