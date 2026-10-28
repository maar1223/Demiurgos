# Install Layout Contract (frozen — S0-C)

> Change: `cross-platform-one-command-install` · Status: **frozen** · Owner of the
> runtime layout: the **launcher** (S2a), the **installer** (S3a/S3b) and the
> **release packaging** (S5a) all derive their paths from this document. It is a
> contract, not documentation: anything that hardcodes a path that contradicts
> this table is a bug.
>
> This is the single source of truth for where the installed Demiurgos lives.
> It supersedes every earlier ad-hoc layout (`<install_root>/.venv`,
> `$PROJECT_ROOT/.venv`, forced `DEMIURGOS_DATA_ROOT="$PROJECT_ROOT"`, …).

## 1. Layout table

| Element | POSIX | Windows |
|---|---|---|
| Install root | `~/.demiurgos` (`DEMIURGOS_HOME` override) | `%LOCALAPPDATA%\Demiurgos` |
| App root | `<install_root>/app/<version>` | `<install_root>\app\<version>` |
| `current` | symlink → `app/<version>` | junction → `app\<version>` |
| Venv | `<current>/.venv/bin/python` | `<current>\.venv\Scripts\python.exe` |
| Backend entry | `<current>/src/tools/demiurgos-suite/wiki/api_server.py` | same |
| SPA dist | `<current>/frontend/dist` | same |
| Launchers | `<current>/scripts/start-demiurgos.sh` | `<current>\scripts\start-demiurgos.ps1` |
| Logs (persistent) | `<install_root>/logs/` | `<install_root>\logs\` |
| Runtime state (pid files) | `${XDG_RUNTIME_DIR:-$TMPDIR}/demiurgos-launcher` | `%LOCALAPPDATA%\Demiurgos\run` |
| Data root | env `DEMIURGOS_DATA_ROOT` → pointer → bootstrap-once `~/.demiurgos/data` | env → pointer → `%LOCALAPPDATA%\Demiurgos\data` |
| State root (machine-local) | env `DEMIURGOS_STATE_ROOT` → `$XDG_DATA_HOME/demiurgos` (else `~/.local/share/demiurgos`) | env → `%LOCALAPPDATA%\demiurgos` |
| Data-root `.env` | `<data_root>/.env` (auth mode + locale; **never in payload**) | same |

Author content and machine state live in DIFFERENT roots: the data root holds
what the author backs up, the state root holds locks/WAL/SQLite that must stay on
one machine. See [`CONTENT_AND_STATE.md`](CONTENT_AND_STATE.md) for the split,
the one-time adoption and the backup routing.

Where `<install_root>` is `$DEMIURGOS_HOME` when set, otherwise the platform
default above; `<version>` is the installed `DEMIURGOS_VERSION` (e.g. `0.9.0`);
`<current>` is `<install_root>/current` resolved through the symlink/junction.

## 2. Key rules

1. **`APP_ROOT` is derived from the launcher's own location.** The launcher
   resolves `SCRIPT_DIR` from `$0` and sets `APP_ROOT="$(cd "$(dirname "$0")/.." && pwd)"`
   (Windows: `$PSScriptRoot\..`). It NEVER reads a hardcoded path and NEVER
   uses `$PROJECT_ROOT/.venv`. Because the dev checkout and the installed
   layout share the same relative structure
   (`<root>/src/tools/demiurgos-suite/wiki/api_server.py` and
   `<root>/scripts/start-demiurgos.sh`), **one launcher serves both**.
2. **`DEMIURGOS_FRONTEND_DIST` has exactly one owner: the launcher.** It is
   exported as `<APP_ROOT>/frontend/dist` before uvicorn starts and by nothing
   else. The backend's `_frontend_dist()` falls back to
   `_CODE_ROOT/frontend/dist` in dev, where the launcher is not involved.
3. **The SPA dist derives from `APP_ROOT`, independent of the data root.**
   `<current>/frontend/dist` always — never from `<data_root>`, never from a
   world directory, never from the CLI clone (`repo/`). A data root that points
   at a CLI clone (see §4) has no `frontend/dist`, and that is correct: the
   clone is not the runtime app.
4. **The data root is resolved in this order only**: existing env
   `DEMIURGOS_DATA_ROOT` → existing pointer file → bootstrap-once the default
   `<install_root>/data`. An existing pointer is never silently re-oriented.
5. **The data-root `.env` is seeded by the installer, exported by the
   launcher.** It contains non-secret install-time values
   (`DEMIURGOS_AUTH_MODE=local-dev`, `DEMIURGOS_LANGUAGE=<locale>`, optional
   `DEMIURGOS_WORLD=`). It is written only when absent and never ships inside
   the payload. The launcher parses it in pure shell (no system `python3`) and
   exports the values before starting uvicorn.
6. **`current` is flipped atomically by the installer** after a same-FS staged
   rename; the previous `app/<version>` is retained until the next install
   (rollback boundary — see S6, bounded boot rollback).

## 3. Data-root pointer

The pointer is the byte-compatible format owned by `data_root.py`
(`write_pointer`/`read_pointer`) — the installer reuses it and never
re-implements the format. POSIX default location follows
`platformdirs` semantics (XDG_CONFIG_HOME/`~/.config`); Windows follows
`%APPDATA%`. The installer writes the pointer only when neither the env nor a
pointer exists (bootstrap-once).

## 4. Coexistence with the CLI stack (`repo/` vs `app/`) — D5

The existing CLI bootstrap (`install.sh`, CLI stack) clones the private repo
to `$DEMIURGOS_HOME/repo` (a.k.a. `~/.demiurgos/repo`) and probes it. The
platform installer uses `app/<version>` + `current`. Both live under the same
install root and MUST coexist:

- `repo/` — the CLI clone (source checkout, author continuity).
- `app/<version>` + `current` — the runtime app installed by the platform
  installer (payload tree, venv, launchers).
- A data-root pointer may legitimately point **at the CLI clone** (author
  continuity) and MUST be preserved untouched by the installer.
- The installer never adopts `repo/` as the app root and never clobbers it.
- The SPA dist derives from `APP_ROOT` (§2.3), so a data root pointing at the
  CLI clone simply serves no dist — the CLI stack does not need one.

## 5. Environment variables owned by this contract

| Variable | Owner | Meaning |
|---|---|---|
| `DEMIURGOS_HOME` | installer/launcher | install root override |
| `DEMIURGOS_VERSION` | bootstrap/installer | pinned version; default `latest` |
| `DEMIURGOS_DATA_ROOT` | launcher/backend | data root (env wins) |
| `DEMIURGOS_AUTH_MODE` | **launcher only** (exported from data-root `.env`) | install-time auth mode |
| `DEMIURGOS_FRONTEND_DIST` | **launcher only** | `<APP_ROOT>/frontend/dist` |
| `DEMIURGOS_URL_BASE` | installer | overridable channel base (test seam) |
| `UV_VERSION` | installer | pinned uv version |

## 6. What this contract deliberately does NOT own

- The data-root `.env` content beyond the seed keys (§2.5) — secrets and
  operator overrides are the user's.
- CORS (`DEMIURGOS_CORS_ORIGINS`) — a dev-only override, unchanged by this
  change.
- The `plantillas/` and `mundos/` trees — author data, out of the payload.