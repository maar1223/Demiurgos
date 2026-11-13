# Local install vehicle (this machine only)

`scripts/install-local.sh` builds **this checkout** and installs it as a real
Demiurgos version under the install root. It never touches the release channel:
no tag, no publish, no download, no signature.

Use it when you are iterating on the code and want the app in front of you now.
Use the release protocol (`docs/RELEASING.md`) when the change must reach other
machines.

## Commands

```bash
# Plan only: prints the version, app dir and build decision, writes nothing.
scripts/install-local.sh --dry-run

# Normal loop: rebuild the frontend when src is newer, install, restart.
scripts/install-local.sh

# Force or skip the frontend build.
scripts/install-local.sh --build
scripts/install-local.sh --no-build

# Install and flip `current` without restarting the app.
scripts/install-local.sh --no-restart

# Keep only the newest 3 local builds (default is 5).
scripts/install-local.sh --keep 3
```

## What it does

1. Derives `<base>+local.<YYYYMMDD>.<HHMMSS>.<sha>[.dirty]` from the latest
   git tag, the local clock and `HEAD`.
2. Rebuilds `frontend/dist` when `frontend/src` is newer (or when forced).
3. Assembles the **same payload the release workflow ships**: the
   `payload_manifest.json` allow-list, the explicit extras, `LICENSE`, and
   `frontend/dist`.
4. Creates a self-contained `.venv` with the pinned `uv` and the hash-locked
   `requirements.lock` (the uv cache makes repeats fast).
5. Moves the staged tree to `app/<version>`, flips `current`, and restarts the
   launcher (`start-demiurgos.sh restart`), which verifies `/health`.

## Version label and updates

The label is SemVer build metadata with the local date and time:
`0.9.0+local.20261113.035500.059dc49`, or `...\.dirty` when tracked files have
uncommitted changes. The timestamp makes every local build distinguishable at
a glance.

Build metadata never affects precedence, so the updater compares a local build
**equal** to the same released version and does not nag with a bogus "update
available". A genuinely newer channel release still shows up as an update.

## Rollback and cleanup

Each install keeps the newest `--keep` local builds (default 5) and prunes the
rest **after** a successful install. The running version and every channel
version are never touched.

- The launcher's bounded rollback can still fall back to the previous version.
- To go back by hand: point `current` at the version you want, for example
  `ln -sfn app/<version> ~/.demiurgos/current` and restart.

Local version directories are ordinary directories (no archives, no channel
metadata), so removing an old one is just `rm -rf app/<version>`.

## Requirements and limits

- POSIX only (the launcher's supported Linux/macOS shells).
- A normal Demiurgos install must already exist under `~/.demiurgos`
  (`app/` and `bin/uv`). This vehicle does not bootstrap a first install.
- It is a development tool and is **not** part of the shipped payload.
