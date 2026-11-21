# Assistant world-reading — wiring contract and incident record

> Status: **in effect** (2026-11-18). This is a **contract**, not documentation.
> It names the one capability that separates Demiurgos from a generic chat: the
> assistant reads the author's world. A change that violates it is a bug even
> when every test is green.
>
> Companion documents: [`INSTALL_LAYOUT.md`](INSTALL_LAYOUT.md) (where the code
> tree and `current` live) and [`CONTENT_AND_STATE.md`](CONTENT_AND_STATE.md)
> (data root vs machine state). Read those before changing anything this
> document covers.

## 1. Why this is a contract

Every other feature can degrade gracefully and the product still works: a broken
importer is an error message, a broken UI is a bad screen. A blind assistant is
different — it silently becomes a general-purpose chatbot wearing Demiurgos'
voice, answering about the author's world from model memory and old notes. That
is the failure mode this document exists to prevent. It is invisible unless
someone asks a question whose answer exists only in a ficha.

The capability is one chain, and every link is owned by a different subsystem:

```
launcher (scripts/start-demiurgos.sh)
  │
  ├─ export DEMIURGOS_DATA_ROOT=<data root>     (author content: mundos/, ideas/)
  ├─ export DEMIURGOS_ROOT=<app root>           (code tree: current/)
  │
  ├─ uvicorn api_server ──► in-process EntityGraphIndex(<data root>/mundos)
  │                         powers /api/{mundo}/graph/* and prompt evidence
  │
  └─ hermes gateway ──► reads <HERMES_HOME>/config.yaml
                        mcp_servers.demiurgos-graph
                          args: graph_mcp_server.py --mundo <W> --mundos-path <P>
                        ──► a SEPARATE process: EntityGraphIndex(P)
                            tools: mcp__demiurgos_graph__graph_search / graph_read /
                                   graph_status / graph_rebuild / graph_links /
                                   lore_search / lore_conflicts / auto_tag …
```

**The trap, stated once:** there are **two independent indexes**. The API builds
one on the data root (correct by construction). The MCP server builds another on
whatever `--mundos-path` says. `/api/{mundo}/graph/status` reporting
`node_count: 71` proves **nothing** about the assistant. Only the MCP process'
own `graph_status` counts.

Same process, two behaviours worth remembering: the idea-bank tools
(`ideas_*`, `pending_list`) resolve `<data root>/ideas` lazily and keep working
while the world index is empty. A healthy server with an empty world index looks
exactly like a healthy server.

## 2. Invariants

Violating any of these is a defect, not a preference.

| # | Invariant |
|---|---|
| **I1** | The MCP `--mundos-path` MUST resolve to the same `<data root>/mundos` the API uses. `${DEMIURGOS_ROOT}/mundos` is **forbidden**: `DEMIURGOS_ROOT` is the code tree and never contains author data. Allowed: `${env:DEMIURGOS_DATA_ROOT}/mundos`, an absolute `<data root>/mundos`, or `mcp_launcher.py`, which resolves the data root itself. |
| **I2** | The configured `--mundo` MUST exist as a directory under that `mundos/` and yield at least one indexable ficha. An empty world is a FAIL, never "no data yet". |
| **I3** | Author data is never resolved code-relatively. `data_root.resolve_data_root()` is the only resolver (env → pointer → loud failure). No `Path(__file__).parents[N]`, no repo-relative `mundos`. |
| **I4** | `/api/{mundo}/graph/status` is **not** evidence about the assistant. Verification reads the MCP process' `graph_status`. |
| **I5** | Provisioning is idempotent and never silently overwrites an existing profile. `config.yaml` survives upgrades, so a wrong value written once persists forever. Conversely, a provisioning fix must be able to *correct* a value it owns. |
| **I6** | The graph MCP must be registered by the **product** (installer/provisioner), not by hand on one machine. POSIX installers register it since 2026-11-18 and the Windows core since 2026-11-20; the boot-time self-check remains open, see §7. |
| **I7** | A blind graph must be visible, never papered over: the assistant says it cannot read the world and asks for the text, and never asserts world facts from memory. This held during the incident and is the behaviour to preserve. |

## 3. Incident record — 2026-11-18

### Symptom

In chat session `mwmvrrdkh9gwwc` (world `Vibrantes`, 2026-11-18 21:39–21:52
local), the assistant could not read a ficha that was open on screen:
`lore/politica-distribucion-y-territorios/chaart.md`. It reported an empty graph
and asked the author to paste the text.

### Evidence (from the live run, `HERMES_HOME/state.db`)

```
graph_status  -> {"entity_count": 0, "last_build": "2026-11-19T01:49:48Z"}
graph_rebuild -> {"entity_count": 0, "rebuilt": true}
graph_search  -> {"matches": [], "query": "Chaart"}
graph_read    -> {"exists": false,
                  "path": "lore/politica-distribucion-y-territorios/chaart.md"}
```

The running MCP process (`spawn-ledger.json`, `pgrep -af graph_mcp_server`):

