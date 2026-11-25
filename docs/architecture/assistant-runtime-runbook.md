# Assistant runtime runbook

Operational reference for the product-owned Hermes runtime that Demiurgos ships:
the pin policy that keeps it frozen, where every moving part lives, and the
repair procedures for the four failures the assistant can present today (gateway
down, pin mismatch, broken provisioning, unusable configuration), plus how to
read a report bundle.

Scope: an installed Demiurgos (`$HOME/.demiurgos` by default) and a development
checkout. All procedures are read-only until a step explicitly says otherwise.
Nothing here touches the author's personal `~/.hermes` or world data.

Related: `odd/tasks/hermes-core-runtime.md` (why the fork exists),
`odd/tasks/assistant-runtime-evolution.md` (S8, S11),
`docs/architecture/ASSISTANT_WORLD_READING.md` (what "the assistant works"
means), `docs/install/ONE_SCREEN_GUIDE.md` (user-facing install).

---

## 1. What "the runtime" is

Demiurgos does not run upstream Hermes. It runs a **pinned fork** installed under
its own product root, so an upstream release can never change the product
silently:

| Fact | Value |
|---|---|
| Fork | `https://github.com/maar1223/hermes-agent-demiurgos.git` |
| Pin | `d046ff9905b8470c4a0cfd5e9da566986056b438` |
| Patch carried by the fork | `tool_choice: "none"` support (empty toolset), used by one-shot calls |
| Verified at install time | the pinned **tree** contains `no_tools` in `gateway/platforms/api_server.py`, not merely the branch history |
| Provisioner | `scripts/provision-hermes.sh` (idempotent, `--check` for read-only diagnosis) |

Layout under the install root (`$DEMIURGOS_HOME`, default `$HOME/.demiurgos`):

| Path | What it is |
|---|---|
| `<root>/current` | symlink to the active app version |
| `<root>/app/<version>` | installed application payloads |
| `<root>/hermes-agent` | the pinned git checkout of the runtime |
| `<root>/hermes-agent/.hermes/bin/hermes` | the runtime entry point the launcher invokes |
| `<root>/hermes` | `HERMES_HOME`: dedicated profile (skills, tools store) |
| `<root>/hermes/config.yaml` | the assistant provider/model configuration |
| `<root>/hermes/.env` | the runtime environment (`API_SERVER_ENABLED=true`, provider keys) |
| `<root>/hermes/tools` | `HERMES_RUNTIME_DIR` (tool store) |
| `<root>/logs` | `launcher.log`, `demiurgos-api.log`, `demiurgos-gateway.log` |
| `<root>/bin/demiurgos` | installed launcher wrapper (`start`, `restart`, `stop`, `restart-assistant`, `install`) |
| runtime state dir (`$XDG_RUNTIME_DIR` / `$TMPDIR` / `~/.cache/demiurgos/runtime` + `/demiurgos-launcher`) | launcher pid files and `gateway-supervisor.json` |

The runtime checkout is rebuilt from the pin by the provisioner. **Never edit
`<root>/hermes-agent` in place**: the next provisioning replaces it, and a
locally drifted checkout is not reproducible on another machine.

---

## 2. Pin policy (fork freeze, S8)

1. **The pin does not move because upstream moved.** A release, a refactor, or a
   new feature upstream is not a reason. It stays until a Demiurgos feature
   genuinely requires a commit that does not exist in the pinned tree.
2. **One reason per move.** The commit that bumps the pin names the product
   feature that needs it, and records expected-vs-found in that feature's ODD
   document.
3. **The bump is verified, not trusted.** A pin bump must: fetch the new commit
   into a staging directory, prove the `no_tools` patch is still in the tree,
   update `HERMES_PIN` in `scripts/provision-hermes.sh` (and any test that pins
   it), keep the launcher contract tests green, and pass the assistant wiring
   gate (§8).
4. **Rollback is the previous pin.** Bumping the pin backwards to the last
   provisioned commit is always allowed; the provisioner moves the previous
   checkout aside as `<root>/hermes-agent.previous-<timestamp>` instead of
   deleting it.

Rationale (verified evidence, `odd/tasks/hermes-core-runtime.md`): the fork
exists for exactly one patch. Past pin moves produced (a) a merge conflict in
`gateway/platforms/api_server.py`, the same file that carries the patch, and (b)
a new upstream trust check on bare `custom` base URLs that can reject the
provider base URL the assistant settings write. Both classes of breakage arrive
with an upstream bump and with nothing changing in Demiurgos.

