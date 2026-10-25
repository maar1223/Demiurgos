# assistant-provider-compatible — the Assistant runs the provider Demiurgos saved

Branch: `fix/assistant-provider-compatible` (base `origin/master` @ 7d85766c). Delivery: `ask-on-risk`.
Test runners: `pytest` from `src/tools/demiurgos-suite`; `cd frontend && npm test` (untouched by this fix).

## Specs

### S1 — Hermes-resolvable provider ids

Every save that writes the active Hermes profile's `model:` block writes a provider id the installed Hermes runtime resolves. The Demiurgos provider vocabulary is translated on write:

| Demiurgos id (normalized block, UI) | Hermes `model.provider` |
|---|---|
| `opencode-go` | `opencode-go` |
| `openrouter` | `openrouter` |
| `openai` | `custom` |
| `compatible` | `custom` |
| `ollama` | `ollama` |
| `lm-studio` | `lmstudio` |

`openai` and `compatible` map to Hermes `custom` because that is the Hermes identity for an OpenAI-compatible chat-completions endpoint — the same transport the two Demiurgos probes validate — while Hermes' native `openai-api` identity forces the Responses transport (`codex_responses`) that Demiurgos never probed. `lm-studio` maps to Hermes' canonical `lmstudio` (Hermes accepts `lm-studio` as an alias, but the canonical id is written). For `api.openai.com` Hermes host-mandates the Responses transport itself; that is the runtime's contract, not a Demiurgos promise.

### S2 — The secret reaches the runtime without landing in config.yaml

For a `compatible` endpoint the model block carries `api_key: ${ASSISTANT_PROVIDER_API_KEY}`, the env var Demiurgos already writes to the profile `.env` (mode 600), so Hermes resolves the stored secret at config load. The secret itself is never inlined in `config.yaml`. The other mappings need no reference: `openai` relies on Hermes' host-gated `OPENAI_API_KEY`, and the native providers read their own env vars.

### S3 — The product vocabulary is preserved

The normalized `assistant_settings` block keeps the Demiurgos provider id (`provider: compatible`, ...), so the panel, the vision gate (`import_vision`, `chat_vision`) and the key-env lookup continue to see the product provider after the config is rewritten. Only the `model:` block carries the Hermes id.

### S4 — Only Demiurgos-owned keys are rewritten

A managed `api_key` reference (`${ASSISTANT_PROVIDER_API_KEY}`) is added when saving a `compatible` endpoint and removed when a later save (or a key clear) moves away from it. Any other `model.api_key` value is preserved untouched, including on a keyless save; only a save that supplies a new secret replaces it (explicit input wins). `default`, `provider` and `base_url` keep their existing replace semantics.

### S5 — Acceptance is a real run, not gateway liveness (and it converges)

A save reports `runtime_state: "active"` only when one bounded real Hermes run — `POST /v1/runs` with a tiny prompt, then `GET /v1/runs/{id}` polled to a terminal state — finishes `completed` with a non-empty output. Gateway reachability alone (`gateway_state.json` + live PID) is no longer acceptance: it becomes `saved-not-active`, exactly like an unreachable gateway. A failed, cancelled, empty, unreachable or timed-out run is `saved-not-active` and never records an acceptance. The run is bounded (default 20 s deadline, 8 s per request) and every failure path fails closed. The recorded acceptance, and therefore the readiness badge, can only become `accepted` through that real run. A non-accepted acceptance recorded for the CURRENT revision is re-evaluated once at startup (up only: the recorded text+vision proofs, a live gateway and one completed run), so a revision saved while the runtime was not ready converges to `active` after a restart instead of lying forever; an accepted revision is never downgraded nor re-probed.

### S6 — Checked, documented, and honest

The mapping, the reference lifecycle and the run probe are covered by deterministic tests that use injected transport/clock seams (no network). The onboarding contract documents the persisted mapping (`docs/architecture/onboarding-and-configuration.md`, 6.1) and the full backend suite stays green.

### Assumptions (not requested verbatim; Owner may overturn)

- A1: `openai` is mapped to `custom` (chat completions) instead of Hermes' native `openai-api` (Responses), because only chat completions is what Demiurgos validated.
- A2: one small real model call per explicit save is an acceptable cost for a truthful acceptance; no periodic probing is added.
- A3: the acceptance probe uses a stable session id (`demiurgos-acceptance`) so repeated saves do not spawn a new Hermes session each time.

### Out of scope

