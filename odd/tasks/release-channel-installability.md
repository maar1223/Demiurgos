# Release channel installability — make the public channel serve a complete, verifiable installer tree

Branch: `fix/release-channel-installability` (from `master` @ `abc7abf`). PR: #77. Delivery: `ask-on-risk` (`size:exception` requested: 1113 changed lines, no cohesive split under 400).
Runners: `pytest src/tools/demiurgos-suite/wiki/tests/` (backend), `gh run` for CI/release.

## Specs

- **S1** The default channel base is a raw branch root:
  `https://raw.githubusercontent.com/<owner>/demiurgos-releases/main` in `install.sh`,
  `install.ps1` and `DEFAULT_CHANNEL_URL` in `src/tools/demiurgos-suite/wiki/updater.py`.
  The owner stays assembled from parts (`"maar12""23"`), so the literal address never
  appears in a public file. `DEMIURGOS_URL_BASE` remains the override/test seam.
- **S2** After a publish, the channel branch root contains:
  `install.sh`, `install.ps1`, `scripts/install-demiurgos.sh`, `scripts/install-demiurgos.ps1`,
  `scripts/lib/verify_checksum.sh`, `scripts/lib/verify_checksum.ps1`,
  `scripts/provision-hermes.sh`, `scripts/provision-hermes.ps1`,
  `uv/uv-<uv_target>-<uv_version>.(tar.gz|zip)` for the four supported targets,
  `uv-shas.env`, the four `demiurgos-app-<version>-<cell>.(tar.gz|zip)` payloads,
  `version.json`, `SHA256SUMS`, `SHA256SUMS.minisig`, and the `latest` / `latest-beta`
  pointers. Each publish writes only its classified pointer and leaves the other intact;
  pointers are excluded from the signed manifest (they move after signing). When no stable
  release exists yet, a default install resolves `latest-beta` and prints a note.
- **S3** `uv-shas.env` holds one `KEY=<64 lowercase hex>` line per supported uv target:
  `UV_SHA_X86_64_LINUX_GNU`, `UV_SHA_AARCH64_LINUX_GNU`, `UV_SHA_AARCH64_DARWIN`,
  `UV_SHA_X86_64_WINDOWS_MSVC`, each the SHA-256 of that archive, with `UV_VERSION=0.5.24`.
- **S4** Both installer cores download `uv-shas.env`, verify it against the signed
  `SHA256SUMS` BEFORE trusting any value, parse ONLY whitelisted `UV_SHA_*` keys whose value
  is exactly 64 hex characters, and export them. `DEMIURGOS_UV_SHA256` still overrides for
  tests. A missing, unsigned, unlisted or malformed `uv-shas.env`, or a missing key for the
  host target, fails closed with an actionable message; the installer never executes an
  unverified uv.
- **S5** The publish job regenerates `SHA256SUMS` over the WHOLE channel tree (every file
  except `SHA256SUMS` and `SHA256SUMS.minisig`, names without a leading `./`), signs it,
  pushes the tree to the branch WITHOUT moving pointers, and creates the GitHub release for
  traceability. Older payloads stay listed, so an install pinned to an older version keeps
  working.
- **S6** The anonymous smoke installs from the real raw branch — no `file://` fixture and no
  `DEMIURGOS_UV_SHA256` override — with `DEMIURGOS_VERSION=<tag>`, then boots and expects
  `/health` and `/` to answer 200.
- **S7** Pointer gating is enforced on the raw branch: a stable tag moves only `latest` to its
  version; a prerelease tag moves only `latest-beta` and leaves `latest` untouched.
- **S8** Payload selection is platform-correct: POSIX picks
  `demiurgos-app-<version>-<cell>.<ext>` from `SHA256SUMS` for `linux-x86_64`,
  `linux-aarch64` or `macos-arm64` (host-derived, with the release matrix's own cell
  names — `macos-arm64`, never a mechanical arch transform); Windows picks
  `windows-amd64`. When that entry is absent (older channels), both cores fall back to
  `version.json` and then to the legacy flat name, so old fixtures/channels keep
  installing.
- **S9** Docs match the shipped commands: `docs/install/ONE_SCREEN_GUIDE.md` uses the raw
  branch one-liners; `docs/RELEASING.md` describes the channel tree and the two pointers.
- **S10** Tests pin S1, S3, S4, S8: uv-shas.env verified+parsed, tampered/missing/invalid
  fails closed, cell selection per simulated platform, default base; the full backend suite is
  green.

## Tasks

- T1 — uv-shas.env consumption in both cores (S3, S4). Route: inline. **Done**; tests `TestUvShasEnv` (signed table installs without the seam; missing/tampered/malformed fail closed).
- T2 — platform-correct payload selection in both cores (S8). Route: inline. **Done**; `test_cell_named_payload_is_preferred_over_version_json`; legacy fallback keeps old fixtures green.
- T3 — raw-branch defaults in both bootstraps and the updater (S1). Route: inline. **Done**; `test_bootstrap_defaults_to_the_raw_channel_branch`, `test_default_channel_url_is_the_raw_channel_branch`.
- T4 — release workflow: channel tree assembly, uv archives, uv-shas.env, full-tree signing, branch push, release assets, real-channel smoke, pointer job (S2, S5, S6, S7). Route: inline. **Done**; `test_channel_tree_is_the_documented_flat_branch`, `test_smoke_installs_from_the_real_raw_channel`, updated beta-gate tests.
- T5 — docs (S9). Route: inline. **Done**: install one-liners on the raw branch; RELEASING channel-tree section; runbook updated.
- T6 — tests + full suite + independent verification (S10). Route: inline + verifier. **Done**: 4888 passed / 26 skipped after the correction batch; independent verifier reported S1/S3/S4/S5/S6/S7/S9 met, and its two blockers (S8 cell name, S2 beta-first pointer) were fixed with committed regression tests.

