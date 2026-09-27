# Hermes Telegram bot — trimmed command menu + passive TTS with language-based voice

## Objective

Make the Demiurgos Telegram bot's surface match its real design:

1. Reduce the visible `/` command menu from 60 English Hermes commands to exactly
   four: `/stop`, `/new`, `/retry`, `/voice`.
2. Enable **passive** text-to-speech (voice only on request: typed text or
   `/voice`), with the Edge TTS voice chosen from the Demiurgos UI language
   (`es` → Spanish voice, `en` → English voice).

## Problem / Why

- The bot's `/` menu is filled entirely by Hermes' built-in `COMMAND_REGISTRY`
  (66 core commands; the default cap of 60 shows 60, all English). None of them
  belongs to Demiurgos, and most are dev/ops noise for an author-facing intake
  bot whose real bridge to the Taller de Ideas is the Guardar/Descartar keyboard
  plus the `capture_idea`/`update_idea` tools.
- TTS works out of the box (Edge provider, free, `edge-tts` 7.2.7 installed) but
  the default voice is `en-US-AriaNeural` (English), so Spanish output sounds
  wrong. Hermes has no native per-language voice selection: voice/provider are
  static config, "not model-selected".

## Scope

In scope:

- T1. A repo-hosted voice-selection wrapper script.
- T2. Unit tests for its pure logic (language resolution + voice mapping).
- T3. Live Hermes config (`~/.hermes/config.yaml`, outside the repo): the
  `command_menu` block and the `tts` command provider.

Out of scope (explicitly decided):

- No auto voice reply on inbound voice notes (passive only).
- No slash commands of our own (the Taller is conversational via MCP tools).
- No SDD: bounded config + one small script.

## Constraints / Verified facts

- `ffmpeg` is installed (`/usr/bin/ffmpeg` 6.1.1) → mp3→Ogg/Opus voice bubbles OK.
- `platformdirs` is **missing** in the Hermes venv → the wrapper MUST NOT import
  repo modules (`data_root`/`demiurgos_language`); it resolves the language from
  `DEMIURGOS_LANGUAGE` (env) or `$DEMIURGOS_ROOT/.env`, defaulting to `es`.
- `DEMIURGOS_ROOT` is exported by `scripts/start-demiurgos-linux.sh` for the
  gateway child only; `${env:DEMIURGOS_ROOT}` in config resolves under the
  launcher.
- `edge-tts` lives in the Hermes venv; the wrapper locates the binary via
  `shutil.which("edge-tts")` with a documented fallback path.
- Hidden commands remain typed-dispatchable; only the `/` picker is trimmed.
- A gateway restart is required for menu/TTS changes to take effect.

## Voice mapping (verified online against Edge's catalog)

- `es` → `es-MX-DaliaNeural` (neutral Latin-American). Alternative documented:
  `es-AR-ElenaNeural` (Argentine).
- `en` → `en-US-AriaNeural` (Hermes default).
- Anything else → `es` fallback.

## Tasks

- [ ] **T1** — `scripts/hermes_tts_voice.py`: resolve language (env → `$DEMIURGOS_ROOT/.env`
  → `es`), map language → Edge voice, synthesize `{input_path}` → `{output_path}`
  via the `edge-tts` binary. Stdlib only; no repo imports.
- [ ] **T2** — `tests/test_hermes_tts_voice.py`: unit-test language resolution and
  voice mapping (including the `es` default and unknown-language fallback), and
  the synthesis call with the edge-tts subprocess mocked.
- [ ] **T3** — Edit `~/.hermes/config.yaml` (with a backup):
  - `platforms.telegram.extra.command_menu` = `{max_commands: 4, priority_mode: replace,
    priority: [stop, new, retry, voice]}`.
  - `tts` command provider `demiurgos_voice` pointing at the wrapper, with
    `voice_compatible: true`, `output_format: mp3`, `timeout: 180`,
    `env_passthrough: [DEMIURGOS_ROOT, DEMIURGOS_DATA_ROOT, DEMIURGOS_LANGUAGE]`.
- [ ] **T4** — Restart the gateway and verify: menu shows exactly the four
  commands; a TTS request speaks in the Demiurgos language.

## Acceptance criteria

- The Telegram `/` picker shows exactly `/stop`, `/new`, `/retry`, `/voice`.
- Typing a hidden command (e.g. `/status`) still works.
- With `DEMIURGOS_LANGUAGE=es`, a voice request produces Spanish audio; with `en`,
  English audio.
- The voice arrives as a Telegram voice bubble (Ogg/Opus).
- Repo tests pass; no repo module is imported by the wrapper.

## Route (ODD)

- Delegated direct: one `explore` (done) + one `general` writer for T1/T2.
- Parent: T3 live config edit + T4 restart guidance.

## Progress

- 2026-09-27 — Explore complete; risks resolved (ffmpeg present, platformdirs gap
  identified, Edge voices verified). Branch `feat/hermes-telegram-voice` created.
- 2026-09-27 — T1/T2 done. `scripts/hermes_tts_voice.py` (stdlib only, no repo
  imports) + `tests/test_hermes_tts_voice.py`. Independent verifier found 3
  defects (stale-output false success, unhandled spawn `OSError`, unhandled
  non-UTF-8 input); all fixed with regression tests. 34 tests pass.
  Real end-to-end verified: `es` → es-MX-DaliaNeural, `en` → en-US-AriaNeural,
  both produce valid MP3 (ffprobe).
- 2026-09-27 — T3 done. `~/.hermes/config.yaml` edited (backup
  `config.yaml.bak-20260927-181845`). Validated with Hermes' own code:
  `telegram_menu_commands` → exactly `[stop, new, retry, voice]` (167 hidden);
  `tts.providers.demiurgos_voice` loads with `${env:DEMIURGOS_ROOT}` expanded.
- Pending: T4 — gateway restart (owner action) and live confirmation.

## Evidence

- Tests: `.venv/bin/pytest tests/test_hermes_tts_voice.py -q` → 34 passed.
- Menu: `telegram_menu_max_commands()` = 4; `telegram_menu_commands(4)` = the 4.
- Assess (RDD off): risk `high` (`process_boundary`/`shell_process`); independent
  verifier PASS-with-caveats, defects fixed.
