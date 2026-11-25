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
| T1.2 | Replace all-or-nothing log assembly with a most-recent tail budget | S5 | inline | done | 88db7c6 |
| T1.3 | Persist an operations ring buffer (endpoint, world, status, duration, error code, run_id) | S5 | inline | done | 2329bd5 |
| T1.4 | Record the assistant turn (run_id, tools, evidence, gate decision, model, timings) | S5 | inline | done (activity turn; guided turn pending) | c0f61ea |
| T1.5 | Add `diagnostics.json` to the report contract; bump the relay schema with the relay owner | S5, S6 | delegated (worker + independent verifier) | done in the app; relay side pending deployment | 57e7b77 |
| T1.6 | Content policy: metadata default, content opt-in, redaction verified | S6 | inline | done | 413dbde |
| T1.7 | Tests: rotation, tail budget, redaction, cap behaviour, never-500 | S5, S6 | inline | done (inventory in L23; two never-500 gaps closed) | 413dbde |
| T2.1 | Define the golden-set corpus format (question, expected facts, must-not, level) | S7 | inline | done | bef30c9 |
| T2.2 | Build the runner `scripts/eval_assistant.py` against a live stack | S7 | inline | done | ddf85a7 |
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
- **D15** The content policy is a field rule on the app's own writers, not a prose heuristic: `preview=` is the field the gateway records use for prompt/answer tails (`api_server.py`, `Hermes GW START/DONE`), so the report replaces that payload and keeps the rest of the record (`len=`, session, timing, outcome). The opt-in travels as the `x-bugreport-content` header rather than a payload field because the relay validates an exact key set and a new field would need a schema bump on a service outside this repo. The label (`== content snippets included at the reporter's request ==`) lives inside `logs`, is charged to the same byte budget, and is decided on the shipped text — never on what the sources contained. The policy is re-enforced on `/submit` and `/fallback`, so the panel is not a trust boundary.

- **D16** The golden set is a per-world corpus under `src/tools/demiurgos-suite/wiki/tests/fixtures/assistant-golden/`, mirroring the intent-corpus layout: a `README.md` contract, closed vocabularies in `labels.yaml`, a JSON Schema (`schema.json`) for a `cases.yaml` document and the world descriptor, and one world directory per `<slug>`. A world declares `source: fixture` (its fichas live under the corpus root — deterministic, CI-safe; the graph indexer already ignores the descriptor and cases because it scans only `lore/`, `personajes/`, `referencias/`) or `source: data-root` (a real world resolved from `DEMIURGOS_DATA_ROOT/mundos/<name>`, for a release baseline on the Owner's install). Assertions are facts (`expected_facts` with `any_of`), the citation (`source_paths`), deterministic forbidden strings, and judged `must_not` codes — never the reply prose. The corpus is a dev fixture: no runtime path reads it.

- **D17** The golden-set runner is `scripts/eval_assistant.py`, a read-only stdlib-only dev tool that follows the documented Hermes API server contract (`/capabilities`, `POST /runs`, `GET /runs/{id}/events`) and is not part of the payload, exactly like `scripts/check_assistant_graph.py`. It has two modes: `--validate-only` (schema rules + OKF ficha validation for fixture worlds; deterministic, no network) and live (ask each case's `question`, fold the SSE stream, evaluate). Live by default only runs `source: data-root` worlds, because a fixture world lives in the corpus and is not indexed by the running gateway's `mundos`; `--allow-fixture-live` overrides only for a stack configured to index it. Evaluation is deterministic (every `expected_facts` group matches an `any_of`, no `must_not.strings`, at least one `source_paths` cited) plus an advisory language heuristic; semantic `invented_canon`/`claimed_authority`/`blind_answer`/`wrong_tone` are written as `judge:` flags for a human, never silently passed. The report carries metadata and per-case verdicts, not answer text unless `--include-answers` (S6).

## Open questions (need the Owner or the relay owner)

1. Relay ownership: who owns the endpoint and who can bump the schema to carry `diagnostics.json`? **App side landed 2026-11-24 (schema 3 + one-step downgrade, L19)**; the relay still has to accept schema 3, and until it does every report pays one rejected probe before the downgraded retry.
2. Are Telegram, TTS and vision **must-keep** product features, or nice-to-have? (Decides the true cost of Phase 6.)
3. Is the world name acceptable diagnostic metadata, or must it be hashed even though the recipient is the Owner?
4. ~~Log rotation owner: launcher (shell) or a small Python writer inside the API? (Prefer one owner, tested.)~~ **Resolved 2026-11-24 (D14):** `log_rotation.py`, run by the API's boot thread; the launcher exports `DEMIURGOS_LOG_DIR` and stays the owner of the location.
5. ~~Should `collect-diagnostics.sh` produce the same `diagnostics.json` format, so manual and automated bundles are interchangeable?~~ **Resolved 2026-11-24 (L19): yes**, the script calls the same module and writes the identical document.
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

**L16 (T1.2 newest log window, commit `88db7c6`, 2026-11-24):** the assembler no longer drops every log when the redacted text passes the cap.

- Shape: `_default_log_source` walks newest first — the live `*.log` (at most `_LOG_SOURCE_MAX_BYTES` = 16 KiB of its newest bytes, read with a seek so a 5 MiB log is never loaded whole), then its `<log>.N` archives in numeric order (`_archives_of`, `.1` newest). Families are ordered by live name, so the window is deterministic instead of mtime-dependent.
- Budget: `_assemble_logs` appends `_tail_window(redacted, …)` per source while the joined payload fits `_LOGS_MAX_BYTES` (64 KiB), then keeps the newest bytes of the first source that overflows and stops. Both cuts drop the partial first line, so the window starts on a record boundary; a single unterminated line longer than the budget is returned as-is rather than discarded. The UTF-8 byte budget is stricter than the relay's UTF-16 unit cap, so the assembled content can never be rejected downstream.
- The `logs exceed the size cap` reason is gone; an empty log set still reports `included: False` with `no logs available`.
- Tests authored first (RED: 7 failures — no archives, drop-everything on oversize), then GREEN. `test_bug_report_log_budget.py` (9) covers the over-cap window and its line boundary, archive order, the total budget dropping older families, a small log carried whole, the honest absent case, redaction inside the tail window, byte-identical repeat assembly, and archive names beyond `.1`.
- Checks: focused 68 passed (9 new + 59 existing bug-report router tests); full wiki suite 5401 passed / 37 skipped / **7 failed, all environmental** — the installer's 2 GiB disk gate again, and the count grew only because free space fell to 1.92 GiB while the suite's temp trees grew; `derive_payload_manifest.py --check` fresh (193 files).
- Route: inline (one module plus its seam tests). Risk: item 2/3? No — the change alters what a diagnostic bundle carries but exposes nothing new: the allow-list, the redaction and the source directory are untouched, so risk is none beyond the delivery surface already covered by T1.1 (no payload file added).

**L17 (T1.3 operations ring, commit `2329bd5`, 2026-11-24):** the API now journals what it was asked to do and where it failed.

- Store (`operations_ring.py`): one append-only `<state dir>/operations-ring.jsonl`, `MAX_ENTRIES` = 200 and `MAX_BYTES` = 512 KiB, compacted atomically (temp + `os.replace`) whenever either bound is crossed, so the newest records survive and a crash mid-compaction cannot corrupt the ring. Two origins survive a crash: one `write` per line, and a torn trailing line is skipped by the reader instead of poisoning the file.
- Fixed schema, no author content: `ts`, `run_id`, `method`, `endpoint` (the matched route template), `world_hash` (16 hex chars of the world name's sha256), `status`, `duration_ms`, `error_code`. Free text is clipped to 300 chars; the world is hashed inside the middleware, so even a custom recorder never receives the raw name (S6).
- Middleware (ASGI, like the backup write signal, so no response is buffered): records `/api/*` requests that failed (`status >= 400`) or mutated (POST/PUT/PATCH/DELETE). Successful reads are skipped on purpose — the UI polls graph/health on a timer and would otherwise evict every real operation. `endpoint` is the route template read from `scope["route"]` after the app handled the request; an unmatched path records `unmatched`, so raw path segments never reach the file. The stable error code comes from the structured error body, which is passed through byte-identical. Recording never breaks a request (`DEMIURGOS_OPERATIONS_RING=0` disables it).
- One existing test changed on purpose: `test_guided_canon_safety_holds_when_semantic_provider_writes`-adjacent assertion `list(tmp_path.rglob("*")) == [vibrantes]` asserted "a guarded request writes nothing". The ring is a deliberate diagnostic side effect, so the test now asserts the real invariant (world tree untouched) plus the bounded allow-list (`operations-ring.jsonl` is the only state file). Recorded here because changing an existing test is a decision, not a detail.
- Tests authored first (RED: collection `ModuleNotFoundError`), then GREEN: `test_operations_ring.py` (18) covers append/read across processes, world hashing, entry and byte caps, malformed-line tolerance, an unwritable ring, the kill switch, and the middleware's recording rules (200 GET skipped, mutating recorded, failed read recorded with its code, unmatched path recorded without raw segments, body passed through, non-http passthrough, and the production wiring).
- Checks: focused 86 passed (18 + the guided-character module); every module except the two installer ones 5211 passed / 26 skipped / 0 failed; `test_installer_contract.py` + `test_payload_audit.py` 205 passed / 10 failed with every failure being the installer's `at least 2 GiB of free disk space` gate (the machine sits at ~1.95–2.02 GiB free, so the count fluctuates run to run — same class as L12's baseline). Manifest regenerated (194 payload files).
- Route: inline. Risk: item 1? No stored author data is touched — the ring is a new diagnosis-only artifact under the state dir with a fixed schema. Item 5 applies (a new module in the shipped payload).

**L18 (T1.4 assistant turn record, commit `c0f61ea`, 2026-11-24):** each activity turn leaves one bounded, non-content record.

- Store: `assistant_turns.py`, `<state dir>/assistant-turns.jsonl`, 100 turns / 256 KiB, sharing `operations_ring.append_bounded_record` / `read_recent_records` — the bounded-JSONL mechanics moved out of the ring so both journals have one compaction and one crash story (the ring's 18 tests stayed green through the refactor).
- Record: `request_id`, `run_id`, `world_hash`, `model` (read from the active profile's `model.default`; None when unreadable, never a guess), `semantic_state`/`semantic_action` from the gate, `tools[] = {name, ok, duration_ms}` (from the translated activity events, capped at 20, names clipped), `evidence_status`, `stage_timings = {gate_ms, run_ms}`, `status`, `close_reason`, `error_code`.
- Two vocabularies defined here rather than inherited: `evidence_status` is `complete` when at least one world source reached the turn (injected ficha or a successful tool), `incomplete` when a tool was attempted and none succeeded, `none` when nothing was used — it describes the evidence, not the outcome; `status` is `completed`, `failed`, `disconnected` or `unknown`, and a non-completed turn gets `error_code = assistant.<close_reason>`.
- Wiring: `turn_started_at` before the semantic gate (so `gate_ms` covers the whole admission wait), tool notes inside the stream's `emit`, and the record built in the stream's `finally`, wrapped so a recording failure only logs. The SSE envelope, the prompts and the answers are untouched.
- Gap stated plainly: the **guided** turn (`/guided-character/turn`) is not instrumented yet; only the activity turn is. T1.4 is marked done for the activity path.
- Tests authored first (RED: collection `ModuleNotFoundError`, then three mapping failures that forced the evidence taxonomy to be written down), then GREEN: `test_assistant_turns.py` (16) covers the mapping, the tool cap, hashing, caps, unwritable storage and the model reader; one new end-to-end test in `test_per_flow_activation_api.py` drives the real activity endpoint and asserts the recorded turn (and that the world name never appears).
- Checks: focused batch 695 passed / 14 skipped (api_server, integration, attachments, semantic e2e, assistant activity, turns, ring); every module except the two installer ones 5227 passed / 26 skipped / 0 failed; manifest regenerated (195 payload files). The two installer modules remain the environmental 2 GiB disk gate.
- Route: inline. Risk: item 5 (a new module in the shipped payload). The assistant stream is the product's differentiator, which is why the batch above exercises every existing activity path, including the semantic end-to-end one, and no envelope changed.

**L19 (T1.5 diagnostics document and relay schema 3, commit `57e7b77`, 2026-11-24):** the report now carries what the app did, not only what it logged.

- `diagnostics.py`: reads the two bounded journals through `operations_ring.recent_operations` and `assistant_turns.recent_turns` (newest 50 operations / 20 turns), redacts every string value with `content_scan.redact_secrets`, and trims the globally oldest record until the serialized document fits `MAX_BYTES` = 24 KiB, setting `truncated` instead of cutting silently. `redacted_lines` is recomputed after trimming so it counts only placeholders that survived (verifier A1). The CLI (`python -m diagnostics --out PATH`) measures the INDENTED serialization it writes, so the manual file is bounded too (verifier A4).
- `bug_report.py`: the document is built SERVER-SIDE at delivery; a client-supplied `diagnostics` field stays outside `ALLOWED_FIELDS` and is rejected (test proves 400 and zero relay calls). `/assemble` also returns it. Relay ladder: first attempt `schema: 3` with diagnostics (and `context` when present); on a contract-rejection 4xx (400/413/415/422 only — 401/403/404/409/429 are not contract rejections) retry ONCE with the pre-diagnostics shape (`schema: 2` + context, or `schema: 1` without) and no diagnostics, answering `{"ok": true, ..., "diagnostics": "dropped"}`. 5xx, timeout, transport error and non-ok 2xx never retry: a duplicate report is worse than a missing payload. The retry shares the request, so it never spends a second rate-limit token (test pins five rejected-then-accepted submits inside one budget).
- `scripts/collect-diagnostics.sh` emits the identical `diagnostics.json` through the app's Python (`PYTHONPATH=<wiki> python -m diagnostics`), best effort: missing, non-executable or failing Python prints one skip line and the tarball is still produced under `set -eu`.
- Open question 1 stays open on the relay side: the app is ready for schema 3, and until the relay accepts it every report pays one rejected probe before the downgrade. Open question 5 resolved: yes, one format for both bundles.
- Tests authored before the implementation (RED: both modules failed collection with `ModuleNotFoundError: diagnostics`), then GREEN: `test_diagnostics.py` (12) and six relay-ladder tests plus the verifier's own six in `test_bug_report_router.py`. Focused set 127 passed; every module except the two installer ones 5241 passed / 26 skipped / 0 failed; manifest fresh (196 payload files); `bash -n` clean; CLI smoke produced the empty shape on this dev box.
- Independent verifier (`gentle-ai-verify`): S5 and S6 **MET** for T1.5, **no blockers**. Advisories taken: A1 (honest `redacted_lines`) and A4 (CLI file bounded by its own serialization), both with tests. Left as recorded: A2 (dict keys are not redacted — the writers only produce the fixed schema keys), A3 (a hand-edited journal is copied verbatim — the threat model is the app's own writers), A5 (a pathological pair of max-size journals can starve the operations list, which is the specified oldest-first policy). Relay-side acceptance of schema 3 is unverified until it is deployed.
- Route: delegated writer with the design above plus one independent verifier (the unit names a shared contract others consume: the relay schema). Risk: item 3 (the relay contract version) and item 5 (the shipped shell script and manifest).

**L20 (native RDD review of T1.2–T1.5, 2026-11-24):** assessed `high` (`process_boundary` + `shell_source` on `scripts/collect-diagnostics.sh`, 16 paths, 2623 lines) → review due. The Owner granted the candidate consent through the native envelope. Lineage `review-5dec151958d01dea`, target `sha256:1ad1c02b…3822e8bb`, range `f15ac2b..HEAD`, lenses `review-risk`, `review-resilience`, `review-reliability`.

- Admitted: `review-risk` and `review-reliability` (`admission_decision: completed`).
- `review-resilience` produced `opencode_task_output_empty` on the grouped launch AND on the one bound-STATUS relaunch the provider reoffered — the same deterministic host defect recorded in L13 for the previous lineage. Declared with the provider's own command (`review capture-unachievable --reason host_agent_output_empty`), which is the documented continuation for that slot.
- Outcome: `stop/unachievable_lens_slot` — the lineage is terminal with **no approval receipt**. No reduction ran, so the two admitted lenses' findings were never surfaced and no delivery was attempted; this is a host-side capture defect, not a verdict on the candidate.
- What the candidate still has as evidence: the independent verifier (`gentle-ai-verify`) returned S5/S6 **MET** with no blockers, and every module except the two installer ones runs 5241 passed / 26 skipped / 0 failed. The installer modules fail only on their 2 GiB free-disk gate.
- To obtain a native receipt the remaining route is a deliberately smaller candidate (a second review of `diagnostics.py` + `bug_report.py` alone with two lenses) or turning RDD off for this clone; both are the Owner's call, and neither is needed for correctness.

**L21 (re-review and advisory closure, 2026-11-24):** the Owner asked for the smaller re-review L20 proposed.

- New lineage `review-80d57c5c029bd812`, target `sha256:5e211a67…588f8d2d`, same range `f15ac2b..HEAD`, lenses `review-risk` + `review-reliability` (the two this host can capture; `review-resilience` was declared unachievable in the previous lineage). Consent granted through the native envelope.
- Both lenses admitted (`admission_decision: completed`); the reduction ran and the lineage is **approved**. Receipt acknowledged and authority burned (`gentle-ai.review-acknowledged/v1`). **No blockers**; five non-blocking findings.
- Closed in `7cd7be6`: R1-weak-world-hash (128 bits instead of 64, and the docstring stops over-claiming); R1-pattern-only-redaction (the document copies only the keys each journal schema defines, so an unknown key cannot smuggle world text); R3-001 (`logs.redacted_lines` counts the placeholders in the shipped content, not the ones the budget trimmed); R3-002 (the CLI budgets its trailing newline); R3-003 (the symlink and non-archive guards, including the `.rotating` leftover, are now tested).
- Checks after the fixes: focused 97 passed; every module except the two installer ones 5256 passed / 26 skipped / 0 failed; manifest fresh (196 payload files). The two installer modules remain the environmental 2 GiB disk gate.
- The lesson worth keeping: the host cannot capture `review-resilience`, so a three-lens candidate on this machine ends terminal without a receipt. Two lenses over the same range produced an approved receipt.

**L22 (T1.6 content policy, commit `413dbde`, 2026-11-25):** a report is metadata by default; author content travels only on an explicit opt-in.

- Unit: `content_scan.py` gains `CONTENT_PREVIEW_PLACEHOLDER`, `count_content_previews` and `redact_content_previews` — the rule replaces everything after a `preview=` field to the end of the line, keeps `len=`/session/timing/outcome, is idempotent, and ignores a plain `preview = obs.get(...)` assignment. The four writers that put author text into a log line are the gateway records (`api_server.py:12358, 12383, 12417, 12449`); a grep of the module and the launcher found no other one.
- `bug_report.py`: `_wants_content` reads `x-bugreport-content` (out of band, so `_deliver` still sends schema 3 with the same keys); `_apply_content_policy` is applied inside `_validate_and_cap`, so `/submit` AND `/fallback` enforce the policy on whatever the client posted — the caps are measured on the payload as sent, before scrubbing, so a scrub can never rescue an oversized payload. `_apply_content_policy` deliberately does NOT re-run `redact_secrets`: assemble already replaces a matching line whole and the public fallback body is scrubbed structurally with `scrub_all`, so re-redacting there would replace the fallback's `<email>`/`<hostname>` placeholders with whole-line redactions (it also keeps `test_fallback_scrubs_privacy_findings` honest).
- `/assemble` now answers `content_policy = {included, scrubbed_lines}`. `_assemble_logs` builds the window once, and only when the SHIPPED content still has a preview does it pay for `== content snippets included at the reporter's request ==`: it re-trims the joined content to `_LOGS_MAX_BYTES - len(marker)`; if that trim would drop the last payload it rebuilds metadata-only instead of shipping content without its label. `scrubbed_lines` is counted on the shipped text (`content.count(placeholder)`), the same rule `redacted_lines` already followed.
- Frontend: the opt-in is OFF by default and not persisted (a sticky preference would weaken "by default"); toggling re-assembles server-side, re-locks the mandatory preview gate, and a failed opt-in fetch reverts once to the metadata-only bundle instead of leaving the panel claiming content it does not have. The flag travels with submit and fallback; the card shows the omitted count or the included label; i18n in es/en.
- Route: inline (~840 changed lines, ~450 of them tests; splitting the policy from its proof would leave the report contract half-asserted). Risk: item 3 (what the report contract carries to an external relay and to the Owner) and item 5 (shipped payload/manifest).
- Checks: focused 139 passed; every module except the two installer ones 5275 passed / 26 skipped / 0 failed (those two remain the environmental 2 GiB disk gate: `install-demiurgos.sh` reports 2010272 KiB found); frontend 139 files / 1844 tests; `npm run typecheck`; `npm run build`; `derive_payload_manifest.py --check` fresh (196 files).
- Independent verifier (`gentle-ai-verify`): S5 **MET**, S6 **NOT MET** with blocker B1 — the marker's own 58-byte re-trim could orphan the label (`included: true` with no preview left) — plus A1: `scrubbed_lines` counted the working build, not the shipped text. Correction batch closed both; the narrow recheck reported B1 no longer reproduces (marker ⇔ content, `49153` bytes with preview and label) and A1 no longer overcounts (`scrubbed_lines == content.count("[content omitted]")`), with 400 randomized fixtures green and both durable probes now in `test_bug_report_router.py`.
- Advisories recorded: A2 a hand-made opt-in client posting `/submit` directly gets no marker (the label is a property of the server-assembled bundle; delivery still enforces the privacy default); A3 the `Hermes GW HTTP ...: resp.text` provider body and the `CRASH` line are not `preview=` fields (provider text, secret-redacted, bounded); A4 the log window carries real world names in API log lines although `diagnostics.json` hashes them (pre-existing; only relevant if S6's "world text" includes the name); A5 `_tail_window`'s `errors="replace"` can expand a multibyte cut, pre-existing at `0017017`, only for an unterminated multibyte line; A6 a hand-edited log line containing the literal marker makes a substring label check ambiguous (the app never writes it there).

**L23 (T1.7 test inventory, 2026-11-25):** Phase 1's exit gate is covered, and the inventory found two real gaps.

| Gate clause | Where |
|---|---|
| (a) the last log window after > 64 KB of logs | `test_bug_report_log_budget.py` (11): over-cap window, line boundary, archive order, total budget, redaction inside the window, byte-identical repeat |
| (b) the operations ring survives a crash | `test_operations_ring.py` (18): append/read across processes, world hashing, entry/byte caps, torn line, unwritable ring, kill switch, middleware rules |
| (c) the failing assistant turn | `test_assistant_turns.py` (16) + the end-to-end assertion in `test_per_flow_activation_api.py` |
| no endpoint can 500 on a bad source | `test_bug_report_router.py`: **two tests added in `413dbde`** — a raising `log_source` degrades to `included: false` / `log source unavailable`, and a raising `build_diagnostics` yields `{unavailable: true}` while the bundle still ships. Neither had a test before, although both code paths existed since T1.2/T1.5. |
| rotation, cap behaviour, kill switch | `test_log_rotation.py` (23) + `test_log_rotation_safety.py` (11) |
| redaction and the content policy | `test_content_scan.py` (22) + the T1.6 router tests |
| the bounded diagnostics document | `test_diagnostics.py` (13): schema keys, redaction, trimming, unknown-key denial, the CLI budget |

Phase 1 exit gate: **met** — a report produced after more than 64 KB of logs carries the last window, the operations ring and the failing turn, every clause above is pinned by a test, and the report path cannot 500 on a bad source. The relay still has to deploy schema 3 (open question 1); until then each report pays one rejected probe before the downgrade.

**L24 (RDD assessment of `0017017..b87e773`, 2026-11-25):** `gentle-ai review assess --base-ref 0017017 --committed-only` (untracked `.venv/` and `frontend/node_modules` declared `--untracked-scope=exclude`) → `risk: medium`, 11 changed paths / 1033 lines, reason `executable_change` on the runbook's bash block, `review_due: false`, `review_due_reason: under_budget`. No native review was started; the reviewed boundary stays at `0017017` until a later commit reaches the budget or the Owner asks for a review.

**L25 (T2.1 golden-set corpus format, commit `bef30c9`, 2026-11-25):** Phase 2 starts by pinning the format before any runner exists.

- Layout: `src/tools/demiurgos-suite/wiki/tests/fixtures/assistant-golden/` with `README.md` (contract), `labels.yaml` (closed levels and `must_not` codes with severity), `schema.json` (JSON Schema 2020-12 for a `cases.yaml` document plus the `worldDescriptor` definition), and `worlds/<slug>/`. The descriptor and cases sit at the world root on purpose: `EntityGraphIndex._scan_mundo` scans only `lore/`, `personajes/`, `referencias/`, so they are never treated as entities.
- World descriptor: `{name, description, source: fixture|data-root, language?}`. `fixture` worlds carry their fichas under the corpus (deterministic, CI-safe); `data-root` worlds resolve a real install for a release baseline.
- Case: `{id, level: C, question (verbatim), language?, source_paths[], expected_facts[{name, any_of[]}], must_not{codes[], strings[]}, notes?}`. Every fact group must match at least one `any_of`; at least one source path must be cited; blocking codes fail; wording is never asserted.
- Worked example: `worlds/example-chaart/` — a synthetic OKF world (one `lugar` ficha, one `personaje` ficha) and two cases (climate; founder+year) that demonstrate a single-fact and a two-fact case plus forbidden strings.
- Evidence: `schema.json` validates both `cases.yaml` and `world.yaml`; both fichas pass `okf_contract.validate` (`ok=true`, after adding the `personaje` `motivacion` minimum); `EntityGraphIndex.build("example-chaart")` returns exactly the two fichas and ignores `world.yaml`/`cases.yaml`; the schema rejects an invalid `level: Z`. `derive_payload_manifest.py --check` fresh (196 files): the corpus is a dev fixture and is not shipped.
- Route: inline. Risk: none — fixtures and docs only, no runtime path reads it and no shipped file changed. The runner is T2.2; the baseline is T2.3.

**L26 (RDD assessment of `0017017..HEAD` after T2.1, 2026-11-25):** `gentle-ai review assess --base-ref 0017017 --committed-only --untracked-scope=exclude --expected-untracked-inventory <digest>` (digest from selectorless STATUS) → `risk: medium`, 18 changed paths / 1400 lines, reason `executable_change` on `docs/architecture/assistant-runtime-runbook.md`, `review_due: false`, `review_due_reason: under_budget`. No native review started; the reviewed boundary stays at `0017017`. T2.1 added only fixtures and docs, so it did not move the tier.

**L27 (T2.2 golden-set runner, commit `ddf85a7`, 2026-11-25):** the runner exists and its logic is pinned; the live baseline is T2.3.

- `scripts/eval_assistant.py` (dev tool, stdlib + PyYAML, not in the payload): `--validate-only` validates each world's descriptor and cases against the same rules as `schema.json` and, for `source: fixture`, checks every `source_paths` ficha exists and passes `okf_contract.validate`; live mode probes `/capabilities` (the five required features), starts `POST /runs` per question and folds `/runs/{id}/events` into `(answer, tools, status)`.
- Evaluation: every `expected_facts` group matches at least one `any_of` (accent/case-insensitive), no `must_not.strings` appears, at least one `source_paths` is cited (full path or basename), language is an advisory marker heuristic, and `tool_evidence` records whether a graph tool succeeded. Semantic `invented_canon`/`claimed_authority`/`blind_answer`/`wrong_tone` become `judge:` flags — the runner never claims to judge them.
- Live-scope decision (D17): only `source: data-root` worlds by default, because a fixture world is not in the running gateway's `mundos`; `--allow-fixture-live` is the explicit override. The report goes to `odd/evidence/assistant-golden/<date>-<sha>.md` and omits answer text unless `--include-answers` (S6).
- Tests authored first (RED: the runner did not exist, 16 failures), then GREEN. `test_eval_assistant.py` (18) covers: normalize; pass/missing-fact/forbidden/uncited/basename-citation; multiple fact groups; language advisory; tool evidence; corpus digest stability; `validate_world` on the shipped example and on a bad level; `consume_events` (deltas + tools; terminal-only output); `evaluate_world` end-to-end with fake answers (one PASS, one FAIL); the report counts; and the `--validate-only` CLI on the example (exit 0) and a broken corpus (exit nonzero).
- Evidence: new tests 18 passed; `test_eval_assistant.py` + `test_assistant_graph_gate.py` 22 passed; `python3 scripts/eval_assistant.py --validate-only` → `OK example-chaart (2 cases, source=fixture)`, digest `5b5b397050d42ec9`; live mode against a dead gateway fails cleanly with "gateway unreachable … start Demiurgos first"; whole suite collects 5547 tests with no errors; `derive_payload_manifest.py --check` fresh (196 files) — the runner is not shipped.
- Route: inline. Risk: none — a new dev tool plus its test, no shipped file and no runtime path changed.

**L28 (RDD assessment of `0017017..HEAD` after T2.2, 2026-11-25):** `gentle-ai review assess --base-ref 0017017 --committed-only --untracked-scope=exclude --expected-untracked-inventory <digest>` → `risk: high`, reason `process_boundary` on `scripts/eval_assistant.py` (signal `shell_process`), 20 changed paths / 2437 lines, `review_due: true`, `review_due_reason: high_risk`. The signal comes from the runner's `subprocess.run(["git", "rev-parse", ...])` (fixed argv, no user input) and its urllib transport; it is a read-only dev tool and not shipped. RDD is on (`default`), so a native review is due for this candidate: pending the Owner's decision to run it now (2 lenses `review-risk` + `review-reliability`, avoiding the host's deterministic `review-resilience` capture defect) or to continue to T2.3 and review at the feature boundary before publishing.

**L29 (native RDD review of T2.1–T2.2, 2026-11-25):** the Owner ran the native review on the committed slice.

- Consent given through the native envelope; lineage `review-9a26e030d6cedcad`, target `sha256:2f14df9f…967c1d`, committed range `0017017..ab29b87` (20 paths / 2439 lines), lenses `review-risk` + `review-reliability` (avoiding the host's deterministic `review-resilience` capture defect). Untracked `.venv/`/`node_modules` excluded via `--untracked-scope=exclude` + the canonical inventory digest.
- Both lenses admitted (`admission_decision: completed`); state **approved**; receipt acknowledged and authority burned (`gentle-ai.review-acknowledged/v1`, `consumed_revision sha256:d5c731c5…`, `authority: burned`). **No blockers.**
- Six non-blocking advisories (later work, never a reason to re-run this candidate): R1-cleartext-key (WARNING — the runner sends the gateway key over the resolved base URL with no plaintext warning and echoes the base URL into the report), R1-sourcepath-traversal (SUGGESTION — `validate_world` joins `source_paths` without containment), R3-001 (WARNING — the per-case `--timeout` is enforced only when `iter_sse` yields, so a stream that never completes an event can hang), R3-002 (WARNING — blocking `must_not` codes stay `judge:` flags and do not fail the case or `--fail-on-fail`, which contradicts the corpus "blocking codes fail" wording), R3-003 (SUGGESTION — live `load_world` is unguarded, so malformed YAML aborts the run), R3-004 (SUGGESTION — the live transport is untested).
- The runbook/docs content in the same candidate (T1.6/T1.7 rotation-and-content sections) was reviewed as part of the slice and produced no findings.