Environment overrides exist only as test seams and for hermetic installers:
`DEMIURGOS_HERMES_FORK_URL`, `DEMIURGOS_HERMES_PIN`,
`DEMIURGOS_HERMES_SKIP=1`. An override that differs from the shipped pin makes
the install non-reproducible; treat it as temporary.

---

## 3. Health checks (read-only, do these first)

Run these before any repair step; they separate "the app is down" from "the
assistant is down".

```bash
# 1. The API: Demiurgos itself is alive.
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8000/health

# 2. The runtime pin: exit 0 means provisioned at the pin with a usable launcher.
<root>/current/scripts/provision-hermes.sh --check

# 3. The pin actually checked out.
git -C <root>/hermes-agent rev-parse HEAD

# 4. The gateway process and its port (default 8642).
python3 -c "import socket;s=socket.create_connection(('127.0.0.1',8642),2);print('open')"

# 5. The app's own view: Perfil -> Asistente reports gateway_running, and the
#    assistant sidebar shows the localized health banner when it is false.
```

Launcher state (pid files plus the gateway supervisor snapshot) lives outside
the install root, in the per-user runtime dir:
`${XDG_RUNTIME_DIR:-${TMPDIR:-${XDG_CACHE_HOME:-$HOME/.cache}/demiurgos/runtime}}/demiurgos-launcher`
(default `~/.cache/demiurgos/runtime/demiurgos-launcher`). Ports are overridable
with `DEMIURGOS_API_PORT` / `DEMIURGOS_GATEWAY_PORT`.

The gateway child is wrapped by the product supervisor
(`gateway_supervisor.py`), so `gateway.pid` holds the supervisor, not the
runtime. The supervisor keeps `gateway-supervisor.json` next to it:

```json
{"schema":"demiurgos.gateway-supervisor/v1","state":"running|starting|restarting|failed|stopped",
 "cause":null|"not_started"|"exited"|"config_invalid","attempts":0,"max_attempts":3,
 "last_exit_code":null,"last_restart_at":null,"updated_at":"...","supervisor_pid":0,"gateway_pid":0}
```

A missing or unparsable file is "no status" (the app reports `not_started`), never
a guessed cause. The app exposes the same snapshot as
`GET /api/system/assistant` with the closed cause vocabulary.

---

## 4. Repair procedures

### 4.1 Gateway down

**Symptom.** The assistant answers "unavailable", the assistant sidebar shows its
health banner, or the gateway port is closed while `GET /health` still answers
200. The app itself works.

**Diagnose.**

```bash
tail -n 100 <root>/logs/demiurgos-gateway.log
tail -n 50  <root>/logs/launcher.log
```

Classify with the supervisor snapshot, never with raw log text. The supervisor
emits only what it can observe without parsing logs:

| Cause | What you will see |
|---|---|
| `not_started` | no gateway process was ever spawned (runtime rejected at boot, CLI missing) |
| `exited` | the supervisor saw the child exit; it restarted it until the attempt cap |
| `config_invalid` | `config.yaml` is unparsable; the supervisor refuses to spawn and never retries |

Provider refusals (401/402/403) and timeouts are **per-turn** causes classified by
the assistant failure taxonomy (`assistant-failure-recovery.md` S3/S4); they show
up in the gateway log and in the turn's localized copy, not in the supervisor's
cause field. A pin mismatch never reaches the supervisor: the launcher rejects it
at boot (§4.2) and the state reads `not_started`.

**Automatic recovery.** A child that exits on its own is restarted by the
supervisor with a bounded backoff (3 attempts at 5 s / 15 s / 45 s by default;
attempts reset after a run that stays up past the reset window). When the cap is
reached the supervisor stops and records `failed/exited`, and the app surfaces
the cause. `DEMIURGOS_GATEWAY_SUPERVISOR=0` disables the wrapper (rollback: one
spawn, no retries); `DEMIURGOS_GATEWAY_BACKOFF` and
`DEMIURGOS_GATEWAY_MAX_ATTEMPTS` tune it.

**Repair.**

- If the cause is `config_invalid` or credentials are missing, **restarting will
  not help**. Fix the configuration or the credential first (§4.4); the app
  shows the remedy and withholds the restart action.
