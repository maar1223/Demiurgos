# Release channel installability — make the public channel serve a complete, verifiable installer tree

Branch: `fix/release-channel-installability` (from `master` @ `abc7abf`). Delivery: `ask-on-risk`.
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
  `version.json`, `SHA256SUMS`, `SHA256SUMS.minisig`, `latest`, `latest-beta`.
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
  `linux-aarch64` or `macos-arm64` (host-derived); Windows picks `windows-amd64`. When that
  entry is absent (older channels), both cores fall back to `version.json` and then to the
  legacy flat name, so old fixtures/channels keep installing.
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
- T6 — tests + full suite + independent verification (S10). Route: inline + verifier. **In progress**: suite 4879 passed / 26 skipped with the one stale payload-audit expectation, fixed and re-run green (65 passed / 6 skipped).

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
