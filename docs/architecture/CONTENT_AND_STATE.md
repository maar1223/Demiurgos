# Content root vs state root

> Status: **in effect** since the content/state separation (steps 1, 2a, 2b).
> Companion to [`INSTALL_LAYOUT.md`](INSTALL_LAYOUT.md), which owns the install
> paths; this document owns the split between what the author backs up and what
> belongs to one machine.

## Why two roots

Demiurgos keeps two different kinds of data side by side:

- **Author content** — worlds (`mundos/`), the ideas bank (`ideas/`),
  templates, configuration, the methodology library and its attachments. It is
  the author's work, it is worth backing up with any cloud client, and moving it
  between machines is the point.
- **Machine state** — the SQLite stores, the world recycle bin, migration
  evidence, `local-state.json`, the auth-session registry, the import spool and
  the process locks. It is opened with locks and WAL, is worthless (or corrupt)
  on another machine, and a cloud client syncing a live SQLite file between two
  machines corrupts it.

`resolve_data_root()` names the first. `resolve_state_root()` names the
machine-local base for the second. `state_paths.resolve_state_dir()` combines
them — the only place that decides which directory machine state uses.

## Where things live

| Content root (`DEMIURGOS_DATA_ROOT`) | State directory |
|---|---|
| `mundos/`, `ideas/`, `plantillas/`, `config/`, `.env` | `idea-capture.sqlite3` |
| `data/methodology/` (library, seeds, skills, attachments) | `guided-sessions.sqlite3` |
| `data/world-aliases.json` | `co-creation-sessions.sqlite3` |
| `data/probes/` (regenerable readiness probe) | `conversation-memory.sqlite3` |
| | `import-jobs.sqlite3`, `world-checkpoints.sqlite3` |
| | `local-state.json`, `sessions.json` |
| | `world-trash/`, `import-spool/`, `migration-evidence/` |

Default locations:

| | POSIX | Windows |
|---|---|---|
| Content root | env → pointer → bootstrap-once the documents folder + `/Demiurgos` (`~/Documents/Demiurgos`; `~/Documentos/Demiurgos` on a localized desktop) | env → pointer → bootstrap-once `%USERPROFILE%\Documents\Demiurgos` (the shell's Documents folder) |
| State base | `DEMIURGOS_STATE_ROOT` → `$XDG_DATA_HOME/demiurgos` (else `~/.local/share/demiurgos`) | `DEMIURGOS_STATE_ROOT` → `%LOCALAPPDATA%\demiurgos` |

The state directory is always `<base>/data`, on both sides of the split.

The documents folder is never hardcoded: POSIX reads `XDG_DOCUMENTS_DIR` from
`user-dirs.dirs` (falling back to `~/Documents`) and Windows asks the shell
(`[Environment]::GetFolderPath('MyDocuments')`, falling back to
`%USERPROFILE%\Documents`). A localized folder name and a redirected one
(OneDrive Known Folder Move) are both followed, so the content root is the
folder the author actually sees.

> **Windows note.** A pointer written before step 3 records
> `%LOCALAPPDATA%\Demiurgos\data`, which IS the default state directory. Such an
> install still resolves both sides to the same folder: the split is inert there
> (the adoption is a no-op and every consumer works exactly as before), and no
> data is lost or copied. It becomes effective when the pointer is re-oriented,
> which this project never does silently. A **new** install bootstraps the
> content root under Documents, so the split is effective from the first boot.

## Policy (ii): which directory wins

| Situation | Resulting state directory |
|---|---|
| `<state base>/data/.adoption-complete` exists | `<state base>/data` |
| no marker, the legacy `<content root>/data` holds a state artifact | `<content root>/data` (adoption pending) |
| no marker, no legacy state artifact | `<state base>/data` (fresh install) |
| no content root configured | `<state base>/data` |

The marker is written INSIDE the staged copy, last, and the copy is published
with a single `os.replace`, so its presence proves a complete copy. Two
processes booting at once may both stage; only one publishes, and the loser
follows the winner's marker instead of writing a second tree.

Nothing is cached: the decision is derived on every call, so the boot-time
adoption flips it for the rest of the process.

## The one-time adoption

`state_root_migration.adopt_existing_state()` runs as the FIRST statement of the
API lifespan, before any store opens:

1. if `<content root>/data` holds a state artifact and the state directory does
   not exist, the tree is copied (SQLite and its `-wal`/`-shm` siblings included)
   into a stage on the state filesystem;
2. the source tree hash is recorded before the copy and the staged copy must hash
   to the same value (a source that changed mid-copy aborts);
3. `.adoption-complete` is written into the stage and the stage is published with
   one `os.replace`;
4. one JSON record per attempt lands in `<state base>/migration-evidence/`.

The source is **never deleted** and never modified: it stays in place, inert, so
a later cleanup step can offer to remove it. A failed adoption is logged and the
process keeps booting from the legacy tree — the pre-split behaviour — rather
than refusing to start.

## Backup and restore

The backup is the one feature that spans both roots:

- the four databases it captures are cut from the state base
  (`Connection.backup()`, read-only, WAL included), because that is where the
  stores open them;
- the copy-back of a restore writes them into the state base, and the restore
  retires the copy the member swap necessarily deposits in the content root;
- the manifest keeps the `data/<name>.sqlite3` labels, so the snapshot format,
  the path gate and the integrity check are unchanged;
- the inventory refuses state artifacts found under the content root's `data/`
  with the reason `excluded:state-root-artifact`: after an adoption that folder
  may still hold an inert copy, and it must never be uploaded as author content.
- a destination that overlaps the content root is refused: equal to it, inside
  it, or containing it. The check runs when the folder is chosen AND again when
  a run starts, so a record written earlier (or edited by hand) cannot reach the
  writer. The reason is the inventory's own rule: it includes every top-level
  folder it does not recognise, and the backup's layout (`current/`,
  `snapshots/`, `meta/`, `world-trash-index/`) is exactly such a folder — an
  overlapping destination would carry each run into the next one, and `current/`
  would copy itself. A backup stored inside the folder it backs up is also one
  copy and one failure.

## Tests and seams

- `DEMIURGOS_STATE_ROOT` and `DEMIURGOS_DATA_ROOT` isolate the whole suite;
  `tests/conftest.py` gives EVERY test its own state root and drops the
  process-wide singletons that captured a state path.
- `tests/state_root_support.py` answers "where is state for this test" without
  hardcoding the layout.
- `state_paths.resolve_state_dir(environ=…, state_dir=…, config_dir=…)` and
  `resolve_state_base(…)` are fully injectable; `data_root`'s two resolvers stay
  pure (no filesystem inspection, no pointer reads in the state resolver).
