# MVP readiness audit — wave 3 (AUD-11 … AUD-17)

Branch: `fix/mvp-audit-wave-3` · Base: `master` (`1165120`) · Delivery: work-unit commits on the feature branch; merge and push are the Owner's decision. Runner: `.venv/bin/python -m pytest`.

## Specs

- **S1 (AUD-11) — relay CI job.** `.github/workflows/ci.yml` runs the separately-deployed Cloudflare Worker's tests and typecheck on Node 22 (the relay's `--experimental-strip-types` test runner needs it). Acceptance: the `relay` job exists and its commands pass locally.
- **S2 (AUD-12) — `engram_sync` promise.** PENDING Owner decision: wire the documented worker into a launcher, or retire the README promise. Acceptance from the audit: the promise matches what actually runs.
- **S3 (AUD-13) — dev-tool dependencies.** PENDING Owner decision: declare `googleapiclient` / `faster_whisper` in a dev requirements file, or retire the scripts. Acceptance: no undeclared import in shipped tooling.
- **S4 (AUD-14) — macOS desktop integration.** PENDING Owner decision: add a `.app`/alias or declare it out of MVP scope. Acceptance: the desktop story matches the shipped artifacts.
- **S5 (AUD-15) — fixed ports.** PENDING Owner decision: document the overrides, or choose a free port when 8000/8642 are taken. Acceptance: a foreign process on a default port does not leave the app unusable without guidance.
- **S6 (AUD-16) — Windows payload boot test.** The packaged Windows payload has no real boot test; the fixture fabricates the layout. Acceptance: the packaged Windows bundle boots in CI or a documented harness.
- **S7 (AUD-17) — retired `web-config-ui` tree.** PENDING Owner decision: freeze the tree or retire it entirely. Acceptance: the historical tree cannot drift again.

## Tasks

- T1 — AUD-11 relay CI — inline — done; local `npm test` 143 passed, `npm run typecheck` clean.
- T2 — AUD-12 — blocked on S2 decision.
- T3 — AUD-13 — blocked on S3 decision.
- T4 — AUD-14 — blocked on S4 decision.
- T5 — AUD-15 — blocked on S5 decision.
- T6 — AUD-16 — not started (needs a Windows runner).
- T7 — AUD-17 — blocked on S7 decision.

## Log

- **L1** Checkpoint continuation: wave 3 is the next step after waves 0, 1 and 2. Owner instruction this session, verbatim: "continua desde checkpoint. Ah y por cierto el ES-AR ya no lo quiero, prefiero solo español neutro".
- **L2** Wave 3 backlog from `docs/MVP_READINESS_AUDIT.md`: AUD-11 relay CI, AUD-12 `engram_sync`, AUD-13 dev deps, AUD-14 macOS desktop, AUD-15 ports, AUD-16 Windows payload, AUD-17 `web-config-ui`.
- **L3** AUD-11 implemented: new `relay` job (Node 22, `npm install` because no lockfile is committed, `npm test`, `npm run typecheck`). Local evidence: 143 tests pass, typecheck clean.
- **L4** Next: Owner decisions for S2..S5 and S7; S6 needs a Windows CI boot harness.