- If the cause is `exited` (or no status exists), restart **only the assistant**:

  ```bash
  <root>/bin/demiurgos restart-assistant
  ```

  It stops the supervised gateway, waits for its port, and starts the runtime
  again (re-exporting the environment, re-verifying the pin and re-seeding the
  gateway key). The API and the user's in-flight work are untouched. From the
  app, the health banner's "Restart assistant" calls the same action through
  `POST /api/system/assistant/restart` (authenticated, coalesced for 20 s).
- Use the platform restart (`<root>/bin/demiurgos restart`) only when the API
  itself is unwell; it stops and starts both components.

**Exit:** the gateway port is open, and one assistant turn answers.

### 4.2 Pin mismatch

**Symptom.** The provisioner reports expected-vs-found, e.g.

```
provision-hermes: expected pin d046ff... at <root>/hermes-agent, found <other>; re-run the installer or this script.
```

or the launcher refuses to start the runtime, or the assistant is unavailable
right after an update.

**Diagnose.**

```bash
<root>/current/scripts/provision-hermes.sh --check   # prints expected vs found
git -C <root>/hermes-agent rev-parse HEAD            # what is actually there
git -C <root>/hermes-agent status --short            # local drift? (should be empty)
```

**Repair.** Re-run provisioning (§4.3). Local changes inside the checkout are
discarded on purpose: the pin is the contract. If the pin itself is wrong, fix
it in the source you installed from (§2), not by hand-editing the checkout.

**Exit:** `--check` exits 0.

### 4.3 Re-provision the runtime

Safe and idempotent. It returns immediately when the checkout is already at the
pin with a usable launcher; otherwise it fetches the pinned commit into a
staging directory and only then replaces the checkout, moving the previous one
to `<root>/hermes-agent.previous-<timestamp>`.

```bash
# Installed layout
<root>/current/scripts/provision-hermes.sh

# Explicit root (parallel installs, tests)
<root>/current/scripts/provision-hermes.sh --install-root /path/to/root
```

`setup-hermes.sh` runs with a scratch `HOME`/XDG directories inside the install
root that are deleted afterwards, so it never writes the user's `~/.local/bin`
or shell rc files. The first run can take 1–5 minutes; the profile seeding
(`config.yaml`, `.env`, `API_SERVER_ENABLED=true`) also runs on an already
provisioned checkout, so a missing profile file is repaired without a re-fetch.
A Hermes already installed on the machine (on `PATH`, or a personal
`~/.hermes`) is reported and left untouched.

**Exit:** the provisioner ends with `runtime ready at <root>/hermes-agent (pin …)`.

### 4.4 Unusable configuration or missing credentials

**Symptom.** The runtime starts and immediately refuses, or every turn fails with
an auth/quota copy, or the assistant settings panel shows the key as missing or
the configuration as saved-but-not-active.

**Diagnose (read-only).**

```bash
sed -n '1,60p' <root>/hermes/config.yaml     # model.provider / model.base_url / model.default
grep -c 'API_SERVER_ENABLED=true' <root>/hermes/.env
```

Do not print key values; `AssistantSettingsStatus` reports only
`key_configured`. The authoritative fix path is the app: **Perfil → Asistente**,
which reads and writes the same `config.yaml`/`.env` through
`assistant_settings.py`.

**Repair.** Save the configuration in the app (or fix the profile directly and
restart). A configuration change requires the runtime to load it again: the
settings report `pending-reload` until the runtime restarts. Phase 0.5 makes the
existing health banner's action restart the assistant in that state instead of
telling the user to restart the platform.

**Exit:** the settings report `active`, the key is configured, one assistant
turn answers.

---

## 5. Log locations

| File | Written by | Content |
|---|---|---|
| `<root>/logs/launcher.log` | `start-demiurgos.sh` | boot, adopted processes, component start/stop, health polling |
| `<root>/logs/demiurgos-api.log` | the API child (`uvicorn api_server:app`) | every API request and background job |
| `<root>/logs/demiurgos-gateway.log` | the gateway child (`hermes gateway run`) | provider calls, run lifecycle, upstream refusals |

Today the three logs **rotate** and a report carries a bounded window instead of
dropping everything:

- `log_rotation.py` runs from the API's boot thread and archives each live
  `*.log` as `<log>.N` by copy+truncate (`.1` is the newest archive). It never
  renames a live file: the launcher's `O_APPEND` handles must keep pointing at
  it. Bounds and switches: `DEMIURGOS_LOG_MAX_BYTES` (per live file),
  `DEMIURGOS_LOG_KEEP` (archives kept), `DEMIURGOS_LOG_ROTATE_INTERVAL_SECONDS`,
  and the kill switch `DEMIURGOS_LOG_ROTATION=0`. The launcher still owns
  *where* the logs live and exports `DEMIURGOS_LOG_DIR`.