```
graph_mcp_server.py --mundo Vibrantes \
  --mundos-path /home/miguel-angel/.demiurgos/current/mundos
```

`~/.demiurgos/current/mundos` **does not exist**. The data root
(`~/.config/demiurgos/data-root.json` → `/mnt/3C2A86E52A869C10/Demiurgos`) holds
`mundos/Vibrantes` with ≈71 indexable fichas (70 under `lore/`, 1 under
`personajes/`).

### Root cause

`~/.demiurgos/hermes/config.yaml` declared:

```yaml
mcp_servers:
  demiurgos-graph:
    args:
      - ${env:DEMIURGOS_ROOT}/src/tools/demiurgos-suite/wiki/graph_mcp_server.py
      - --mundo
      - Vibrantes
      - --mundos-path
      - ${env:DEMIURGOS_ROOT}/mundos      # code tree — no author data here
```

`DEMIURGOS_ROOT` is exported by the launcher as `<install_root>/current` (the
code tree). The payload never ships a `mundos/` directory — no installed version
from `0.2.2` to `0.10.3` has one. The path therefore pointed at a directory that
cannot exist in the installed layout.

### Timeline

| When | What |
|---|---|
| 2026-08-23 | Graph MCP wired to `${env:DEMIURGOS_ROOT}` (Engram #2575). It **worked** because the launcher then exported `DEMIURGOS_ROOT=<repo>`, and `<repo>/mundos/Vibrantes` had content. Verified by reading a real ficha. |
| 2026-10-28/29 | Content/state split: author data moved to the data root (`data-root.json`), code to `<install_root>/current`. `DEMIURGOS_ROOT` kept its name but changed meaning. |
| 2026-11-02 | Earliest surviving profile backup already carries `${env:DEMIURGOS_ROOT}/mundos`. The block was carried across, unchanged, into the dedicated profile. |
| 2026-11-02 → 11-18 | Broken for ~16 days and across every upgrade. Nothing rewrote the block, so nothing healed it. |
| 2026-11-18 21:49 | The assistant called the tools for real, saw an empty index, and said so. |

### Why it was silent

1. The MCP server is healthy — it registered all 16 `@mcp.tool` entries and
   answered in milliseconds. Health checks pass.
2. `graph_rebuild` returns `rebuilt: true` with `entity_count: 0` — a truthful
   answer to a question nobody asked.
3. The API's own index is correct, so the UI graph, the lore tree and the
   injected prompt evidence all look fine.
4. The assistant degrades honestly (I7), so the failure reads as "this world has
   no data" instead of a bug.

### Blast radius

Everything the assistant does through the graph: entity search, ficha reads,
link/backlink traversal, canon conflicts, auto-tagging, narrative tools. The
API, UI, importer, backup and idea-bank tools were unaffected.

### Fix recipe (applied 2026-11-18; recorded for any repeat)

Point the MCP at the data root — or, better, at `mcp_launcher.py`, which resolves
it through `data_root.resolve_data_root()` and derives `--mundo` dynamically
(from `DEMIURGOS_WORLD`, then the data-root `.env`):

```yaml
mcp_servers:
  demiurgos-graph:
    command: python3
    cwd: ${env:DEMIURGOS_ROOT}
    args:
      - ${env:DEMIURGOS_ROOT}/src/tools/demiurgos-suite/wiki/mcp_launcher.py
```

`mcp_launcher.py` builds its own argv and re-executes the server in-process, so
extra CLI flags in the profile are ignored — do not rely on them.

Then restart Demiurgos and run the verification gate (§5). Note the second
latent defect this exposes: `--mundo Vibrantes` was **hardcoded**, so the
assistant would have gone blind again the moment the active world changed.

**Applied on the reporting machine at 2026-11-18 22:21 local** (profile backup:
`~/.demiurgos/hermes/config.yaml.bak-pre-graph-fix-20261118`). Evidence after
the restart:

```
scripts/check_assistant_graph.py                      -> VERDICT: PASS
pgrep -af mcp_launcher                                 -> …/wiki/mcp_launcher.py
MCP graph_status (stdio probe)                         -> {"entity_count": 71}
MCP graph_read lore/…/chaart.md (stdio probe)          -> entity returned
```

Level C (a world-only question answered in the app) remains the Owner's
acceptance step.

## 4. When this gate is mandatory

Run the whole gate before closing ANY change that touches:

- `data_root.py`, `state_paths.py`, `CONTENT_AND_STATE.md` behaviour;
- `scripts/start-demiurgos.sh` / `.ps1` / `start-gateway.*` env exports;
- `install.sh`, `install.ps1`, `scripts/provision-hermes.*`;
- `hermes_profile_config.py` or any writer of `<HERMES_HOME>/config.yaml`;
- `graph_indexer.py`, `mcp_adapter.py`, `graph_mcp_server.py`, `mcp_launcher.py`;
- `warmup_gateway.py`;
- the install layout table (`INSTALL_LAYOUT.md`) or the payload manifest.

No exceptions for "it's only a path rename", "it's a docs change", or "the tests
are green". The incident was born from a path whose meaning changed while its
name stayed the same.

## 5. Verification gate (mandatory, three levels)

### Level A — static wiring (cheap, deterministic)

```bash
# From the checkout (the script is a dev tool and is not part of the install
# payload; it inspects the installed runtime on its own).
python3 scripts/check_assistant_graph.py
```

Exit code 0 = PASS. Every FAIL names the offending value and, when the fix is
known, the remediation. It is read-only: it inspects the data-root pointer, the
Hermes profile and the filesystem, and never writes (it disables bytecode
writing for the resolver it imports). When an installed layout exists it checks that
runtime (`~/.demiurgos/current`), not the checkout, so a stale dev copy of
`mundos/` cannot mask a broken wiring.

This check exists precisely because the API's `/graph/status` cannot answer the
question (I4).

### Level B — live runtime

```bash
pgrep -af mcp_launcher              # after the fix the process is mcp_launcher.py
pgrep -af graph_mcp_server          # legacy/direct entries only: check --mundos-path
curl -s http://127.0.0.1:8000/api/Vibrantes/graph/status   # API index (context)
```

And, from the app, ask the assistant for something that only exists in a ficha
— e.g. "leé `lore/.../chaart.md` y decime el clima". A correct answer requires
content; "no puedo leer el grafo" means the gate failed.

### Level C — semantic acceptance (the one that counts)

Ask one question whose answer lives **only** in the world (a ficha the model
cannot know). The assistant must answer from the file, cite its path, and not
invent alternatives. If it answers from general knowledge, treat the gate as
failed even when Levels A and B are green.

## 6. Failure modes and their signature

| Signature | Cause | First check |
|---|---|---|
| `entity_count: 0` after `graph_rebuild`, `exists: false` for real paths | `--mundos-path` points to a missing/wrong directory (this incident) | Level A |
| Tools not registered at all (`mcp__demiurgos_graph__*` absent from the run) | `demiurgos-graph` missing from the profile (I6) | Level A, `agent.log` |
| `entity_count` correct for one world, zero for another | `--mundo` hardcoded to a stale world | Level A (`--mundo` vs `DEMIURGOS_WORLD`) |
| Works in dev, blind after install | code-relative path used instead of the data root (I3) | Level A from `<install_root>/current` |
| Blind only after an upgrade | provisioning overwrote the profile, or never corrected it (I5) | profile diff vs backup |
| Assistant answers world facts with no tool calls | graph tools unavailable and the model improvised (I7 violation) | Level B + transcript |

## 7. Durable prevention

The incident is diagnosed and the machine is repaired; the *class* is closed by
the following, in order of what landed on 2026-11-18:

1. **Provision the server from the product — DONE (POSIX and Windows).**
   `hermes_profile_config.merge_graph_mcp_server()` registers
   `mcp_servers.demiurgos-graph` → `mcp_launcher.py`, and the checkout
   installer (`install.sh`), the shipping POSIX installer
   (`scripts/install-demiurgos.sh`, after the Hermes runtime and the app venv
   exist) and the shipping Windows core
   (`scripts/install-demiurgos.ps1`, after `Invoke-HermesProvision`) call it.
   It is best-effort and loud: a failure warns that the assistant will not read
   the world, and never aborts the install.
2. **Correct, don't only create — DONE.** The merge is corrective: a stale entry
   (the incident shape: direct `graph_mcp_server.py` + `--mundos-path` on the
   code tree) is rewritten on the next install run. Sibling servers and every
   other top-level key are preserved.
3. **Boot-time self-check — OPEN.** The launcher (or the API boot) should fail
   loudly when the MCP world is missing or empty. A log warning is not enough;
   this is the remaining hole.
4. **Regression test — DONE.** `wiki/tests/test_graph_mcp_provisioning.py` pins
   idempotence, correction of the incident shape, preservation of sibling keys,
   the absence of any hardcoded author-data path or world name, that the
   registered launcher exists and resolves the data root, and that all three
   installers call the merge (in `install.sh` after `prepare_python_env`; in the
   POSIX shipping installer after `provision_hermes_runtime`; in the Windows
   core after `Invoke-HermesProvision`, through the same merge program).
   `wiki/tests/test_assistant_graph_gate.py` pins the gate itself: a relative
   `--mundos-path` resolves against the MCP process' `cwd` and FAILs, the
   launcher entry PASSes, and extra entry keys survive a no-op merge.

**Windows parity — DONE (graph wiring, 2026-11-20).**
`scripts/install-demiurgos.ps1` now registers the corrected
`demiurgos-graph` entry after provisioning the runtime and removes the legacy
Engram server, exactly like the POSIX core. Windows still does not run the
skills external-dirs merge; that remains open and is separate from
world-reading.

Until 3 lands, every change listed in §4 must run the gate by hand, and no
release may ship without a green Level A on a real install.
