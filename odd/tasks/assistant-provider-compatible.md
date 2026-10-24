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

`openai` and `compatible` map to Hermes `custom` because that is the Hermes identity for an OpenAI-compatible chat-completions endpoint — the same transport the two Demiurgos probes validate — while Hermes' native `openai-api` identity forces the Responses transport (`codex_responses`) that Demiurgos never probed. `lm-studio` maps to Hermes' canonical `lmstudio` (Hermes accepts `lm-studio` as an alias, but the canonical id is written).

### S2 — The secret reaches the runtime without landing in config.yaml

For a `compatible` endpoint the model block carries `api_key: ${ASSISTANT_PROVIDER_API_KEY}`, the env var Demiurgos already writes to the profile `.env` (mode 600), so Hermes resolves the stored secret at config load. The secret itself is never inlined in `config.yaml`. The other mappings need no reference: `openai` relies on Hermes' host-gated `OPENAI_API_KEY`, and the native providers read their own env vars.

### S3 — The product vocabulary is preserved

The normalized `assistant_settings` block keeps the Demiurgos provider id (`provider: compatible`, ...), so the panel, the vision gate (`import_vision`, `chat_vision`) and the key-env lookup continue to see the product provider after the config is rewritten. Only the `model:` block carries the Hermes id.

### S4 — Only Demiurgos-owned keys are rewritten

A managed `api_key` reference (`${ASSISTANT_PROVIDER_API_KEY}`) is added when saving a `compatible` endpoint and removed when a later save (or a key clear) moves away from it. Any other `model.api_key` value is preserved untouched; `default`, `provider` and `base_url` keep their existing replace semantics.

### S5 — Acceptance is a real run, not gateway liveness

A save reports `runtime_state: "active"` only when one bounded real Hermes run — `POST /v1/runs` with a tiny prompt, then `GET /v1/runs/{id}` polled to a terminal state — finishes `completed` with a non-empty output. Gateway reachability alone (`gateway_state.json` + live PID) is no longer acceptance: it becomes `saved-not-active`, exactly like an unreachable gateway. A failed, cancelled, empty, unreachable or timed-out run is `saved-not-active` and never records an acceptance. The run is bounded (default 25 s) and every failure path fails closed. The recorded acceptance, and therefore the readiness badge, can only become `accepted` through that real run.

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

- [ ] T1 — Provider mapping + managed `api_key` reference in `assistant_settings` (`S1`-`S4`).
- [ ] T2 — `HermesRunProbe` module + unit tests (`S5`).
- [ ] T3 — Wire the run probe as save-time acceptance + router tests (`S5`).
- [ ] T4 — Docs, full suite, verification (`S6`).

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
