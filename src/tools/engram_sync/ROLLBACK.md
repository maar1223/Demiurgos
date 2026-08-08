# Engram Sync Worker Rollback

The worker is fail-closed. A scan or session-start check never writes to local files, Engram, or `.demiurgos-sync/`.

## Disable Triggers

1. Stop the daemon through its owner, then verify `Daemon.health()` reports `stopped` and no trigger is running.
2. Remove or disable the external watcher/poller launch only after recording the health result.
3. Do not run `confirm` while recovery evidence, source revisions, or Engram availability are uncertain.

## Recover Safely

- Preserve `.demiurgos-sync/journal.jsonl`; it is the idempotency and recovery record.
- Inspect unresolved `planned`, `confirmed`, or `failed` entries before retrying. An unresolved entry blocks replay until its source and target are re-scanned.
- Re-run `python -m engram_sync --root . scan --session-start` with `PYTHONPATH=src/tools` to obtain a read-only report.
- Treat changed source revisions, conflicts, malformed confirmation documents, unavailable Engram, and incomplete journal evidence as blocked states.
- Never delete a journal row to force a retry and never reverse a write by hand. A reversal is a new reviewed operation with a new source revision and explicit `APPLY` confirmation.

## Data Safety

Rollback disables triggers; it does not restore a winner or bulk-migrate data. If an apply result is uncertain, leave both stores untouched, retain the journal, and stop for author/orchestrator review. Real recovery requires a fresh report, explicit authorization, and a successful post-apply journal transition.