## Log

- **L1** (Owner): "sigamos desde checkpoint"
- **D1** Design deviation from checkpoint plan item 1: ONE channel branch (`main`), not
  `main` + `beta`. Reason: with two branches the base URL recorded in `channel.json` cannot
  serve the other channel, so switching Estable→Beta would apply a version whose payload does
  not exist on the recorded base. One branch hosts both pointers and all payloads (names are
  versioned), so channel switching and pinned installs both work with a single base.
  Checkpoint's goal (raw-branch channel, uv SHAs baked, working defaults) is preserved.
- **D2** The pointer movement stays gated on the smoke: the tree is pushed first (additive,
  old pointer intact), the smoke installs the new version explicitly, and only then a separate
  job moves `latest`/`latest-beta`.
- **D3** SHA256SUMS is regenerated over the whole branch tree instead of being assembled from
  this run's artifacts, so `uv-shas.env`, scripts and older payloads are all covered and older
  versions remain installable.
- **D4** The uv key names are explicit (`UV_SHA_X86_64_LINUX_GNU`, `UV_SHA_AARCH64_LINUX_GNU`,
  `UV_SHA_AARCH64_DARWIN`, `UV_SHA_X86_64_WINDOWS_MSVC`), not a mechanical upper-case of the
  uv target triple: the installer's contract drops the `unknown`/`pc` infix, and a blind
  transform silently produced keys the core never reads.
- **E1** Full backend suite: 4879 passed, 26 skipped, plus one stale expectation in
  `test_payload_audit.py` that asserted the old "no uv checksum available" stop; updated to the
  new fail-closed `uv-shas.env` stop (the gates-crossed intent is preserved) and re-run green.
- **E2** RDD status is `unavailable` on this checkout: `gentle-ai review mode status` fails
  because the repository lives on a FUSE/ntfs-3g mount with a fixed owner projection, so native
  review cannot be resolved. Treated as unknown; no review authority exists and none is
  fabricated. Independent verification still runs (Risk: high-risk items 3 and 5).
- **E3** Test-first disclosure: the new uv-shas and payload-cell tests were written alongside the
  implementation, so no RED was captured for them. A real RED was observed for the stale
  `test_payload_audit.py` expectation after the behavior changed, and it was corrected against
  the new contract.
- **VER1** Independent verification (gentle-ai-verify) reported two blockers and three advisories.
  Fixed in the correction batch:
  - **S8 blocker** — the core derived `macos-aarch64` while the matrix publishes `macos-arm64`,
    so Apple Silicon fell back to the Linux payload or failed closed. `payload_cell` now maps
    Darwin arm64 to `macos-arm64` (no arch transform), the fixture helper matches, and
    `test_release_channel_verifier.py` pins every matrix cell against the core's own derivation.
  - **S2 blocker** — a beta-first channel left `latest` absent and the default install
    unresolvable. Both cores now fall back to `latest-beta` with a visible note when no stable
    pointer exists; pointers stay out of the signed manifest (they move after signing), and the
    pointer job writes only the classified pointer. Regression tests: version-fallback cells in
    `test_installer_contract.py`, pointer contract in `test_release_channel_verifier.py`.
  - **Advisory** — Windows uv-shas whitelist tightened to the same explicit key list as POSIX.
  - **Advisory** — pointer/manifest drift removed by excluding `latest`/`latest-beta` from
    `SHA256SUMS`; documented in `docs/RELEASING.md`.
  - **Accepted as out of scope** — `scripts/provision-hermes.*` contains the literal private
    address; pre-existing at the baseline and outside the bootstrap scope.
- **E4** Full backend suite after the correction batch: `.venv/bin/python -m pytest src/tools/demiurgos-suite/wiki/tests/ -q` -> 4888 passed, 26 skipped (330.99s). `bash -n` both cores and the workflow YAML parse are green; Windows execution is unverified on this host (no pwsh).
- **E5** First live publish (`v0.2.1`, run 41760632375): packaging and publish succeeded — the flat tree is live on the branch and the release exists — but the anonymous smoke failed because the smoke runner no longer had `minisign` installed, which the consumer requires. The pointer was correctly NOT moved. Added the minisign prerequisite step to the smoke job plus a regression test. Verified the live channel anonymously from the authoring host: manifest signature verified, eight listed artifacts checksum-verified, and a real install of 0.2.1 from the public raw URL booted `/health` and `/` with 200 (Hermes provisioning skipped locally).
- **VER2** Focused recheck of the two blockers: both FIXED, no new blocker. macOS cell derivation matches all four matrix cells; a beta-only `file://` channel installs by default with the visible note while a channel with neither pointer fails with the actionable message; stable wins when both pointers exist; the signed manifest excludes the pointers and self-verifies; the pointer job writes only the classified pointer. Windows remains text-only (no pwsh).
