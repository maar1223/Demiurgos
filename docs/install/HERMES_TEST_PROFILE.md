# Hermes test-profile provisioning

This recipe provisions a **dedicated** `HERMES_HOME`-layout test profile for the
opt-in live gateway probe. It is reusable, idempotent, and **P0-8 safe**: it
refuses the personal `~/.hermes` profile and writes only under the root you
request.

The provisioning path is implemented by
`src/tools/demiurgos-suite/wiki/hermes_profile_config.py::provision_test_profile`
(change `hermes-probe-closure`, WU-3). The live-probe harness that consumes the
profile is `src/tools/demiurgos-suite/wiki/tests/hermes_probe_support.py`.

## What provisioning writes

`provision_test_profile(root, repo_root)` writes `<root>/config.yaml` with five
effects, each through an idempotent writer that preserves every other key:

| Effect | Key | Requirement |
|--------|-----|-------------|
| Plugin opt-in | `plugins.enabled` contains `demiurgos-idea-capture` | REQ-TPP-1 |
| Skills toolset | `platform_toolsets.api_server` includes `skills` | REQ-TPP-2 |
| External skills dir | `skills.external_dirs` includes `resolve_skills_dir(repo_root)` | REQ-TPP-3 |
| Telegram-free boot | `platforms.telegram.enabled: false` | REQ-TPP-6 |
| Observable hooks | `logging.level: DEBUG` | REQ-LPH-8 |

The `platforms.telegram.enabled: false` write makes the profile boot without a
bot token: a missing telegram token is a non-retryable startup conflict that
exits the gateway `78`, and the explicit-disable marker wins over environment
credentials. The `logging.level: DEBUG` write raises the dedicated profile's
`agent.log` so the gateway's hook-registration lines (DEBUG-only) become
observable — no other log level exposes them.

Re-running the recipe is a no-op: the file stays byte-identical when all five
keys are already present.

## P0-8 safety

Provisioning resolves the requested root and compares it against the personal
`~/.hermes`. If they match it raises `ProfileProvisioningError` and writes
nothing. The live probe applies the same predicate independently (as
`assert_not_personal_profile`) — pointing either at the personal profile is a
hard failure, never a skip and never a pass.

## Recipe

Run from the repository root. `<PROFILE_ROOT>` must be a dedicated directory
(use a throwaway path such as `/tmp/opencode/hermes-test-profile-closure`), and
`<REPO_ROOT>` is the checkout root.

```bash
PYTHONPATH=src/tools/demiurgos-suite/wiki .venv/bin/python -c \
  "from hermes_profile_config import provision_test_profile; \
   provision_test_profile('<PROFILE_ROOT>', '<REPO_ROOT>')"
```

Result: `<PROFILE_ROOT>/config.yaml` carrying the five effects above.

## Gateway env / CWD source of truth

The profile is only meaningful because the live probe boots the gateway with the
same project-plugin contract the product uses. `scripts/start-demiurgos.sh:480-484`
is the authoritative source for that contract:

- `cwd` = the repository root (so `Path.cwd()/.hermes/plugins` resolves);
- `HERMES_ENABLE_PROJECT_PLUGINS=1` (opts project plugins in);
- `DEMIURGOS_ROOT=<repo root>`.

The shared live-probe helper mirrors those exactly and additionally sets both
`HERMES_HOME` and `DEMIURGOS_HERMES_HOME` to the dedicated profile root.

## Run the opt-in live probe

The probe is opt-in and honest: it skips (with the named reason) when the opt-in
is unset, `hermes` is not on `PATH`, the profile is not provisioned, or the
gateway never created the log directory **after** boot (log-path drift). A
missing log directory **before** boot is not drift — the gateway creates it on
boot — so a fresh profile is probed normally. It never reports a pass it did not
observe.

```bash
DEMIURGOS_PROBE_LIVE=1 \
DEMIURGOS_HERMES_HOME=/tmp/opencode/hermes-test-profile-closure \
.venv/bin/python -m pytest \
  src/tools/demiurgos-suite/wiki/tests/test_native_channel_probe.py -q -rs
```