- Auto-healing an already-written `provider: compatible` config on read/startup (the Owner re-saves once after this fix; a startup mutation of the user's profile is out of scope).
- Native RDD review (the RAR authority rejects this FUSE/NTFS Git common dir; see the Log).
- Frontend copy or provider list changes.

## Tasks

- [x] T1 — Provider mapping + managed `api_key` reference in `assistant_settings` (`S1`-`S4`). Commit `520a1f72`.
- [x] T2 — `HermesRunProbe` module + unit tests (`S5`). Commit `89c2f762`.
- [x] T3 — Wire the run probe as save-time acceptance + router tests (`S5`). Commit `c585b43d`.
- [x] T4 — Docs, full suite, verification (`S6`). Commit (docs).

## Log

**L1 (Owner, verbatim):** `vayamos con esto bug/assistant-provider-compatible (#3816)`

**L2 — Prior analysis carried over (Engram `#3816`, topic `bug/assistant-provider-compatible`), next-session steps verbatim:**

> 2. Decide the Hermes-known provider value (or register the alias) and align assistant_settings normalization + persisted block.
> 3. Add a real end-to-end readiness probe (one small run) instead of gateway-liveness-only acceptance.
> 4. Re-test text and image chat after the fix.

**L3 — Recorded evidence (same observation):** the live profile had `model.provider: compatible`, `assistant_settings.provider: compatible`, `model_id: deepseek-flash`, `revision: 35`; the gateway accepted `POST /v1/runs` with 202 and streamed events, but `GET /v1/runs/{id}` answered `status=failed`, `error="Provider authentication failed: Unknown provider 'compatible'. Check 'hermes model' for available providers, or run 'hermes doctor'."`. `hermes doctor` confirmed `model.provider 'compatible' is not a recognised provider`. The image upload worked because `chat_vision` calls `https://api.deepseek.com` directly with the stored key, bypassing Hermes provider resolution.

**L4 — Repository evidence (2026-10-24, Hermes 0.21.1 installed at `~/.hermes/hermes-agent`):**
- `hermes_cli/auth.py:1397 resolve_provider` raises `AuthError("Unknown provider '…'")` unless the name is `openrouter`, `custom`, or a `PROVIDER_REGISTRY` key. Empirically: `compatible` → error, `openai` → error (it is a models.dev alias of `openrouter` and `resolve_provider` checks the raw name), `custom` → ok, `opencode-go` → ok, `openrouter` → ok, `ollama` → `custom`, `lm-studio` → `lmstudio`.
- `hermes_cli/runtime_provider_backends.py:112 _resolve_openrouter_runtime` serves bare `custom`: it trusts `model.base_url` when `model.provider` is `custom`, and reads the key from `model.api_key` (inline or `${VAR}`) or host-gated env keys. Empirically, with a temp `HERMES_HOME`, `provider: custom` + `base_url` + `api_key: ${ASSISTANT_PROVIDER_API_KEY}` resolved to `provider=custom`, `api_mode=chat_completions`, `api_key=sk-…` once the var was in the environment; without the ref it resolved to `api_key='no-key-required'` and would 401.
- `hermes_profile_config.merge_model_provider` is only used by the test-profile provisioner, not by the product save path; `assistant_settings._set_model_config_content` is the single writer of the live `model:` block.
- `_status_from_config` prefers the normalized `assistant_settings.provider`, so the product id survives on the read path.

**L5 — Decision:** map `openai`/`compatible` to Hermes `custom` (chat completions, the transport both probes validate) rather than `openai-api` (Responses); keep the normalized block as the product vocabulary; reference the existing `.env` secret from `model.api_key` instead of inlining it.

**L6 — T1 implementation evidence (2026-10-24):**
- `assistant_settings._HERMES_PROVIDERS` maps the six product ids; `_set_model_config_content` now writes the mapped id, accepts an owned `model.api_key` reference and drops only that owned reference (`${ASSISTANT_PROVIDER_API_KEY}`) when the provider no longer needs it. Any foreign `api_key` is preserved.
- `DELETE /configuration/key` also releases the owned reference.
- Tests: `TestHermesProviderMapping` (6 parametrized mappings + switch-away + key-clear + foreign-key preservation) plus the updated `test_model_update_preserves_non_legacy_provider_fields`. `test_assistant_settings.py` 64 passed at that point.
- Verified against the installed Hermes 0.21.1 in a temp `HERMES_HOME`: `provider: custom` + `base_url` + `api_key: ${ASSISTANT_PROVIDER_API_KEY}` resolves to `provider=custom`, `api_mode=chat_completions` with the real secret; without the reference it resolves to `no-key-required`.

**L7 — T2/T3 implementation evidence (2026-10-24):**
- `hermes_run_probe.HermesRunProbe`: POST `/v1/runs` + poll `GET /v1/runs/{id}`, bounded by a deadline (25 s default, 0.5 s poll), accept only `completed` with non-empty `output`; 13 unit tests with an injected transport/clock.
- Router: new `runtime_probe` injection; when present it is the only acceptance observation (one call), a raised error fails closed. `api_server` wires `_assistant_runtime_run_probe()` (gateway base from `HERMES_GATEWAY_URL`, bearer from `HERMES_GATEWAY_KEY`).
- Tests: `test_save_uses_the_real_run_probe_for_acceptance` (liveness tripwire, True/False) and `test_run_probe_exception_fails_closed`; wiring tests assert the api_server seam uses the configured gateway and fails closed.
- Targeted suites: `test_assistant_settings.py` + `test_hermes_run_probe.py` 79 passed; `test_api_server.py`, `test_readiness.py`, `test_hermes_runtime_probe.py`, `test_import_vision.py`, `test_assistant_provider_adapters.py`, `test_hermes_profile_config.py`, `test_assistant_activity.py` 639 passed.

**Risk (feature):** item 3 — the persisted Hermes `model:` contract changes (provider identity plus an owned `api_key` reference). Delivering the fix requires the Owner to re-save the assistant configuration once so the already-written `provider: compatible` is replaced; startup auto-healing of a broken profile was deliberately left out of scope.

**L8 — Live-resolution proof (2026-10-24):** taking the LIVE `~/.hermes/config.yaml` (provider `compatible`, model `deepseek-flash`, base_url `https://api.deepseek.com`, key in the profile `.env`) and applying only this fix's `_set_model_config_content` in a throwaway `/tmp` `HERMES_HOME` (config + a copy of the profile `.env`, 600, removed afterwards), the installed Hermes 0.21.1 resolved `provider=custom`, `api_mode=chat_completions`, `base_url=https://api.deepseek.com`, and the real 35-character key from the `.env` (not the `${ASSISTANT_PROVIDER_API_KEY}` literal). The already-running gateway still serves the old config, so the Owner's live re-save after restarting the app is the remaining step.

**L9 — Full-suite evidence (2026-10-24):** CI's backend command (ignore list + `-k "not live"`) → 3939 passed, 2 failed (`test_gateway_hooks::test_cache_safe_returns_false_when_modules_absent`, `...fallback_to_plain_prompt_builder`) — the known order-dependent pair, 51/51 green when run in isolation. `test_payload_boot` initially failed because the new module was missing from the payload allow-list; `scripts/derive_payload_manifest.py` regenerated it (163 payload files) and the four boot tests pass.

**L10 — Independent verification (2026-10-24):** `gentle-ai-verify` returned MET for S1, S2, S3, S5 and S6 and one change-caused blocker on S4: a *keyless* `compatible` save replaced a foreign inline `model.api_key` with Demiurgos' reference (baseline preserved it). Advisories: the feature doc's "custom = chat completions" rationale is false for `api.openai.com` (Hermes host-mandates Responses), and the probe's worst wall time was ~45 s. Correction batch: `_set_model_config_content` now replaces a foreign `api_key` only when the save supplies a new secret (`replace_foreign_api_key`), the rationale was corrected in the spec and the onboarding doc, and the probe tightened to a 20 s deadline / 8 s per request. The verifier's probe set was committed as `wiki/tests/test_assistant_provider_contract.py` (13 tests; its S4 cases failed on the pre-correction candidate). Recheck: focused + related suites 657 passed. The verifier also confirmed the two `test_gateway_hooks` failures do not reproduce under its isolated run (3931 passed, 0 failed) and pass at the baseline.

**L11 — Final full-suite run (2026-10-24):** CI's backend command → **3951 passed, 2 failed** (`test_gateway_hooks` order-dependent pair; 51/51 green in isolation together with `test_system_control`), 31 deselected. `test_payload_audit`'s signature-gate tests briefly failed because `/tmp` sat at 99% (the installer's 2 GiB gate); removing the verifier's 1.5 GB scratch and the old pytest temp dirs restored 3.1 GiB and the 55 tests passed. No workspace scratch was left behind.

**L16 — Acceptance convergence (2026-10-25):** the Owner reported that after restarting Demiurgos the panel showed a working assistant as inactive. Root cause: the save-time acceptance is recorded once and the resolver treats it as authoritative, so a revision saved while the runtime was not ready kept `saved-not-active` forever. `api_server._converge_assistant_acceptance()` now runs once at startup (daemon thread, off the boot path): it requires the current revision's `text=passed`/`vision=passed` evidence, a live gateway and one completed real run, and upgrades only `runtime` to `accepted`; it never downgrades nor re-probes an accepted revision, so a transient provider failure cannot flip a working assistant to inactive. Tests: `test_assistant_acceptance_convergence.py` (8 cases, including a failed probe leaving the evidence untouched, a down gateway never probing, and the bounded wait for a gateway that comes up a few seconds after the API).

**L17 — Convergence race (2026-10-25, after the 23:02 restart):** the first convergence attempt ran 16 s before the gateway wrote `gateway_state.json`, saw it down and returned silently, so the badge still said "sin verificar". The startup convergence now waits for the gateway in a bounded loop (90 s, 3 s steps) before the single probe; the wait is injectable and pinned by a test with a fake clock and a gateway that reports down twice then up.
