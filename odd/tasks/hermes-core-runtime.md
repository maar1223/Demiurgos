# Hermes as the MVP runtime (AUD-04, hardened)

Branch: `feat/hermes-core-runtime` · Base: `master` (`7bd8f26`) · Runtime pin: `d046ff9905b8470c4a0cfd5e9da566986056b438` · Tests: `.venv/bin/python -m pytest src/tools/demiurgos-suite/wiki/tests/ -q`, fork: `pytest tests/gateway/test_api_server.py` · Delivery: work-unit commits on the feature branch; push/PR are the Owner's decision. Forecast: L (multi-session).

## Specs

S1 — Owner decision (verbatim): "hermes es requisito indispensable ... es el corazon de la IA en el sistema. Sin Hermes potenciando Demiurgos por debajo el sistema funciona como al 40% se su capacidad real." The default install therefore provisions the assistant runtime; it is no longer an opt-in CLI stack.

S2 — The runtime is the Demiurgos fork `maar1223/hermes-agent-demiurgos` (MIT, `Copyright (c) 2025 Nous Research`), pinned to a commit. The fork is public (Owner decision, verbatim: "desde que lo converti en un repo publico eso ya no importa"). Never upstream-latest at install time.

S3 — The fork patch Demiurgos depends on is `tool_choice: "none"` support (`no_tools` empty toolset in `gateway/platforms/api_server.py`, route handling in `api_server_openai_routes.py`). The app sends it at `api_server.py:10061` and `idea_materialization_provider.py:201`. The patch must be present in the pinned commit and covered by the fork's own tests.

S4 — The pinned base must support the declared matrix: Linux x86_64/aarch64 glibc, macOS arm64, Windows amd64 native (`setup-hermes.ps1` + `pm/lock.json`). The old commit `5aedb4d4` does not (it predates both), so the pin must move to a rebased commit on a current upstream base.

S5 — The runtime is product-owned and isolated: the checkout lives under the product root, `HERMES_HOME` and `HERMES_RUNTIME_DIR` point there, and the gateway runs the product-owned binary by absolute path. It never uses `command -v hermes` from the user's PATH, and never writes `~/.hermes/config.yaml` or `~/.hermes/profiles`.

S6 — A pre-existing Hermes on the user's machine is detected and reported, never modified. The product runtime is used regardless; using the user's Hermes is an explicit opt-out, never the default.

S7 — Version/commit verification at install and at boot. An incompatible runtime fails closed with expected-vs-found and a remedy, rather than degrading silently.

S8 — MIT compliance: the Hermes `LICENSE` and copyright notice travel with the artifact (third-party notices), and no "Nous Research"/"Hermes" endorsement is implied.

S9 — Existing behaviour that shares the changed code must not regress: the installer contract tests, the launcher suites, readiness, and the gateway-absent boot path stay green (the web app still boots when the assistant is unavailable, but readiness stays honest and `runtime=accepted` requires a real run).

## Tasks

| ID | Task | Specs | Route | Status | Commit |
|---|---|---|---|---|---|
| T1 | Make the fork public and record the license obligation | S2, S8 | inline | done (public confirmed) | — |
| T2 | Port the `tool_choice: none` patch onto current upstream `main`; run the fork tests; pin the new commit | S3, S4 | inline | done — merge `d046ff99` on upstream `6112c2ad`; 367 api_server tests pass | — |
| T3 | POSIX installer: product-owned pinned runtime + verification | S5, S7 | inline | pending | |
| T4 | Windows installer parity (`setup-hermes.ps1`, product env) | S4, S5 | inline | pending | |
| T5 | Isolation: export `HERMES_HOME`, move `demiurgos-mcp` out of `~/.hermes/profiles`, prior-install report | S5, S6 | inline | pending | |
| T6 | Launcher: product binary + `HERMES_AGENT_ROOT` (+ `API_SERVER_PORT`) | S5, S7 | inline | done — see L16 | |
| T7 | Docs/readiness/license notices | S8, S9 | inline | pending | |
| T8 | Verification: installer contract, launcher suites, readiness, fork tests | S9 | inline | pending | |

## Log

L1 (Owner request, verbatim): "ok, lo hacemos publico, y harías tus recomendaciones para que todo funcione bien verda?"

L2 (evidence) — fork `maar1223/hermes-agent-demiurgos` was PRIVATE; made public with explicit Owner consent. It is a git checkout of upstream MIT + one commit `5aedb4d4` ("honor tool_choice none to disable tools per request", 194 lines, 3 files + tests). Upstream does not contain it (API: `No commit found for SHA`).

L3 (evidence) — the pinned commit predates Windows native support: its tree has `setup-hermes.sh` only, no `setup-hermes.ps1`, no `pm/`, no `pm/lock.json`. Current upstream `main` has both. Pinning `5aedb4d4` therefore cannot satisfy S4 on Windows.