- A report's `logs` is the newest window, not the history: each source
  contributes at most 16 KiB of its newest bytes, families are walked
  newest-first, and the joined payload never exceeds 64 KiB
  (`bug_report.py`, `_LOGS_MAX_BYTES`). `included: false` now means "no readable
  source", never "too big".
- Beside the text logs the API keeps two bounded journals under the state dir:
  `operations-ring.jsonl` (200 records / 512 KiB; failing and mutating requests;
  `DEMIURGOS_OPERATIONS_RING=0` disables it) and `assistant-turns.jsonl`
  (100 turns / 256 KiB; one record per activity turn, **not** the guided turn).

The files themselves are still available through `scripts/collect-diagnostics.sh`
(§6), which now emits the same `diagnostics.json` as the in-app report.

---

## 6. Reading a report bundle

There are two bundles; know which one you have.

### 6.1 In-app report (Perfil → Reporte de errores)

The app posts a JSON bundle to the relay; the relay publishes it to the owner's
inbox. Payload keys (relay schema 3 in `bug_report.py`):

```
{ schema, app_version, platform{os, os_version, arch, python_version},
  description, contact, context{...}, logs{included, text, reason, redacted_lines},
  diagnostics{schema, ...} }
```

- `logs` is default-on, **secret-redacted** with `content_scan.redact_secrets`
  and **content-scrubbed** by default: a matching secret line becomes
  `[redacted: <rule>]`, and the assistant records' `preview=` payload (the
  prompt and answer tails) becomes `[content omitted]`. The record keeps its
  `len=`, session, timing and outcome.
- Author content travels only when the reporter opts in from the panel
  (`x-bugreport-content: 1`, off by default and never remembered). Then the
  shipped window starts with `== content snippets included at the reporter's
  request ==`, and that label is charged to the same 64 KiB budget. The policy
  is enforced again server-side on `/submit` and `/fallback`, so it does not
  depend on the panel. Opting in never disables redaction.
- `included: false` with a `reason` means the source was unreadable or empty —
  a bounded window is always attempted first.
- `context` carries allow-listed platform facts only; `diagnostics` is built
  server-side (never accepted from the client) and adds the operations ring,
  the recent assistant turns and the log sources. The relay must accept schema 3;
  until it does, each report pays one rejected probe before the downgraded retry.
- The relay implementation lives outside this repository; schema changes need
  its owner.

### 6.2 Manual bundle (`scripts/collect-diagnostics.sh`)

```bash
<root>/current/scripts/collect-diagnostics.sh [output.tar.gz]
```

Read-only: it never uploads, restarts, or touches world data. The tarball
contains `system.txt` (collected_at, install_root, uname, `current_target`,
installed versions) and a copy of `<root>/logs`. It prints a privacy warning
because the logs may contain local paths and hostnames; review before sharing.

### 6.3 How to read either bundle

1. `app_version` + `current_target`: confirm the report came from the version
   the user thinks is running. A mismatch invalidates the rest of the analysis.
2. `logs.included` / `logs.reason`: if logs were dropped, ask for
   `collect-diagnostics.sh` instead of guessing.
3. Check whether the window starts with the content marker. Without it, every
   `preview=` payload is `[content omitted]` by design: ask the reporter to opt
   in and resend before concluding anything about what the assistant said.
4. Read `diagnostics.json`: the operations ring says which request failed and
   with which stable error code; the recent turns say which model, tools,
   evidence status and timings that turn had.
5. Search the gateway log for upstream status codes (401/402/403) before reading
   anything else; those explain most "assistant does not answer" reports.
6. Never copy provider keys, bearer tokens, or world text out of a bundle into
   an issue.

---

## 7. The wiring gate

The runtime answering is not proof that the assistant can read the world. For
any change touching the install layout, the launcher environment, the profile
writer, the graph indexer, or the MCP adapter, run the gate from
`docs/architecture/ASSISTANT_WORLD_READING.md` §5:

```bash
python3 scripts/check_assistant_graph.py     # exit 0 = wiring is sound
```

A green `GET /api/<world>/graph/status` is **not** evidence: the API and the MCP
server build independent indexes.
