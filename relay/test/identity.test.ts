/**
 * Identity store tests — pure logic over an injected KV surface.
 *
 * Run with: `npm test` (node --experimental-strip-types --test).
 * The store never talks to the Workers runtime, so an in-memory Map is enough
 * to pin the record shape, the lookup pointers and the fail-closed reads.
 */

import { test } from "node:test";
import assert from "node:assert/strict";

import {
  identityKeyForAccount,
  identityKeyForTelegram,
  markBotStarted,
  readIdentity,
  readIdentityByAccount,
  revokeIdentity,
  writeIdentity,
  type IdentityRecord,
  type KvLike,
} from "../src/identity.ts";

class MemoryKv implements KvLike {
  readonly map = new Map<string, string>();

  async get(key: string): Promise<string | null> {
    return this.map.get(key) ?? null;
  }

  async put(key: string, value: string): Promise<void> {
    this.map.set(key, value);
  }

  async delete(key: string): Promise<void> {
    this.map.delete(key);
  }
}

function record(overrides: Partial<IdentityRecord> = {}): IdentityRecord {
  return {
    telegram_user_id: "1234567890",
    username: "brook",
    display_name: "Brook",
    account_key: "prin_abc123",
    linked_at: "2026-10-25T12:00:00.000Z",
    started_bots: { ideas: false, reports: true },
    permissions: { report_identity: true, notify_releases: true },
    ...overrides,
  };
}

test("keys are namespaced per lookup direction", () => {
  assert.equal(identityKeyForTelegram("42"), "identity:tg:42");
  assert.equal(identityKeyForAccount("prin_abc123"), "identity:acct:prin_abc123");
});

test("write then read round-trips by telegram id and by account key", async () => {
  const kv = new MemoryKv();
  await writeIdentity(kv, record());

  const byTelegram = await readIdentity(kv, "1234567890");
  const byPrincipal = await readIdentityByAccount(kv, "prin_abc123");

  assert.deepEqual(byTelegram, record());
  assert.deepEqual(byPrincipal, record());
});

test("a malformed stored value reads as absent, never throws", async () => {
  const kv = new MemoryKv();
  kv.map.set(identityKeyForTelegram("777"), "{not json");

  assert.equal(await readIdentity(kv, "777"), null);
});

test("a dangling account pointer reads as absent", async () => {
  const kv = new MemoryKv();
  kv.map.set(identityKeyForAccount("prin_ghost"), "999");

  assert.equal(await readIdentityByAccount(kv, "prin_ghost"), null);
});

test("revoke removes both directions so the account is unlinked", async () => {
  const kv = new MemoryKv();
  await writeIdentity(kv, record());

  await revokeIdentity(kv, "1234567890");

  assert.equal(await readIdentity(kv, "1234567890"), null);
  assert.equal(await readIdentityByAccount(kv, "prin_abc123"), null);
  assert.equal(kv.map.has(identityKeyForTelegram("1234567890")), false);
  assert.equal(kv.map.has(identityKeyForAccount("prin_abc123")), false);
});

test("relinking the same account key keeps the newest telegram identity", async () => {
  const kv = new MemoryKv();
  await writeIdentity(kv, record());
  await writeIdentity(kv, record({ telegram_user_id: "555000111" }));

  const byPrincipal = await readIdentityByAccount(kv, "prin_abc123");
  assert.equal(byPrincipal?.telegram_user_id, "555000111");
});

test("markBotStarted flips one bot and preserves everything else", async () => {
  const kv = new MemoryKv();
  await writeIdentity(kv, record({ started_bots: { ideas: false, reports: false } }));

  const updated = await markBotStarted(kv, "1234567890", "reports");

  assert.deepEqual(updated?.started_bots, { ideas: false, reports: true });
  assert.deepEqual(updated?.permissions, record().permissions);
  assert.deepEqual(await readIdentity(kv, "1234567890"), updated);
});

test("markBotStarted on an unknown identity returns null and writes nothing", async () => {
  const kv = new MemoryKv();

  assert.equal(await markBotStarted(kv, "404404404", "ideas"), null);
  assert.equal(kv.map.size, 0);
});

test("writeIdentity refuses a non-numeric telegram id and an empty account key", async () => {
  const kv = new MemoryKv();

  await assert.rejects(() => writeIdentity(kv, record({ telegram_user_id: "abc" })));
  await assert.rejects(() => writeIdentity(kv, record({ telegram_user_id: "-5" })));
  await assert.rejects(() => writeIdentity(kv, record({ account_key: "  " })));
  assert.equal(kv.map.size, 0);
});