L4 (evidence) — the fork diff does not apply to current upstream `main`: `git apply --check` fails at `gateway/platforms/api_server.py:2092`. Upstream still does not honor `tool_choice: none` (only a fingerprint key mentions it), so the patch must be ported, not dropped.

L5 (current machine state) — the installed checkout is the old fork commit at `~/.hermes/hermes-agent` (`v2026.9.7-5-g5aedb4d4`, `pyproject` 0.21.1, Python 3.11.15). `~/.demiurgos/hermes` does not exist, and `~/.hermes/config.yaml` already contains Demiurgos-owned blocks (plugin, TTS provider, graph MCP, env refs). Any new install must leave that personal profile untouched.

L6 (license) — Hermes is MIT (`Copyright (c) 2025 Nous Research`); embedding it in proprietary Demiurgos is allowed with the notice retained. The real redistribution risk is the bundling of Hermes' dependency tree, not the fork itself; a dependency-license audit is required only if a prebuilt bundle is shipped instead of an on-machine install.

L7 (decision) — the pin target must be a rebased fork commit on a current upstream base, because Windows native support and the `pm` installer are required by S4. The exact new commit is chosen after the port and its tests.

L8 (execution) — prior memory (#3093, #3095, #3097) showed the fork was already rebuilt onto upstream v0.21.0 in 2026-09-07 with the `tool_choice` commit `5aedb4d4` and a clean merge base. The update is therefore a **merge**, not a rebuild. Fetching upstream `main` gave `6112c2ad` (2026-11-02); the merge produced exactly one conflict, in `gateway/platforms/api_server.py` (signature types, the interim-assistant gate, and the new `session_authority` delegation). Resolved by taking upstream's types/behaviour and re-applying `no_tools` in `_create_agent` (empty `enabled_toolsets` after the display gate), in the `_run_agent` signature (last parameter), in the `_create_agent` call, and in the `session_authority` delegation. The route and test files auto-merged. Result: merge commit `d046ff9905b8470c4a0cfd5e9da566986056b438` on `main`; first parent is the old pin (`5aedb4d4`), so rollback is reachable.

L9 (verification) — the merged tree was exported to a standalone directory outside `~/.hermes` (the new `tests/home_io_guard.py` refuses I/O against the real home) and tested with the existing venv (`PYTHONPATH` to the standalone tree): `tests/gateway/test_api_server.py` 119 passed (including the 5 `tool_choice`/`no_tools` cells), and the `api_server` family 367 passed, 1 skipped. The commit was pushed to the public fork; an anonymous shallow fetch of the pinned sha works, and the tree carries `setup-hermes.ps1`, `pm/lock.json`, the MIT `LICENSE`, and the `tool_choice` handler.

L10 (compatibility risk, open) — the app depends on Hermes internals. In the new base `resolve_provider` still accepts `custom`, `_resolve_openrouter_runtime` still trusts `model.base_url`/`model.api_key` for bare `custom`, the Telegram plugin adapter path is unchanged, and `/v1/runs` still exists. But upstream added `_config_base_url_trustworthy_for_bare_custom`, a newer trust check that could reject a `base_url` the app writes. This needs an end-to-end run on a real gateway before declaring S3/S9 closed.

L11 (e2e, closed) — an isolated gateway was started from the merged tree on `127.0.0.1:8643` with a temporary `HERMES_HOME` (copy of the real `config.yaml`/`.env`, Telegram disabled, `API_SERVER_PORT=8643`), leaving the live home and the 8642 gateway untouched. The real config is exactly the risky shape: `model.provider: custom`, `model.base_url: https://api.deepseek.com`. Results: `/health` 200, `/v1/capabilities` 200, `POST /v1/runs` 202 → `queued` → `running` → `completed` with `message.delta` events spelling "mercurio", and `POST /v1/chat/completions` with `tool_choice: "none"` 200 with `content: "mercurio"`. The new bare-custom trust check accepts an explicit `provider: custom`, so the mapping Demiurgos writes is safe. The test gateway was stopped and the temporary home deleted; `~/.hermes/config.yaml` and `.env` were never modified.

L12 (compatibility finding for T6) — the new upstream reads the API-server port from `API_SERVER_PORT` / `API_SERVER_HOST` (`gateway/config_env.py`), while `scripts/start-demiurgos.sh` exports `HERMES_GATEWAY_PORT` / `HERMES_GATEWAY_HOST`. With the new runtime the launcher's port selection is ignored and the gateway silently binds the default 8642. T6 must switch the launcher (and `start-demiurgos.ps1`) to the new env names and keep the default safe.

L13 (T6 exact work, verified) — `scripts/start-demiurgos.sh:530` currently exports only `HERMES_GATEWAY_HOST=127.0.0.1 HERMES_GATEWAY_PORT="$GATEWAY_PORT"`; `start-gateway.ps1:94-95` does the same. Fix both to export `API_SERVER_HOST`/`API_SERVER_PORT` (keep the legacy names too, so older builds still work). `start-demiurgos.ps1` starts only the API, not the gateway; `start-gateway.ps1` is the Windows gateway entry. `hermes_probe_support.py` already uses `API_SERVER_PORT`; `test_semantic_e2e.py:571-572` still sets the legacy names (excluded from CI — update for consistency). Also switch the launcher's binary resolution: prefer the product-owned `$DEMIURGOS_HOME/hermes/bin/hermes`, use `command -v hermes` only as a dev fallback, and export `HERMES_HOME=$DEMIURGOS_HOME/hermes` + `HERMES_AGENT_ROOT=$DEMIURGOS_HOME/hermes-agent` so the project plugin resolves the checkout.

L14 (T3/T4 design, next session) — one provisioning owner, invoked by both platform installers and the CLI stack:
- `scripts/provision-hermes.sh` (POSIX) and `scripts/provision-hermes.ps1` (Windows), called from `scripts/install-demiurgos.sh` / `.ps1` (the default install) and from `install.sh --with-cli-stack` (replacing `install_hermes`).
- Constants: `HERMES_FORK_URL=https://github.com/maar1223/hermes-agent-demiurgos.git`, `HERMES_PIN=d046ff9905b8470c4a0cfd5e9da566986056b438`.
- Fetch the pinned commit without a full clone: `git init` + `git remote add` + `git fetch --depth 1 origin "$HERMES_PIN"` + `git checkout FETCH_HEAD`, then assert `git rev-parse HEAD == $HERMES_PIN`.
- Install with the product root: run `setup-hermes.sh` / `setup-hermes.ps1` from the checkout with `HERMES_HOME=$DEMIURGOS_HOME/hermes`, `HERMES_RUNTIME_DIR=$DEMIURGOS_HOME/hermes/tools`, `HERMES_AGENT_ROOT=$DEMIURGOS_HOME/hermes-agent`. The setup scripts stage their own pinned uv and hash-verify deps via `pm/lock.json`/`uv.lock`.
- Prior install: detect `command -v hermes` and `~/.hermes`, report what was found, and modify nothing there (no `config.yaml`, no `profiles/`, no `.env`). The product runtime is used regardless.
- Boot verification: the launcher checks the product binary exists and its checkout is at the pin; failure is closed with expected-vs-found and the remedy.
- License: ship the MIT `LICENSE` text as a third-party notice in the artifact, and add it to the release extras + allow-list.
- Tests: `test_installer_hermes_isolation.py` extended (no `$HOME/.hermes` write, pin constant, product paths), `test_installer_contract.py` still green, launcher suites green, and a focused unit test for the pin/fetch/verify helpers.

L15 (next-session start) — read this document and the `nec/checkpoint` observation first. Then, in order: (1) T6 launcher env/binary fix from L13, with the launcher suites; (2) T3/T4 `provision-hermes.{sh,ps1}` from L14, with the installer contract tests; (3) T5 isolation (`HERMES_HOME` export, `configure_mcp_profile` out of `~/.hermes/profiles`, prior-install report); (4) T7 docs/readiness/license; (5) T8 full verification. Do not modify `~/.hermes`, do not restart the live gateway, and do not push the Demiurgos branch without the Owner's decision. The fork is public and pinned; future runtime updates are `git merge upstream/main`, never a rebuild.

L16 (execution, T6) — implemented in `scripts/start-demiurgos.sh` and `start-gateway.ps1`:
- Both gateway entry points now export `API_SERVER_HOST`/`API_SERVER_PORT` alongside the legacy `HERMES_GATEWAY_HOST`/`HERMES_GATEWAY_PORT`, so the pinned upstream binds the launcher's port and older builds still work. `test_semantic_e2e._start_gateway` was updated for consistency.
- Binary resolution prefers product-owned absolute paths: the checkout's exact-install launcher (`<agent root>/.hermes/bin/hermes[.exe|.cmd]`, created by `ensure_install_launchers` on both platforms) and the installer-published `<hermes home>/bin/hermes[.exe|.cmd]` (Windows convention). `command -v hermes` / `~/.local/bin/hermes` are dev fallbacks only.
- `HERMES_AGENT_ROOT` is exported (when the checkout's `plugins/` package exists) before either child starts; `HERMES_HOME` keeps the ratified conditional export (only when `<dedicated root>/config.yaml` is provisioned).
- Evidence correction to L13: on POSIX `setup-hermes.sh` publishes conveniences to `~/.local/bin` and the exact install launcher to `<checkout>/.hermes/bin/hermes`; it never writes `<hermes home>/bin`. The launcher therefore checks the checkout launcher first and keeps `<hermes home>/bin` as the Windows installer convention, instead of pinning only `$DEMIURGOS_HOME/hermes/bin/hermes`.
- Verification: `test_launcher_portable.py` (7 new contract tests, including a behavioural sourcing probe proving the product binary beats a different `hermes` on `PATH`) plus the launcher/installer/system-control/probe suites: 297 passed, 11 skipped. Tests were observed RED before the implementation.
