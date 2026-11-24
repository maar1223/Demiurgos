# Assistant runtime evolution — observability first, ownership later

Objective: keep Hermes as the assistant engine for now, make it observable (diagnostics + quality measurement) and keep it swappable, then decide engine ownership phase by phase with evidence. Delivery: phases ship as work-unit commits on branch `feat/assistant-runtime-evolution` (worktree `demiurgos-worktrees/assistant-runtime-evolution`, own `.venv` and `.codegraph`), based on `master`; push/PR/merge remain the Owner's decision. Tests: `pytest src/tools/demiurgos-suite/wiki/tests/ -q`, `cd frontend && npm test -- --run`, assistant wiring gate `python3 scripts/check_assistant_graph.py`.

## Resumen para el Autor (ES)

El asistente es el 50 % del producto, así que no se reemplaza a ciegas. Primero se congela el fork (riesgo cero) y se agrega recuperación automática del asistente (si el motor se cae, vuelve solo; si no puede, la app lo dice y ofrece un botón para reiniciarlo sin cerrar la plataforma), después se vuelve observable (logs que rotan, cola de logs en vez de descartarlos, y un `diagnostics.json` con qué se hizo y dónde falló), luego se mide su calidad con un conjunto dorado de preguntas, y recién al final se decide si el motor se escribe propio. Cada fase es chica, reversible y tiene criterio de abandono. Ninguna fase toca el camino que hoy funciona sin una red de seguridad antes.

---

## Specs

**S1 — The assistant is half the product; its engine must be observable and replaceable.**
Owner, verbatim: *"yo veo a Demiurgos completamente unido a su Asistente de IA. Para mi eso es el 50% del producto. Por eso me preocupa que no funcione adecuadamente"*.
Acceptance: at the end of Phase 2 there is an automated quality baseline and a per-turn diagnostic record; at any point the engine can be swapped by configuration without touching product code.

**S2 — Hermes stays as the engine until measurement and diagnostics exist.**
Owner, verbatim: *"me recomiendas entonces que mantenga Hermes verdad? pero que podamos observar cuando algo se rompe, correcto?"*
Acceptance: no engine replacement work starts before Phase 1 (diagnostics) and Phase 2 (golden set) are closed.

**S3 — Zero-regression posture: never replace the working path in place.**
Owner, verbatim: *"tengo miedo porque ya hoy demiurgos funciona bastante bien, me da miedo que despues de los cambios todo se caiga a pedazos y comience una incanzable caza de bugs... me da miedo que esto se convierta en un agujero interminable de tiempo"*.
Acceptance: every phase is independently shippable and revertible; Phase 5 ships behind a config switch with the current engine as default; each phase declares a time-box and an abandon criterion.

**S4 — Installation simplicity: one command, minimal footprint, actionable failures.**
Owner, verbatim: *"Me encantaria que Demiurgos sea absolutamente sencillo de instalar. 1 solo comando y listo. Que no instale tantas cosas y que el usuario no se complique tanto la vida."*
Acceptance: Phase 3 publishes a measured install budget (steps, components, sizes) and removes provisioning nothing consumes; failures keep naming expected-vs-found with a remedy.

**S5 — A bug report carries diagnostic logs of what was done and where it failed.**
Owner, verbatim: *"cuando un usuario haga un reporte de errores, tambien adjunte un archivo de logs de que fue lo que se hizo y en que falló el sistema... con esa informacion es mas simple de parte de un agente saber donde está el error y asi no dependemos al 100% de que el usuario haya situado perfectamente donde está el bugs"*.
Acceptance: a report submitted after weeks of accumulated logs still carries the last diagnostic window plus a structured record of recent operations and the failing assistant turn.

**S6 — Privacy by default: metadata, not author content.**
Acceptance: bundled diagnostics contain no world text, prompt bodies, answer bodies, `.env` values or account identity by default; content snippets are opt-in and visibly labelled; secrets are always redacted.
Owner constraint that motivates it: the relay publishes to Telegram, a channel outside the author's machine.

**S7 — Quality is measured, not assumed.**
Acceptance: a golden set of level-C questions (answer exists only inside a ficha) with expected facts, run manually and on every release/update, establishes the baseline before and after any engine change.

**S8 — Freeze the pinned fork.**
Acceptance: the pin does not move without a Demiurgos feature that requires it; the repair runbook exists and is current.
Rationale (evidence): the fork exists for ONE patch (`tool_choice: none`); past pin moves already produced a merge conflict in `gateway/platforms/api_server.py` and a new upstream trust check that could reject the configured `base_url`.

**S9 — The adapter Protocol is the swap seam.**
Acceptance: the engine is selected by configuration implementing `probe/start/status/cancel/events`; the product never imports engine internals.
Evidence: `assistant_activity.py:98-116` defines `HermesActivityAdapter`; the app consumes it structurally and the tests already use fakes.

**S10 — Every phase has an exit gate and a stop rule.**
Acceptance: a phase that misses its gate inside its time-box is paused, not extended; the previous phase stays live.

**S11 — The assistant recovers visibly and locally.**
Owner, verbatim: *"porque no hacemos que cuando hermes se caiga demiurgos se reinicie automaticamente? o al menos le diga al usuario que pasó y que si quiere usar el asistente de IA debe reiniciar (y en dicha pantalla emergente aparezca el boton de reiniciar)"*.
Acceptance: (a) a dead gateway is restarted automatically with bounded backoff and an attempt cap; (b) after the cap, the UI states a localized cause and offers a single action that restarts **only** the assistant, leaving the API and the user's in-flight work untouched; (c) no raw provider, gateway or log text is ever shown; (d) refusals a restart cannot fix (pin mismatch, invalid configuration, missing credentials) are reported with their remedy and never restart-loop.

---

## Tasks

