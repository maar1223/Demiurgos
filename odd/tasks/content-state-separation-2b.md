# Content/state separation — step 2b (wire the consumers, adopt at boot)

Branch: `feat/content-state-separation-2b` · Base: `master` (`dc0340d7`) · Tests: `../../.venv/bin/python -m pytest tests -q` from `src/tools/demiurgos-suite/wiki` · Delivery: work-unit commits on the feature branch; push/PR are the Owner's decision.

## Specs

S1 — Failure policy (ii), quoted from the approved checkpoint:
"el consumidor devuelve `<data root>/data` mientras exista y la adopción no haya completado; una vez adoptado, todo va a la raíz nueva".
Acceptance: a state-path consumer returns `<data root>/data` while that tree still holds our state artifacts AND the adoption marker is absent; once `<state root>/data/.adoption-complete` exists every consumer uses `<state root>/data`; with no legacy state at all a fresh install uses `<state root>/data`.

S2 — "Añadir una capa fina sobre `resolve_state_root()` que implemente (ii) sin ensuciar el resolver puro."
Acceptance: `data_root.resolve_state_root()` keeps its exact contract (never raises, never inspects the filesystem, never reads the pointer); the (ii) decision lives in a new thin module that both resolvers are called from.

S3 — "Migrar a esa capa: los 5 stores (`idea-capture.sqlite3`, `guided-sessions.sqlite3`, `co-creation-sessions.sqlite3`, `conversation-memory.sqlite3`, `import-jobs.sqlite3`), `world-trash`, `migration-evidence` y `local-state.json`. Ojo con los call sites que usan `_project_root() / "data" / ...` en `api_server.py`."
Acceptance: every one of those eight artifacts resolves under the state dir through the new layer, and no runtime module derives it from `_project_root() / "data"` any more. Every monkeypatch seam that exists today (`TRASH_ROOT`, `default_db_path`, `PROJECT_ROOT`) keeps working.

S4 — "Invocar `adopt_existing_state()` en `_lifespan` (`api_server.py:288`) antes de que cualquier store abra."
Acceptance: the adoption call is the first state-touching statement of `_lifespan`, before session restore, spool GC, skill materialization and the backup engine; an adoption failure is logged and never crashes startup.

S5 — "Verificar: (a) instalación existente arranca con el estado adoptado y nada se pierde; (b) instalación nueva crea el estado en la raíz nueva; (c) `test_backup_restore` y la semántica de backup siguen intactos."
Acceptance: (a) a legacy `<data root>/data` with stores+trash is adopted at boot and the consumers read the new copy byte-identically; (b) with no legacy tree every store lands in `<state root>/data`; (c) a snapshot still captures the four included databases from the live location and a restore puts them back where the app reads them.

S6 — "Riesgo del 2b: **item 1** (cambia la ubicación de datos persistidos) → verificación independiente obligatoria".
Acceptance: `Risk: item 1` closes every unit; one independent verifier runs over the whole feature before delivery.

