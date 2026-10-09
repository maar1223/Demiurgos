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

`provision_test_profile(root, repo_root)` writes `<root>/config.yaml` with three
effects, each through an idempotent writer that preserves every other key:

| Effect | Key | Requirement |
|--------|-----|-------------|
| Plugin opt-in | `plugins.enabled` contains `demiurgos-idea-capture` | REQ-TPP-1 |
| Skills toolset | `platform_toolsets.api_server` includes `skills` | REQ-TPP-2 |
| External skills dir | `skills.external_dirs` includes `resolve_skills_dir(repo_root)` | REQ-TPP-3 |

Re-running the recipe is a no-op: the file stays byte-identical when all three
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

Result: `<PROFILE_ROOT>/config.yaml` carrying the three effects above.

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
expected log path drifted. It never reports a pass it did not observe.

```bash
DEMIURGOS_PROBE_LIVE=1 \
DEMIURGOS_HERMES_HOME=/tmp/opencode/hermes-test-profile-closure \
.venv/bin/python -m pytest \
  src/tools/demiurgos-suite/wiki/tests/test_native_channel_probe.py -q
```

When it runs, the probe boots the real gateway, reads hook-registration evidence
from `<HERMES_HOME>/logs/agent.log` from a boot offset, and asserts:

- **(a)** both `pre_tool_call` and `pre_llm_call` registered — live evidence;
- **(c)/(d)** in-process cache-clear and `skill_manage` veto — live evidence;
- **(b)** `skills` present in `platform_toolsets.api_server` and the owned skills
  folder in `skills.external_dirs` — config-level evidence.

Condition **(b) at the model level** (a real assistant turn loading native
skills) requires credentials and remains explicitly deferred; the probe records
it as deferred and never claims a model-level pass.