| ID | Task | Specs | Route | Status | Commit |
|---|---|---|---|---|---|
| T0.1 | Record the fork-freeze policy and pin rationale in the runtime runbook | S8 | inline | done | 4f98d6d |
| T0.2 | Write the repair runbook (gateway down, pin mismatch, re-provision, log locations) | S8 | inline | done | 4f98d6d |
| T0.5.1 | Gateway supervisor: detect exit, bounded backoff restart, attempt cap | S11 | inline | done | 0742955 |
| T0.5.2 | Supervisor status file plus API read model | S11 | inline | done | 0742955 |
| T0.5.3 | Localized cause vocabulary and mapping (no raw text) | S11 | inline | done | 0742955 |
| T0.5.4 | `POST /api/system/assistant/restart` (authenticated, idempotent, gateway-only) | S11 | inline | done | 0742955 |
| T0.5.5 | UI recovery card/dialog with one restart action | S11 | inline | dropped (D9: the banner is the surface) | — |
| T0.5.7 | Repurpose the existing health banner action and copy (state-dependent, non-modal) | S11 | inline | done | 02294d9 |
| T0.5.6 | Tests: auto-recovery, attempt cap, no-loop on refusals, gateway-only restart | S11 | inline | done | 0742955, 02294d9, 68ab9db |
| T1.1 | Size-based rotation for `demiurgos-api.log`, `demiurgos-gateway.log`, `launcher.log` | S5 | inline | done | e48bb3f, 94dd98c |
| T1.2 | Replace all-or-nothing log assembly with a most-recent tail budget | S5 | inline | pending | — |
| T1.3 | Persist an operations ring buffer (endpoint, world, status, duration, error code, run_id) | S5 | inline | pending | — |
| T1.4 | Record the assistant turn (run_id, tools, evidence, gate decision, model, timings) | S5 | inline | pending | — |
| T1.5 | Add `diagnostics.json` to the report contract; bump the relay schema with the relay owner | S5, S6 | delegated (coordination) | pending | — |
| T1.6 | Content policy: metadata default, content opt-in, redaction verified | S6 | inline | pending | — |
| T1.7 | Tests: rotation, tail budget, redaction, cap behaviour, never-500 | S5, S6 | inline | pending | — |
| T2.1 | Define the golden-set corpus format (question, expected facts, must-not, level) | S7 | inline | pending | — |
| T2.2 | Build the runner `scripts/eval_assistant.py` against a live stack | S7 | inline | pending | — |
| T2.3 | Run and record the baseline on the current install | S7 | inline | pending | — |
| T2.4 | Wire the golden set into the update/release checklist | S7 | inline | pending | — |
| T3.1 | Measure the install budget: steps, components, sizes, prerequisites | S4 | inline | pending | — |
| T3.2 | Remove provisioning nothing consumes; keep the one-command path | S3, S4 | inline | pending | — |
| T3.3 | Actionable failures: expected-vs-found with remedy on every install/boot gate | S4 | inline | pending | — |
| T3.4 | Publish before/after measurements in the install docs | S4 | inline | pending | — |
| T4.1 | Provider client for single-shot calls (reuse `assistant_provider_adapters` defaults) | S1, S3 | inline | pending | — |
| T4.2 | Migrate one-shot call sites: import enrichment, semantic intent, edit-suggest, materialization, memory, vision | S1, S3 | inline | pending | — |
| T4.3 | Differential parity: identical output per migrated prompt vs the gateway path | S3, S7 | inline | pending | — |
| T4.4 | Reduce Hermes to `/v1/runs` only; document the reduced contract | S1, S9 | inline | pending | — |
| T5.1 | `OwnRunsAdapter` skeleton behind the Protocol (MCP client, model client, SSE) | S1, S9 | inline | pending | — |
| T5.2 | First-party session store and history replay | S1 | inline | pending | — |
| T5.3 | Config switch with Hermes as default and a one-line kill switch | S3, S9 | inline | pending | — |
| T5.4 | Acceptance: golden-set parity + level-C + full suite, inside the time-box | S7, S10 | inline | pending | — |
| T5.5 | Channels decision: Telegram/TTS/vision stay on Hermes or migrate separately | S1, S10 | ask-on-risk | pending | — |
| T6.1 | Retire Hermes only when S7/S9 are satisfied and channels are resolved | S1, S10 | ask-on-risk | pending | — |

---

## Phase detail

Every phase states entry criteria, exit criteria, estimated sessions (estimate, not a promise), risk and rollback.

### Phase 0 — Freeze the fork (0 sessions of code)

- **What:** write the pin policy and the repair runbook. No source changes.
- **Why:** removes the whole "upstream broke us" failure class for free. It is the cheapest risk reduction available.
- **Entry:** none.
- **Exit:** runbook covers gateway-down, pin mismatch, re-provision, where each log lives, and how to read a report bundle.
- **Risk:** none. **Rollback:** n/a.

### Phase 0.5 — Assistant survival (1–2 sessions)

