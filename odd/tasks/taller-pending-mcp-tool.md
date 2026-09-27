# Taller de Ideas — `pending_list` MCP tool (conversational pending queue)

## Objective

Let the Demiurgos assistant answer "¿qué tengo pendiente?" in natural language by
exposing the parked-capture queue (`AWAITING_CONFIRM`) as a read-only MCP tool,
consistent with the existing `ideas_*` tools.

## Problem / Why

The pending captures live in `<data root>/data/idea-capture.sqlite3` and are only
reachable through the Telegram Guardar/Descartar keyboard or the web review panel.
The Demiurgos MCP server (`graph_mcp_server.py`) exposes the idea bank
(`ideas_list`/`ideas_read`/`ideas_search`) and the graph, but **not** the pending
queue — so the assistant literally cannot tell the author what is waiting.

## Scope

- Add one read-only tool `pending_list()` to `graph_mcp_server.py`.
- Tests for it.

Out of scope (explicit): `pending_confirm` / `pending_discard`. Resolving a
capture needs the full idea-capture runtime (worker/store) in the MCP process —
heavy and redundant with the keyboard and the web panel. Keep the MCP surface
read-only.

## Design (verified)

- Pending rows: `captures` table, `state = 'AWAITING_CONFIRM'`, ordered by
  `created_at` (`CaptureStore.pending_confirm`, `store.py:197`).
- State value literal `AWAITING_CONFIRM` (`models.CaptureState`,
  `models.py:24`). The MCP server must NOT import `idea_capture` (its
  `__init__.py` pulls the whole adapter/runtime/service chain) — so the state is
  a documented local constant and the DB is read directly.
- DB path: `data_root.resolve_data_root() / "data" / "idea-capture.sqlite3"`
  (same resolver `IdeasBank` already uses in this process).
- Connection: read-only URI (`file:<path>?mode=ro`, `uri=True`, `timeout=10`) so
  the MCP server never writes the schema nor contends with the runtime writer.
- Returned fields per capture: `capture_id`, `slug`, `raw_text`, `created_at`,
  `event_ts`, `media_kind` (mirrors the web `GET /api/idea-capture/pending`).
- Missing DB → `{captures: [], count: 0}`. Read error → empty with an `error`
  field (honest, never a crash).

## Tasks

- [ ] **T1** — `pending_list()` tool in `graph_mcp_server.py` (+ docstring tool
  list updated).
- [ ] **T2** — tests in `src/tools/demiurgos-suite/wiki/tests/test_graph_mcp_server.py`.

## Acceptance criteria

- `pending_list()` returns only `AWAITING_CONFIRM` rows, ordered by `created_at`,
  with the six fields above and a matching `count`.
- Missing DB returns an empty list, no exception.
- No `idea_capture` import; no schema write.
- Repo tests pass.

## Route (ODD)

Delegated direct: one writer (T1+T2), then independent verification.

## Progress

- 2026-09-27 — Branch `feat/taller-pending-mcp-tool` (from master). Design
  grounded in `store.py`/`models.py`/`data_root.py`.
- 2026-09-27 — T1/T2 done. `pending_list()` in `graph_mcp_server.py` + 7 tests.
  Assess: risk `medium` (`executable_change`). Independent verifier
  PASS-with-caveats, found 2 robustness gaps (naive SQLite URI on metacharacter
  paths; `resolve_data_root()` outside the guard breaking "never raises"); both
  fixed with regression tests. Suite: 60 passed (53 baseline + 7).
- Pending: gateway restart (owner action) so the MCP server exposes the tool.

## Evidence

- `.venv/bin/pytest src/tools/demiurgos-suite/wiki/tests/test_graph_mcp_server.py -q`
  → 60 passed.
- Read-only proven: DB bytes/mtime unchanged, no sidecars, `mode=ro` write
  rejected. No `idea_capture` import. Tool registered on the FastMCP instance.