S7 — Decision D1 (machine state the checkpoint's list did not name): `data/sessions.json` (auth session hashes) and `data/import-spool` (in-flight upload staging) are machine state by `backup.inventory`'s own classification, and the adoption copies the whole tree, so they migrate with the rest and join `state_root_migration.STATE_ARTIFACTS` — otherwise the consumer layer and the adoption disagree about whether a legacy tree is ours.
Acceptance: both resolve under the state dir; a legacy tree that holds ONLY one of them is still adopted.

S8 — Decision D2 (backup follows the state): the SQLite cut reads databases from the state dir and `restore_databases` writes them back to the state dir. The manifest keeps the `data/<name>.sqlite3` label so the on-disk format, the gating rules and every manifest assertion stay unchanged.
Acceptance: `snapshot_databases(state_dir())` and `restore_databases(data_root, payloads, state_dir=...)`; a restore of a snapshot created after the split puts the live databases where the stores open them, and `PRAGMA integrity_check` still gates the write.

S9 — Decision D3: `backup.inventory` excludes the state artifacts under the content root's `data/` (they are no longer content), so a snapshot never carries an inert legacy copy.
Acceptance: a `data/idea-capture.sqlite3` in the content root is reported as excluded with a stable reason; author content under `data/` keeps being included.

S10 — Content stays put: `mundos/`, `ideas/`, `plantillas/`, `config/`, `.env`, `data/methodology/` (including `data/methodology/attachments`) and `data/world-aliases.json` keep resolving from the content root.
Acceptance: none of those paths changes location.

S11 — Hermetic suite: `tests/conftest.py` exports `DEMIURGOS_STATE_ROOT` next to `DEMIURGOS_DATA_ROOT`, so no test can write to the developer's real state dir.
Acceptance: the suite stays green with no `platformdirs` state dir touched.

## Tasks

| ID | Specs | Route | Status |
| --- | --- | --- | --- |
| T1 | S1, S2, S11 | inline | done (c19a0789) |
| T2 | S3, S7, S10 | inline | done (46437e73) |
| T3 | S4, S5a, S5b | inline | done |
| T4 | S5c, S8, S9 | inline | in progress |
| T5 | S5, S6, S10 | inline | pending |

## Log

L1 (Owner, verbatim): "Continuamos con el paso 2b de la separación contenido/estado, con la política (ii)."

L2 — Context recovered from `nec/checkpoint` (#2351): steps 1, 2a merged (`#50`, `#51`), master `dc0340d7`, clean tree; step 2b is "conectar los consumidores a la raíz de estado y adoptar al arrancar" with the five sub-steps S2–S5 above. Policy (ii) chosen by the Owner in L1.

L3 — Exploration (inline, read-only): consumers found in `guided_session_store`, `conversation_memory_store`, `co_creation_session_store`, `import_store`, `graph_mcp_server`, `idea_capture_ui`, `world_recycle_bin`, `retirement_gate`, `demiurgos_language`, `src/tools/idea_capture/{hermes_handler,runtime}.py`, and `api_server` (`local-state.json`, `sessions.json`, `import-jobs.sqlite3`, `migration-evidence`, `import-spool`, idea-capture store). Content that must NOT move: `data/methodology/**` (incl. attachments), `data/world-aliases.json`, `.env`, `mundos`, `ideas`, `plantillas`, `config`.

L4 — Two consequences found that the checkpoint did not name, both recorded as decisions above:
- `backup.sqlite_snapshot` reads `data/<name>.sqlite3` under the data root and `backup.restore` writes it back there; after the split the live databases live in the state dir, so without S8 the snapshot would silently capture stale copies and the restore would land where nothing reads. S5c ("la semántica de backup sigue intacta") requires S8.
- `data/sessions.json` and `data/import-spool` are machine state by the repo's own exclusion table and the adoption copies the whole tree; leaving them behind would keep auth hashes and in-flight uploads in the synced folder. S7.

L5 — Route: inline. No writer trigger holds (the units are sequential, each depends on the previous, and no two edit disjoint surfaces in parallel); verification trigger fires (S6, item 1) → one independent verifier at the feature end, plus the parent spot check.

L6 — Baseline: `4318 passed, 24 skipped` in 240 s with `.venv/bin/python -m pytest tests -q`. The system `python3` cannot collect 27 modules (`argon2` missing) — the venv is the runner.

L7 — T1 closed (`c19a0789`): `state_paths.py` implements (ii) as a pure path decision (marker present → state root; no marker + a legacy artifact → legacy; otherwise state root; unconfigured content root → state root), `STATE_ARTIFACTS` gained `sessions.json` and `import-spool`, the `data_root` docstring now names the layer, and `conftest.py` exports a hermetic `DEMIURGOS_STATE_ROOT`. RED→GREEN evidence: `tests/test_state_paths.py` (14 cells) written first; `test_data_root_resolver` needed one honest update (its no-override default now goes through `environ={}`). Full suite after T1: 4332 passed, 24 skipped.

L8 — T2 wiring: 13 runtime modules migrated (5 stores, recycle bin, migration evidence, locale registry, sessions registry, import spool, idea-capture DB + lock, graph MCP state path, the `idea_capture` package's two state paths and its CLI). Two test-hygiene consequences surfaced and were fixed rather than papered over: (1) `PROJECT_ROOT` sandboxing no longer isolates state, so `conftest.py` now gives every test its own state root AND drops the `api_server` singletons that captured a state path (`_LOCAL_STATE`, `_IMPORT_STORE`, `_BACKUP_ENGINE`, the five `_LazyBinding` stores); (2) the two `_lifespan` cells in `test_import_spool_gc` neutralize the acceptance-convergence thread, which used to outlive the test and write into the next test's state directory. `payload_manifest.json` regenerated (the payload now ships `state_paths.py` and `state_root_migration.py`, which nothing imported at runtime before). New `tests/test_state_consumer_wiring.py` (21 cells) pins every consumer, the content paths that must NOT move, and policy (ii) end to end through a live consumer. Full suite: 4353 passed, 24 skipped.

L9 — T3: `_adopt_existing_state_once()` is the FIRST statement of `_lifespan`, before session restore, the spool sweep, skill materialization and the backup engine; it logs `adopted` at INFO and a failure at WARNING and never aborts the boot. One real defect surfaced while wiring it: `create_import_router` resolved its store at import time (`_store = ... else store()`), so the import store would have stayed bound to the PRE-adoption tree and jobs created in the upgrade session would vanish on the next restart. Fixed with `import_router._LazyStore` (resolves on first attribute access) plus a lazy `_IMPORT_SERVICE` built by `_import_service()`; the ~20 router call sites are untouched. New `tests/test_state_boot_adoption.py` (6 cells) drives the real lifespan: adoption-before-everything order, byte-identical adopted copy, the first boot reading the adopted registry, a second boot never re-adopting, a failed adoption booting from the legacy tree, and an empty content root writing no evidence. Full suite: 4359 passed, 24 skipped.