- **What:** supervise the gateway and add a user-facing recovery action.
- **Why:** today a dead gateway leaves the assistant dead until the user restarts the whole platform (E15, E17), and the UI can already say "unavailable" but offers no way out (E16). Availability is the cheapest resilience win and it does not touch the engine.
- **Design constraints:**
  - The supervisor restarts **only** the gateway child; the API and the user's in-flight work are untouched.
  - **Owner (D10):** one small Python supervisor (`src/tools/demiurgos-suite/wiki/gateway_supervisor.py`) spawned by the launcher in place of `hermes gateway run`; it owns the child, the backoff loop and the structured status file. Not a launcher shell loop: one tested owner, no duplicated state.
  - Exponential backoff with a bounded attempt cap (starting proposal: 3 attempts at 5 s / 15 s / 45 s), then stop and surface the cause. Attempts reset after a gateway run that stays up past a threshold, so three crashes spread over weeks never cap a healthy install.
  - One small status file the API reads (state, attempts, last error class, last restart time); no new database. Lives beside the launcher pid files in the same runtime state dir; JSON with an explicit schema, atomic write.
  - Localized cause from a closed vocabulary. **Correction (L11):** the supervisor emits only what it can observe without parsing log text — `not_started`, `exited`, `config_invalid`. `provider_rejected` and `timeout` stay in the per-turn failure taxonomy (`assistant-failure-recovery.md` S3/S4); a pin mismatch never reaches the supervisor because the launcher already rejects the runtime at boot (`verify_product_runtime` runs `provision-hermes.sh --check`), so it presents as `not_started`. Never raw log or provider text.
  - The UI offers exactly one action: "Reiniciar asistente" → `POST /api/system/assistant/restart` (authenticated, idempotent, rate-limited) → gateway-only restart.
  - **Reuse the existing non-modal health banner** (`AIAssistantSidebar.tsx:891-905`) and its periodic recheck instead of adding a modal. Its single action becomes state-dependent: `gatewayDown` → restart the assistant; `pendingReload` → restart the assistant so it loads the new configuration; `notConfigured` → open Profile (no restart helps). Copy changes from "vuelve a iniciar Demiurgos" to the in-place action.
  - **pendingReload correction (L11):** a gateway-only restart is what loads the new `config.yaml`, but `_resolve_assistant_runtime_state` only reports `active` after a recorded acceptance for that revision. The restart action therefore also re-runs the existing bounded `_converge_assistant_acceptance` in the API, so the banner can clear without a platform restart.
  - **Background-first:** a restart that completes while idle is invisible (the banner auto-hides on the next recheck). The banner only becomes visible if a turn was lost or recovery failed.
  - No auto-restart for refusals a restart cannot fix (`config_invalid`, missing or invalid credentials): report the cause with its remedy instead.
- **Entry:** Phase 0 done.
- **Exit:** killing the gateway by hand brings it back inside the backoff window and the assistant answers again; forcing a failure past the cap shows the cause and the restart button fixes it **without reloading the app**; tests cover both paths and the no-loop rule.
- **Risk:** low-medium (child-process lifecycle). **Rollback:** one config flag disables the supervisor; manual restart keeps working.

### Phase 1 — Diagnostics in bug reports (2–3 sessions)

- **What:** rotate logs; send the tail instead of dropping everything; add a structured `diagnostics.json`.
- **Why:** today a report after weeks of use can arrive with zero logs (see Evidence E4), and there is no record of the failing turn (E5). This is the highest-value, lowest-risk investment for real support.
- **Design constraints:**
  - The operations ring must survive a crash: append to a small JSONL under the install state dir, capped by entries and bytes (e.g. 200 entries / 512 KB).
  - Assistant turn fields: `request_id`, `run_id`, `tools[] = {name, ok, duration_ms}`, `evidence_status` (`complete|incomplete|none`), `semantic_decision` (`state`, `action`), `model`, `stage_timings`, `error_code`.
  - World identification in metadata is a hash by default; the real name is content, therefore opt-in (S6).
  - Log assembly must be deterministic: newest files first, per-file and total byte budgets, never a silent empty payload.
- **Entry:** Phase 0 done.
- **Exit:** a report generated after more than 64 KB of logs still carries (a) the last log window, (b) the operations ring, (c) the failing turn; every case covered by tests; no endpoint can 500 on a bad source.
- **Risk:** low; the report path is isolated from the assistant path. **Rollback:** revert the phase; reports keep working with text logs only.

### Phase 2 — Golden set (2–3 sessions)

- **What:** a per-world corpus of level-C questions with expected facts and must-not cases; a runner; a recorded baseline.
- **Why:** today the only acceptance of assistant quality is the Owner asking manually (`ASSISTANT_WORLD_READING.md:229`). Without a baseline, both keeping and replacing the engine are blind decisions.
- **Coverage minimum:** 15–25 level-C cases per world; must-not cases for invented canon, claimed authority, blind answers when the graph is down, wrong language/tone.
- **Entry:** Phase 1 done (so a failing case can be diagnosed).
- **Exit:** `scripts/eval_assistant.py` prints per-case PASS/FAIL, the baseline is recorded in this document, and the command is in the update checklist.
- **Risk:** low. **Rollback:** the runner is a dev tool; it never mutates the install.

### Phase 3 — Installer audit (2–3 sessions)

- **What:** measure, cut, and make failures actionable.
- **Why:** one command already exists (`curl … | bash`); the problem is what it installs (E8).
- **Entry:** Phase 1 done (diagnostics make install failures debuggable).
- **Exit:** a published install budget (components, sizes, steps) before/after; provisioning that nothing consumes is removed; every boot/install failure names expected-vs-found with a remedy.
- **Risk:** medium (installer is the support surface). **Rollback:** installer changes ship as separate commits with contract tests.

### Phase 4 — Direct provider for one-shot calls (2–4 sessions)

- **What:** talk to the configured provider directly for text→JSON and text→text calls; keep Hermes only for `/v1/runs`.
- **Why:** removes most gateway call sites, the `tool_choice: none` fork dependency for those paths, and one class of failure.
- **Constraint:** one call site per commit, each with a differential check proving the same output for the same prompt.
- **Entry:** Phase 2 baseline recorded.
- **Exit:** all listed call sites migrated; the gateway is optional for them; parity evidence recorded.
- **Risk:** medium-low. **Rollback:** per-call-site revert.

### Phase 5 — Own engine behind the Protocol (8–15 sessions, optional)