When it runs, the probe boots the real gateway, reads hook-registration evidence
from `<HERMES_HOME>/logs/agent.log` from a boot offset, and asserts:

- **(a)** both `registered hook: pre_tool_call` and `registered hook: pre_llm_call`
  logged by the gateway (requires the DEBUG-provisioned profile) — live evidence;
- **(c)/(d)** in-process cache-clear and `skill_manage` veto — live evidence;
- **(b)** `skills` present in `platform_toolsets.api_server` and the owned skills
  folder in `skills.external_dirs` — config-level evidence.

If the DEBUG `registered hook:` markers are absent (for example a managed scope
pins the log level to INFO), the probe fails loudly with the observed gateway
return code — never a false pass.

## Model-level (b) proof (real assistant turn)

Condition **(b) at the model level** — a real assistant turn proves the model
sees/loads native skills — is a credential-gated capability. With operator
credentials and the gate env var `DEMIURGOS_MODEL_LIVE=1` the probe drives one
real turn through the gateway api_server; without them it produces an **honest
named skip** and stays deferred — it never claims a model-level pass it did not
observe, and it never fails on the absence of credentials.

### Provision a model-turn profile

`provision_model_turn_profile` reuses the five-writer recipe above and adds the
`model:` block plus a **real tracked skill seed** (`narrative-design`, copied
into `<PROFILE_ROOT>/skills-seed/` and registered in `skills.external_dirs`).
The owned registered skills folder is empty by design (only `SkillPromoter`
fills it, and promotion is gated on a passed probe — circular), so the seed is
what makes the turn meaningful without promotion and without a world-flag flip.

```bash
PYTHONPATH=src/tools/demiurgos-suite/wiki .venv/bin/python -c \
  "from hermes_profile_config import provision_model_turn_profile; \
   provision_model_turn_profile('<PROFILE_ROOT>', '<REPO_ROOT>', \
     provider='opencode-go', model='deepseek-v4.1-flash', \
     base_url='https://opencode.ai/zen/go/v1')"
```

Provisioning writes **no credential**. The operator supplies the keys
**home-scoped**: via export or `<PROFILE_ROOT>/.env`. The dedicated profile
does **NOT** inherit the personal `~/.hermes/.env` (P0-8) — a key exported
there does not count.

- `OPENCODE_GO_API_KEY` — the provider secret resolved by the `model:` block.
- `OPENCODE_GO_BASE_URL` — optional override of the provider base URL.
- `API_SERVER_KEY` — the api_server bearer key, **≥ 16 characters** (the
  gateway's own `has_usable_secret(min_length=16)` strength guard).

### Run the gated model-level proof

```bash
DEMIURGOS_MODEL_LIVE=1 \
DEMIURGOS_HERMES_HOME=/tmp/opencode/hermes-test-profile-closure \
OPENCODE_GO_API_KEY=<key> API_SERVER_KEY=<16+ chars> \
.venv/bin/python -m pytest \
  src/tools/demiurgos-suite/wiki/tests/test_native_channel_probe.py \
  -k model_level -q -rs
```

The test is **opt-in and honest** — it skips with the exact named reason when
the gate is off, `hermes` is missing, the profile is not provisioned, no
provider credential is resolvable, or `API_SERVER_KEY` is unset. A present but
too-short `API_SERVER_KEY`, a provider error (e.g. a recorded `rate_limit`), or
a turn yielding no evidence **fails loudly** — never a false pass.

**Evidence meaning** (permissive disjunction, because an LLM turn is
nondeterministic): model-level (b) passes when **either** the reply names the
seeded skill (`narrative-design`) **or** a `skills_list`/`skill_view` tool call
appears in the `hermes.tool.progress` trace. A live turn may fail even with a
valid key (provider rate limits, model errors) — that is a loud fail, never a
pass.

The run also executes a **deterministic prompt-assembly sub-check** that
composes the profile's `## Skills` / `<available_skills>` block via the
installed runtime's `build_skills_system_prompt()` and asserts it names the
seeded skill. This is explicitly **non-turn evidence**: it proves the skill is
composable into the prompt, and it never substitutes for the model-level turn.
