# MVP readiness audit — wave 3 (AUD-11 … AUD-17)

Branch: `fix/mvp-audit-wave-3` · Base: `master` (`1165120`) · Delivery: work-unit commits on the feature branch; merge and push are the Owner's decision. Runner: `.venv/bin/python -m pytest`.

## Specs

- **S1 (AUD-11) — relay CI job.** `.github/workflows/ci.yml` runs the separately-deployed Cloudflare Worker's tests and typecheck on Node 22 (the relay's `--experimental-strip-types` test runner needs it). Acceptance: the `relay` job exists and its commands pass locally.
- **S2 (AUD-12) — `engram_sync` promise.** Owner decision (2026-11-03): keep the tool, document it as a manual CLI and drop the "worker" claim. No launcher wiring, no deletion. Acceptance: the README promise matches what actually runs.
- **S3 (AUD-13) — dev-tool dependencies.** Owner decision (2026-11-03): declare them in `requirements-dev.txt` (dev-only, never in the payload): `google-auth`, `google-api-python-client`, `faster-whisper`, `requests`. The scripts stay; `sync-ideas.py`'s docstring drops the unused `gspread`. Acceptance: no undeclared import in the dev tools.
- **S4 (AUD-14) — macOS desktop integration.** Owner decision (2026-11-03): out of MVP scope. The READMEs state macOS launches from Terminal; no `.app`/Applications entry. `install_desktop_entry` was already Linux-only (`[ "$OS" = "Linux" ] || return 0`), so no code change was needed. Acceptance: the desktop story matches the shipped artifacts.
- **S5 (AUD-15) — fixed ports.** The overrides already existed (`DEMIURGOS_API_PORT` / `DEMIURGOS_GATEWAY_PORT`); the gap was documentation. Documented in both READMEs and `.env.example`; the launcher still refuses to reuse a foreign process's port (never kills it) by design. No behavior change.
- **S6 (AUD-16) — Windows payload boot test.** The packaged Windows payload has no real boot test; the fixture fabricates the layout. Acceptance: the packaged Windows bundle boots in CI or a documented harness.
- **S7 (AUD-17) — retired `web-config-ui` tree.** Owner decision (2026-11-03): freeze it. `retirement_gate.py` gains `legacy_tree_frozen`, a SHA-256 fingerprint over every non-generated file under the tree (line endings normalized so CRLF/LF checkouts agree); any edit, addition or deletion fails the gate. Acceptance: the historical tree cannot drift silently.

## Tasks

- T1 — AUD-11 relay CI — inline — done; local `npm test` 143 passed, `npm run typecheck` clean.
- T2 — AUD-12 — inline — done; both READMEs describe `engram_sync` as a manual CLI.
- T3 — AUD-13 — inline — done; `requirements-dev.txt` created; payload manifest still fresh.
- T4 — AUD-14 — inline — done; macOS desktop integration declared out, READMEs updated.
- T5 — AUD-15 — inline — done; port overrides documented (READMEs + `.env.example`).
- T6 — AUD-16 — not started (needs a Windows runner).
- T7 — AUD-17 — inline — done; `legacy_tree_frozen` gate + mutation test (26 retirement-gate tests pass).

## Log

- **L1** Checkpoint continuation: wave 3 is the next step after waves 0, 1 and 2. Owner instruction this session, verbatim: "continua desde checkpoint. Ah y por cierto el ES-AR ya no lo quiero, prefiero solo español neutro".
- **L2** Wave 3 backlog from `docs/MVP_READINESS_AUDIT.md`: AUD-11 relay CI, AUD-12 `engram_sync`, AUD-13 dev deps, AUD-14 macOS desktop, AUD-15 ports, AUD-16 Windows payload, AUD-17 `web-config-ui`.
- **L3** AUD-11 implemented: new `relay` job (Node 22, `npm install` because no lockfile is committed, `npm test`, `npm run typecheck`). Local evidence: 143 tests pass, typecheck clean.
- **L4** Next: Owner decisions for S2..S5 and S7; S6 needs a Windows CI boot harness.
- **L5** (Owner decision, 2026-11-03) `engram_sync`: "Documentarlo como CLI manual". Both READMEs now say `engram_sync` CLI (run manually); the tool and its tests stay.
- **L6** Next: AUD-13 (dev-tool dependencies).
- **L7** (Owner decision, 2026-11-03) dev deps: "Declarar deps de dev". New root `requirements-dev.txt`; `sync-ideas.py` docstring no longer lists `gspread` (it was never imported). `scripts/derive_payload_manifest.py --check` reports 187 files fresh.
- **L8** Next: AUD-14 (macOS desktop integration).
- **L9** (Owner decision, 2026-11-03) macOS desktop: "Fuera del MVP + no escribir .desktop". Correction to my earlier read: `install_desktop_entry` already returns early unless `OS = Linux`, so no `.desktop` is written on macOS. Documentation only.
- **L10** Next: AUD-15 (fixed ports).
- **L11** AUD-15: no product fork — the env overrides already existed, so this was a documentation gap. Documented `DEMIURGOS_API_PORT`/`DEMIURGOS_GATEWAY_PORT`; also corrected the stale auth default row in both READMEs to `local-dev`.
- **L12** Next: AUD-16 (Windows payload boot test) and AUD-17 (`web-config-ui` tree).
- **L13** (Owner decision, 2026-11-03) `web-config-ui`: "Congelar el árbol". New gate `legacy_tree_frozen` with SHA-256 `ffdb9925…e362f7` over 33 files (line endings normalized). Mutation test added. `EXPECTED_GATES` updated.
- **L14** Next: AUD-16 only. It needs a real Windows payload boot harness; cannot be verified from this Linux host.