- **What:** implement `probe/start/status/cancel/events` with a model client, an MCP tool loop, SSE and a first-party session store.
- **Why:** ownership of the engine is a strategic goal, not an emergency (S1). It only starts if Phases 1–4 still leave a real pain.
- **Hard gates:** golden-set parity, a level-C conversation against a real world, full suite green, kill switch proven by switching back.
- **Time-box:** if the exit gate is not met inside the box, the phase is paused and Hermes stays; the work is behind a config switch, so nothing regresses.
- **Risk:** high (the product's differentiator). **Rollback:** flip the config to Hermes.

### Phase 6 — Retire Hermes (2–3 sessions)

- **What:** remove the pinned runtime from the install once Phase 5 is accepted and Telegram/TTS/vision are resolved.
- **Entry:** Phase 5 accepted; channels decision recorded.
- **Exit:** install no longer provisions the runtime; MIT notice handling updated; uninstall path documented.
- **Risk:** medium. **Rollback:** the pinned provisioner remains available until the next release cycle.

---

## Evidence (verified 2026-11-23, read-only)

- **E1 — Swap seam exists.** `src/tools/demiurgos-suite/wiki/assistant_activity.py:98-116` defines `HermesActivityAdapter` (`probe/start/status/cancel/events`); the product consumes it structurally and the tests already use fakes. The concrete class (`HermesRunsActivityAdapter`, same file:118) is the only production implementation.
- **E2 — Gateway contract actually used.** `GET /capabilities`, `POST /runs`, `GET /runs/{id}`, `GET /runs/{id}/events` (SSE), `POST /runs/{id}/stop`; plus `POST /v1/chat/completions` and `/health`. See `assistant_activity.py:138-237`, `api_server.py:8992-9066`, `hermes_run_probe.py`.
- **E3 — Logs do land in the install root.** `scripts/start-demiurgos.sh:101-106` defines `LOG_DIR=$INSTALL_ROOT/logs` with `demiurgos-api.log`, `demiurgos-gateway.log`, `launcher.log`; redirections at `:686` and `:700`.
- **E4 — No rotation, and the cap drops everything.** No rotation exists in any script. `bug_report.py:597-603` returns `included: False` with `"logs exceed the size cap"` when the concatenated logs exceed 64 KB (`_LOGS_MAX_BYTES = 65536`).
- **E5 — No structured turn record.** The gateway path logs text previews only: `prompt[:120]`, `content[:200]`, `resp.text[:500]` (`api_server.py:12416-12516`). No run id, tool list, evidence state, gate decision or stage timings.
- **E6 — Logs are default-on and secret-redacted.** `bug_report.py:565-609, 611-625`; redaction via `content_scan.redact_secrets`. Redaction covers secrets, not world content.
- **E7 — Delivery goes through an external relay.** `bug_report.py:216-238, 276-284`: the app posts the bundle to `relay_url`; the provider credential/owner inbox live only in the relay. The relay implementation is NOT in this repository (only install scripts reference bug-report env vars), so relay schema changes require coordination.
- **E8 — The one-command install exists and is heavy.** `README.md:47` (`curl … | bash`), `install.sh` (`bootstrap_web_app` → signed core → `install-demiurgos.sh`), `scripts/provision-hermes.sh` (pinned checkout + `setup-hermes.sh` + `uv` + Python 3.14 + hash-locked deps), plus the app venv and MCP profile.
- **E9 — Hermes scale.** Pinned checkout on this machine: ~440 MB, and non-test Python: `agent/` 150,207 lines / 415 files, `gateway/` 128,974 / 345, `tools/` 129,685 / 367, `plugins/` 91,999 / 304. MIT (`Copyright (c) 2025 Nous Research`).
- **E10 — The fork exists for one patch.** `odd/tasks/hermes-core-runtime.md` S3: `tool_choice: "none"` support. Past pin moves produced a merge conflict in `gateway/platforms/api_server.py` (L8) and a new upstream trust check on bare `custom` base URLs (L10).
- **E11 — The app boots without the assistant.** Same document, S9: the web app still boots when the assistant is unavailable; readiness stays honest.
- **E12 — Wiring gate is not quality.** `scripts/check_assistant_graph.py` checks MCP wiring only; level C is manual (`docs/architecture/ASSISTANT_WORLD_READING.md:178, 229-231`). No evaluation corpus exists in the repository.
- **E13 — Channels depend on Hermes.** Telegram via `.hermes/plugins/demiurgos-idea-capture` (+ `pre_gateway_dispatch`, platform registration, media caches); TTS via `scripts/hermes_tts_voice.py`; image/voice enrichment via the gateway and bundled adapters.
- **E14 — Config is a Hermes artifact.** `assistant_settings.py` reads/writes the active profile's `config.yaml` (`model.provider`, bare `custom` + `base_url`); `assistant_provider_adapters.py` already holds provider-neutral endpoints and discovery.
- **E15 — No gateway supervision.** Launcher actions are `start|restart|stop|install` (`scripts/start-demiurgos.sh:975-993`); `restart` runs `stop_all; start_services`, i.e. the whole platform. The gateway child is started in the background (`:700`) and nothing respawns it if it exits.
- **E16 — The UI already has a non-modal health banner, but its action only re-probes.** `AIAssistantSidebar.tsx:891-905` renders a slim banner (not a modal) driven by three localized states (`assistant.health.notConfigured`, `gatewayDown`, `pendingReload`); the `Reintentar` button calls `checkHealth()` (`:466-494`), which re-probes on demand, on focus and on a periodic interval. There is no restart action, so a dead gateway keeps reporting "down" forever.
- **E17 — The only restart is platform-wide.** `POST /api/system/restart` dispatches the launcher's `restart` (`system_control.py:184-192`), which stops and starts API and gateway together; there is no gateway-only action.
- **E18 — The three launcher logs have append-only writers and no rotation.** `scripts/start-demiurgos.sh:324` (`log_event`), `:749` (`>>"$API_LOG" 2>&1`) and `:772` (`>>"$GATEWAY_LOG" 2>&1`) are the only writers; `gateway_supervisor._run_once` passes no `stdout`/`stderr` to `Popen`, so the gateway child inherits the supervisor's `O_APPEND` fd. No rotation existed in any script (E4).

## Decisions recorded

- **D1** Keep Hermes as the engine now; ownership is a later, evidence-gated decision (S1, S2).
- **D2** Diagnostics (Phase 1) ship before the golden set (Phase 2) because they fix today's support pain.
- **D3** No engine work before measurement exists (S2, S7).
- **D4** Freeze the pin; move it only for a required feature (S8).
- **D5** Diagnostics are metadata by default; content is opt-in (S6).
- **D6** The `HermesActivityAdapter` Protocol is the only swap seam (S9).
- **D7** Every phase carries a time-box and an abandon criterion (S10).
- **D8** Assistant recovery is bounded, visible and gateway-only: auto-restart with an attempt cap, then one user action that never reloads the platform; no restart-loop on refusals a restart cannot fix (S11).
- **D9** Background-first recovery: a successful restart while idle is invisible; the banner appears only when a turn was lost or recovery failed. Reuse the existing health banner instead of adding a modal.
- **D10** The gateway supervisor is one small Python process the launcher spawns in place of the gateway command; it owns the child, the bounded backoff and the JSON status file. The launcher keeps owning process lifecycle (start/stop/restart), and the API never spawns the gateway itself.
- **D11** The supervisor's cause vocabulary is limited to what it observes without parsing log text: `not_started`, `exited`, `config_invalid`. Provider refusals and timeouts remain per-turn causes (`assistant-failure-recovery.md` S3/S4); a pin mismatch is rejected at boot by the launcher and presents as `not_started`.
- **D12** Assistant restart is a launcher action (`restart-assistant`) dispatched detached by the API, exactly like the platform restart: same auth gate, same file-based stderr capture, no user input reaching the shell. The API adds idempotency/rate limiting and re-runs the bounded acceptance convergence after dispatch.
- **D13** The recovery read model is its own authenticated endpoint (`GET /api/system/assistant`) so assistant settings stays a settings contract; the UI fetches it only while the assistant is degraded.
- **D14** Log rotation is one small Python module (`log_rotation.py`) driven by the API's existing background lifecycle; the launcher stays the owner of *where* the logs live and exports `DEMIURGOS_LOG_DIR`. It rotates by copy+truncate, never by renaming a live log, because all three logs are written through `O_APPEND` shell handles that must keep pointing at the live path; archives are named `<log>.N` so the existing `*.log` glob in `bug_report` cannot read the same bytes twice. What is bounded is the archive count, not the bytes: a file that overshoots between checks is archived whole.

## Open questions (need the Owner or the relay owner)

1. Relay ownership: who owns the endpoint and who can bump the schema to carry `diagnostics.json`?
2. Are Telegram, TTS and vision **must-keep** product features, or nice-to-have? (Decides the true cost of Phase 6.)
3. Is the world name acceptable diagnostic metadata, or must it be hashed even though the recipient is the Owner?
4. ~~Log rotation owner: launcher (shell) or a small Python writer inside the API? (Prefer one owner, tested.)~~ **Resolved 2026-11-24 (D14):** `log_rotation.py`, run by the API's boot thread; the launcher exports `DEMIURGOS_LOG_DIR` and stays the owner of the location.
5. Should `collect-diagnostics.sh` produce the same `diagnostics.json` format, so manual and automated bundles are interchangeable?
6. Supervisor owner: launcher shell loop or a small Python supervisor with structured state and logs? (Prefer one owner, tested.)
7. Recovery surface: non-blocking banner in the assistant panel, or a modal dialog? (A modal interrupts imports and edits in progress; a banner does not.)
8. Backoff parameters: is 3 attempts at 5 s / 15 s / 45 s the right starting point, or should the last attempt be manual-only?
9. Does a gateway-only restart suffice for `pendingReload` (the new configuration is read on start), or does that state still require a platform restart?

## Resume protocol (for future sessions)

1. Search Engram for `odd/assistant-runtime-evolution/tasks` and read the full observation; then read this file.
2. Read `nec/checkpoint`.
3. Read `## Tasks`; the next unfinished task is the entry point. Do not start a later phase before the previous exit gate is observed.
4. Quote the task by reference: `Spec: odd/tasks/assistant-runtime-evolution.md, T1.2, S5`.
5. Record in `## Log` the task outcome, the evidence and the next step; mirror at every phase transition.

---

## Log

**L1 (Owner request, verbatim, 2026-11-23):** *"ok, crea una documentacion por fases de este cambio. Todo bien detallado, y le daremos en sesiones futuras paso a paso, te parece bien?"*

**L2 (scope-defining Owner statements, verbatim, same conversation):**
- *"yo veo a Demiurgos completamente unido a su Asistente de IA. Para mi eso es el 50% del producto. Por eso me preocupa que no funcione adecuadamente"*
- *"lo que me preocupa es tener una herramienta que se puede romper y que no pueda reparar adecuadamente ya que no es 100% mia. Y que se caiga el sistema en una pc que no sea la mia. Me encantaria que Demiurgos sea absolutamente sencillo de instalar. 1 solo comando y listo. Que no instale tantas cosas y que el usuario no se complique tanto la vida."*
- *"tengo miedo porque ya hoy demiurgos funciona bastante bien, me da miedo que despues de los cambios todo se caiga a pedazos y comience una incanzable caza de bugs. Lo de Engram fue facil. Pero me da miedo que esto se convierta en un agujero interminable de tiempo"*
- *"cuando un usuario haga un reporte de errores, tambien adjunte un archivo de logs de que fue lo que se hizo y en que falló el sistema... con esa informacion es mas simple de parte de un agente saber donde está el error y asi no dependemos al 100% de que el usuario haya situado perfectamente donde está el bugs que está reportando"*
- *"me recomiendas entonces que mantenga Hermes verdad? pero que podamos observar cuando algo se rompe, correcto?"*

**L3 (analysis, read-only session):** mapped the real Hermes surface (E1–E14). Conclusion: the assistant's *brain* (prompt, memory, world context, skill routing, semantic gates, graph tools, evidence, validation) is already Demiurgos-owned; Hermes is the *engine* (model transport, tool loop, session transcript, skills injection, streaming). The only indispensable engine capability is the tool loop plus sessions. Everything else is single-shot calls or channels.

**L4 (decision):** keep Hermes; invest first in observability and measurement (D1–D3). Phase ordering: freeze → diagnostics → golden set → install audit → direct provider → optional own engine → optional retirement.

**L5 (evidence used to prioritize Phase 1):** the bug-report log path exists end to end (E3, E6, E7), but three defects make it fail the Owner's goal: no rotation with an all-or-nothing 64 KB drop (E4), no structured turn record (E5), and no content policy (E6). These are small, isolated fixes with no runtime risk.

**L6 (assumption, marked):** effort estimates are session-count estimates, not commitments. Relay-side behaviour is unverified from this repository (E7) and is listed as an open question.

**L7 (Owner request, verbatim, 2026-11-23):** *"ok y porque no hacemos que cuando hermes se caiga demiurgos se reinicie automaticamente? o al menos le diga al usuario que pasó y que si quiere usar el asistente de IA debe reiniciar (y en dicha pantalla emergente aparezca el boton de reiniciar)"*
Scope added: Phase 0.5 (S11, T0.5.1–T0.5.6). Verified gaps: no gateway supervisor (E15), the UI already models unavailability but exposes no recovery (E16), and the only restart is platform-wide (E17). Decision D8: bounded, visible, gateway-only recovery; never restart-loop on refusals a restart cannot fix. This phase does **not** detect silent degradation — that remains Phase 2's job.

**L8 (Owner question, verbatim, 2026-11-23):** *"y no se podria reiniciar en segundo plano sin molestar al usuario?"*
Answer recorded: yes, background-first is the default (D9). Evidence correction: the UI banner is already non-modal and already re-probes on focus and on an interval (`AIAssistantSidebar.tsx:891-905`, `:466-494`), so the visible surface is mostly built and auto-hides. Remaining work is the supervisor, the gateway-only restart endpoint, and making the banner's existing button state-dependent (T0.5.7). Visible only when a turn was lost or recovery failed.

**L9 (Owner authorization, verbatim, 2026-11-23):** *"seguimos con el plan del checkpoint"*. Scope: Phase 0 complete plus the core of Phase 0.5, on an isolated worktree (Owner chose "Worktree aislado (Recomendado)" over the current checkout). Technical decisions taken without asking: the supervisor is one small Python process with structured state (not a launcher shell loop), and the starting backoff is 3 attempts at 5 s / 15 s / 45 s, configurable. `pendingReload` is a code question, verified before the banner mapping is written.

**L10 (T0.1/T0.2 evidence, commit `4f98d6d`):** `docs/architecture/assistant-runtime-runbook.md`. Verified against the source before writing: pin `d046ff99…` and the fork URL come from `scripts/provision-hermes.sh:36-37`; the `no_tools` tree check is `:144-145`; the staging/backup provisioning (`hermes-agent.previous-<timestamp>`, scratch HOME) is `:148-197`; the profile seeding is `:204-226`; the layout and `--check` mode are `:47-124`; logs are `scripts/start-demiurgos.sh:101-106` with redirections at `:686` and `:700`; the launcher actions are `:975-996` and the entry point is `<root>/bin/demiurgos` (`:922-938`); the report payload/redaction/64 KB drop are `bug_report.py:78,96-97,470-492,565-609`; the manual bundle is `scripts/collect-diagnostics.sh`; the payload ships both scripts (`scripts/install-local.sh:251-253`). Phase 0 exit gate met: gateway-down, pin mismatch, re-provision, log locations and bundle reading are all covered. Route: inline; docs-only, so structural readback is the proportional check.

**L11 (Phase 0.5 design verified in code, 2026-11-23):** corrections that the implementation follows.

- The launcher already rejects a pin mismatch at boot: `verify_product_runtime` (`scripts/start-demiurgos.sh:738-744`) runs `provision-hermes.sh --check` and clears `HERMES_BIN`; a mismatch therefore presents as "the runtime was never started", never as a restart loop. The supervisor does not duplicate the pin check (D11).
- `pendingReload` is not "needs a restart": `_resolve_assistant_runtime_state` (`api_server.py:1190-1213`) returns it whenever the gateway is live but this revision has no recorded `runtime: accepted` evidence. Only the bounded `_converge_assistant_acceptance` (`api_server.py:1106-1160`, started once at boot at `:395`) records it. A gateway-only restart loads the new `config.yaml`, and the restart action must also re-run convergence, or the banner never clears without a platform restart.
- The provider/timeout causes are already classified per turn (`assistant-failure-recovery.md` T3/T4); parsing gateway log text in the supervisor would duplicate them and break S11(c).
- The launcher kills descendants of a component pid (`_kill_process` + `pgrep -P`), and the port fallback gates on the cmdline; the supervisor's cmdline must therefore be recognised by `is_gateway_cmdline` (it will be, because it carries the Hermes path and `gateway run`), and a pid-file stop must terminate the child through the supervisor's own signal handling.
- The UI comment in `AIAssistantSidebar.tsx:471-476` already claims "the launcher restarts Hermes without touching this page"; today that is false (E15). Phase 0.5 makes it true.

Frozen contract for the implementation:

- Status file: `<launcher state dir>/gateway-supervisor.json`, schema `demiurgos.gateway-supervisor/v1`, keys `{schema, state: starting|running|restarting|failed|stopped, cause: null|not_started|exited|config_invalid, attempts, max_attempts, last_exit_code, last_restart_at, updated_at, supervisor_pid, gateway_pid}`; atomic write; unknown state/schema fails closed in the reader.
- Env tuning: `DEMIURGOS_GATEWAY_SUPERVISOR=0` disables the wrapper (spawn once, current behavior); `DEMIURGOS_GATEWAY_BACKOFF="5,15,45"`; `DEMIURGOS_GATEWAY_MAX_ATTEMPTS=3`; `DEMIURGOS_GATEWAY_RESET_AFTER_SECONDS` resets attempts after a healthy run.
- `GET /api/system/assistant` → `{gateway_running, state, cause, attempts, can_restart, updated_at}` (authenticated, fail-closed).
- `POST /api/system/assistant/restart` → `{action: "assistant-restart", accepted: true|false, coalesced?: true, error?: string}`; authenticated, idempotent inside a 5 s window, dispatches the launcher `restart-assistant` detached, then re-runs the bounded acceptance convergence.
- Launcher action `restart-assistant`: `stop_component gateway`, wait for the gateway port to be free, then `start_services` (which re-exports the runtime env, re-verifies the pin and re-seeds the key) without touching the API.
- i18n keys: `assistant.health.restart`, `assistant.health.restarting`, `assistant.health.restartFailed`, `assistant.health.configInvalid` (es/en).
- Tests: supervisor (cap, no-loop on `config_invalid`, kill switch, attempts reset, status schema), reader/view mapping (each cause and `can_restart`), endpoint (auth, idempotent window, gateway-only action, convergence hook), frontend banner (restart on gatewayDown/pendingReload, cause copy, failure copy), and one existing-behavior test per touched surface (system restart/shutdown unchanged; banner notConfigured unchanged).


**L12 (Phase 0.5 implementation + independent verification, 2026-11-23):** Phase 0.5 core is implemented on `feat/assistant-runtime-evolution` and its two candidate-caused blockers were fixed in `68ab9db`.

- Worktree setup: `demiurgos-worktrees/assistant-runtime-evolution`, own `.venv` (requirements.txt + pytest) and own `.codegraph` index; `frontend/node_modules` is a local symlink to the main checkout and `frontend/dist` was built (`index-gO4a79yV.js`). `.venv` and `node_modules` are untracked local artifacts, never committed.
- Commits: `4f98d6d` runbook, `8f6a19e`/`106d3fe` plan+contract docs, `0742955` backend, `02294d9` frontend, `21a73da` cherry-picked test-hermeticity guard (b97f892 from `feat/methodology-field-rules`; without it a full suite run hits the operator's live gateway — live incident 2026-11-22), `4ab928b` payload manifest, `68ab9db` verification fixes.
- Tests authored before implementation in each unit; the first full execution happened after it, so no RED is claimed. The frontend tests were mutation-checked (`canRestartAssistant = false` made both new action tests fail) to prove they bite.
- Independent verifier (`gentle-ai-verify`, read-only) found B1 (high) and B2 (medium), plus F1-F7. Fixed: B1 (supervisor 3 s escalation inside the launcher's 6 s window + the launcher kills the recorded gateway pid, with two regression tests), B2 (restart action gated on `key_configured` and `can_restart`, plus the `unavailable` remedy copy), F2 (failed dispatch returns one fixed string, never launcher stderr), F3 (cmdline match narrowed to `-m gateway_supervisor`), F4 (20 s coalescing window covers a real restart), F7/S8 (runbook now documents the supervisor, `gateway-supervisor.json`, the closed supervisor vocabulary and `restart-assistant`). Deferred with rationale: F5 (a pin mismatch surfaces as `not_started`; the launcher rejects it at boot and the runbook names the remedy), F6 (`restart-assistant` may *start* a down API through `start_services`; it can never stop it).
- Full backend suite with the guard and no live-E2E opt-in: **5358 passed, 37 skipped, 0 failed** (baseline `master` + the guard: 11 environmental failures). Frontend: **1837 passed** (139 files) before the last two banner tests, **95 passed** in the sidebar file after them; `npm run typecheck` clean; `npm run build` clean. Assistant wiring gate: `python3 scripts/check_assistant_graph.py` → `VERDICT: PASS (2 warnings)`.
- Payload: `scripts/derive_payload_manifest.py --check` is fresh (192 files) after adding the two new modules.
- Not exercised end-to-end: a real kill of the live gateway (would touch the operator's running install). The supervisor behavior is covered by process tests with a fake child; the Owner's live check (kill the gateway → it returns; force past the cap → the cause appears and the button fixes it) remains the Phase 0.5 exit gate.

**L13 (native RDD review, 2026-11-23):** the Owner granted the candidate consent through the native `question` envelope ("Revisar este cambio"). The lineage `review-d3b28d2fe8a10597` froze the target `sha256:018bf333…` over `d3b8700..HEAD` with lenses `review-risk, review-resilience, review-readability, review-reliability`.

- Captured with `admission_decision: completed`: `review-risk`, `review-readability`, `review-reliability`.
- `review-resilience` never produced a result on this OpenCode host: the Task returned `opencode_task_output_empty` on the first grouped launch and on two bound-STSATUS retries (including a withdrawn-and-reoffered slot). It was declared unachievable with the provider's own command (`review capture-unachievable --reason host_agent_output_empty`), which is the documented continuation for that slot.
- The lineage is therefore terminal with `stop/unachievable_lens_slot` and **no approval receipt**: no reduction ran, so no lens findings were surfaced, and no delivery was attempted. Delivery remains the Owner's decision under ordinary repository policy; this is a host-side capture defect, not a candidate verdict.
- Risk coverage for the process-lifecycle surface did happen outside the native review: the independent verifier found and we fixed B1 (orphaned TERM-ignoring gateway) and B2 (banner offered a restart it could not fix), each with regression tests. A scoped re-review (smaller candidate or a single lens) is the clean way to obtain a native receipt if the Owner wants one before publishing.

**L14 (Phase 0.5 live exit gate, 2026-11-23, dev stack from this worktree):** the Owner confirmed Demiurgos was not running, so the gate ran on a fresh dev stack (ports 8000/8642 free, `start-demiurgos.sh --build-if-stale`) and the machine was left stopped afterwards.

- Boot: API `/health` 200; exactly one gateway process listening on 8642 (`hermes`, pid 181891) with `gateway.pid` holding supervisor 180752 and `gateway-supervisor.json` = `{state: running, attempts: 0, max_attempts: 3}`.
- Auto-recovery (S11a): `SIGTERM` to the gateway child → supervisor wrote `restarting` and spawned a new child after the 5 s backoff (new pid 181098, attempts 1); the port reopened once the runtime warmed. API stayed 200 the whole time.
- Bounded cap (S11a): three consecutive exits inside the reset window produced attempts 1→2→3 and then `failed/exited` (last_exit_code -15), the supervisor exited, the gateway stayed down, the port closed and the API still answered 200. No restart loop.
- Manual assistant-only restart (S11b, the exact launcher action the banner dispatches): `start-demiurgos.sh restart-assistant` printed `Already running api (pid 180756)`, started a new supervisor (182654) with attempts reset to 0, and the gateway returned; the API pid was unchanged before/after.
- Shutdown: `start-demiurgos.sh stop` reported `Stopped gateway (pid 182654)` and `Stopped api (pid 180756)`; the supervisor wrote `state: stopped` on TERM, and both ports are free again.
- Not exercised by the agent: the authenticated browser banner (local-dev login requires the Owner's session). The read model is unit-tested (`test_assistant_recovery.py`, `test_assistant_recovery_routes.py`) and the banner's action is the launcher call proven above; the Owner can confirm the visual leg at will.

**L15 (T1.1 rotation, commit `e48bb3f`, 2026-11-24):** size-based rotation for the three launcher logs, verified before writing: the only writers are the launcher's own `log_event` (`scripts/start-demiurgos.sh:324`), the API spawn (`:749`, `>>"$API_LOG" 2>&1`) and the gateway supervisor spawn (`:772`, `>>"$GATEWAY_LOG" 2>&1`); `gateway_supervisor._run_once` passes no `stdout`/`stderr` to `Popen`, so the child inherits that `O_APPEND` fd and never opens the log itself (E18).

- Decision D14 (open question 4 resolved): one Python owner, `log_rotation.py`, started by the API's boot thread; the launcher exports `DEMIURGOS_LOG_DIR` so the location still has a single owner. Copy+truncate instead of rename because truncation keeps every live `O_APPEND` handle on the live path (a rename would move the writes into the archive and leave the live path empty until the next restart). Archives are `<log>.N`, which cannot match `bug_report._default_log_source`'s `*.log` glob, so today's report payload is unchanged.
- Tests authored before the module (RED = collection `ModuleNotFoundError`), then GREEN. `test_log_rotation.py` (27) covers the caps, the shift order, the `*.log` glob, the symlink and missing-dir paths, settings and the loop; `test_log_rotation_safety.py` (8) is the verifier's durable probe set: a real `O_APPEND` fd and a real bash `>>` fd keep writing to the live path across a rotation with no NUL hole, filesystem failures are inert, the archive count is bounded, and the archive keeps the live file's mode.
- Checks: focused 35 passed; full wiki suite 5384 passed / 37 skipped / 4 failed, and all four are environmental (`/` has 1.99 GiB free, the installer tests demand 2 GiB — same class as the 11 baseline failures in L12); `scripts/derive_payload_manifest.py --check` fresh (193 files, new module listed); `scripts/check_assistant_graph.py` → `VERDICT: PASS (2 warnings)`.
- Independent verifier: S5 for T1.1 **MET**, no blockers. Advisories taken: A1 fixed (the archive now inherits the live mode, plus a test); A2 fixed (the docstring now says the archive count is bounded, not the bytes). Advisories recorded and left as-is: A3 (bytes appended inside the copy→truncate window are lost; documented, and the window runs every 300 s), A4 (`rotate_log_dir` rotates every `*.log` in a directory the launcher owns, not only the three names), A5 (until T1.2 a post-rotation report reads only the live files, so it can carry a short window), A6 (copy+truncate across a live fd was proven on Linux only; on Windows an `os.truncate` failure returns `[]` and leaves the log untouched — unverified on Windows).
- Route: inline (one coherent change, ~690 authored lines including tests; splitting it would separate the behavior from its proof). Risk: item 5 (the payload manifest and the launcher export are delivery surface — a missing module would ship a broken feature).
- Native review (RDD on, consent granted by the Owner through the native envelope): lineage `review-5dfd6190f1e035da`, target `sha256:469d57a2…eb427905`, `cb8c815..f15ac2b`, lenses `review-risk`, `review-resilience`, `review-reliability` — the resilience lens captured this time, unlike L13. All three admitted (`admission_decision: completed`); state `approved`; receipt acknowledged and authority burned (`gentle-ai.review-acknowledged/v1`). No blockers; nine non-blocking findings.
- Review advisories closed in `94dd98c` (three that change behaviour): copy-then-evict (a failed copy no longer destroys retained generations, plus its test), a logged warning instead of a silent per-pass failure (plus its test), and a private-mode staged copy so a hardened log is never briefly world-readable (plus its test). The shell append probe now waits on a sentinel instead of a 1 s sleep. Left as recorded advisories: the copy→truncate window still loses in-flight bytes (documented), rotation still covers every `*.log` in the launcher-owned directory (A4), `DEMIURGOS_LOG_DIR` is still only exercised through the Python seam (a launcher-level test would duplicate the wiring), and the return value still underreports a truncate-only failure. After the fixes: focused 38 passed; full suite 5394 passed / 37 skipped / 5 failed, all five environmental (the 2 GiB disk gate; the fifth appeared only because free space dropped to 1.93 GiB).
