/**
 * Attribution tests — how a report says who sent it, and how that was
 * established (S6).
 *
 * The three levels are exact strings, so they are asserted verbatim:
 *
 *   👤 @user · verified by Telegram     the link came from a Telegram update
 *   👤 Name — declared · local session  no link; the name was typed
 *   👤 owner                            id supplied by relay configuration
 *
 * A configuration value is never presented as Telegram verification, and a
 * verified identity only signs reports when the account granted
 * `report_identity`.
 */

import { test } from "node:test";
import assert from "node:assert/strict";

import {
  readIdentityByInstallToken,
  recordInstallToken,
  revokeIdentity,
  writeIdentity,
  type IdentityRecord,
  type KvLike,
} from "../src/identity.ts";
import { ownerTelegramIds, resolveAttribution } from "../src/attribution.ts";

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

/** Shaped like `randomToken()`: 32 bytes, hex, 64 characters. */
const TOKEN = "0123456789abcdef".repeat(4);
const OTHER_TOKEN = "fedcba9876543210".repeat(4);
const NO_OWNERS: ReadonlySet<string> = new Set<string>();

function linked(overrides: Partial<IdentityRecord> = {}): IdentityRecord {
  return {
    telegram_user_id: "1234567890",
    username: "brook",
    display_name: "Brook",
    account_key: "acct_abc123",
    linked_at: "2026-10-25T12:00:00.000Z",
    started_bots: { ideas: false, reports: true },
    permissions: { report_identity: true, notify_releases: false },
    ...overrides,
  };
}

async function withLink(record = linked(), token = TOKEN): Promise<MemoryKv> {
  const kv = new MemoryKv();
  await writeIdentity(kv, record);
  await recordInstallToken(kv, token, record.telegram_user_id);
  return kv;
}

test("a linked account signs its report as verified by Telegram", async () => {
  const kv = await withLink();

  const attribution = await resolveAttribution(kv, TOKEN, null, NO_OWNERS);

  assert.equal(attribution.level, "verified");
  assert.equal(attribution.line, "👤 @brook · verified by Telegram");
  assert.equal(attribution.tag, "verified by Telegram");
  assert.equal(attribution.label, "@brook");
  assert.equal(attribution.identity?.telegram_user_id, "1234567890");
});

test("without a username the Telegram display name is used, never a invented one", async () => {
  const kv = await withLink(linked({ username: null }));

  const attribution = await resolveAttribution(kv, TOKEN, "maria@example.com", NO_OWNERS);

  assert.equal(attribution.line, "👤 Brook · verified by Telegram");
});

test("without any name the numeric Telegram id is shown", async () => {
  const kv = await withLink(linked({ username: null, display_name: null }));

  const attribution = await resolveAttribution(kv, TOKEN, null, NO_OWNERS);

  assert.equal(attribution.line, "👤 1234567890 · verified by Telegram");
});

test("a configured Owner id is labelled owner, not Telegram verification", async () => {
  const kv = await withLink();

  const attribution = await resolveAttribution(kv, TOKEN, null, ownerTelegramIds("42, 1234567890"));

  assert.equal(attribution.level, "owner");
  assert.equal(attribution.line, "👤 owner");
  assert.equal(attribution.tag, "owner");
  assert.equal(attribution.label, "owner");
});

test("configuration never labels an unlinked report as owner", async () => {
  const kv = new MemoryKv();

  const attribution = await resolveAttribution(kv, null, "Brook", ownerTelegramIds("1234567890"));

  assert.equal(attribution.level, "declared");
  assert.equal(attribution.line, "👤 Brook — declared · local session");
});

test("a typed name with no link is declared, tied to the local session", async () => {
  const kv = new MemoryKv();

  const attribution = await resolveAttribution(kv, null, "Maria", NO_OWNERS);

  assert.equal(attribution.level, "declared");
  assert.equal(attribution.line, "👤 Maria — declared · local session");
  assert.equal(attribution.tag, "declared · local session");
  assert.equal(attribution.label, "Maria");
  assert.equal(attribution.identity, null);
});

test("a token the relay never issued cannot sign anything", async () => {
  const kv = new MemoryKv();

  const attribution = await resolveAttribution(kv, TOKEN, null, NO_OWNERS);

  assert.equal(attribution.level, "none");
  assert.equal(attribution.line, "👤 sin contacto");
});

test("a malformed token is refused before touching the store", async () => {
  const kv = new MemoryKv();

  const attribution = await resolveAttribution(kv, "not-a-token", null, NO_OWNERS);

  assert.equal(attribution.level, "none");
  assert.equal(kv.map.size, 0);
});

test("an account that declined report_identity is rendered as declared", async () => {
  const kv = await withLink(
    linked({ permissions: { report_identity: false, notify_releases: true } }),
  );

  const attribution = await resolveAttribution(kv, TOKEN, "brook", NO_OWNERS);

  assert.equal(attribution.level, "declared");
  assert.equal(attribution.line, "👤 brook — declared · local session");
});

test("after a revoke the same token signs nothing", async () => {
  const kv = await withLink();
  await revokeIdentity(kv, "1234567890");

  const attribution = await resolveAttribution(kv, TOKEN, "Brook", NO_OWNERS);

  assert.equal(attribution.level, "declared");
});

test("no link and no typed name renders the neutral line", async () => {
  const kv = new MemoryKv();

  const attribution = await resolveAttribution(kv, null, null, NO_OWNERS);

  assert.equal(attribution.level, "none");
  assert.equal(attribution.line, "👤 sin contacto");
  assert.equal(attribution.tag, "sin contacto");
  assert.equal(attribution.label, "sin contacto");
});

test("the install token never leaks into the rendered line or label", async () => {
  const kv = await withLink();

  const attribution = await resolveAttribution(kv, TOKEN, "Brook", NO_OWNERS);

  assert.equal(attribution.line.includes(TOKEN), false);
  assert.equal(attribution.label.includes(TOKEN), false);
});

test("the Owner list ignores empty and malformed entries", () => {
  const ids = ownerTelegramIds(" 42 ,, nope, -7 ,1234567890");

  assert.deepEqual([...ids], ["42", "1234567890"]);
  assert.equal(ownerTelegramIds(undefined).size, 0);
  assert.equal(ownerTelegramIds("").size, 0);
});

test("an install token resolves only while it is the account's current one", async () => {
  const kv = await withLink();

  await recordInstallToken(kv, OTHER_TOKEN, "1234567890");

  assert.equal(await readIdentityByInstallToken(kv, TOKEN), null);
  const current = await readIdentityByInstallToken(kv, OTHER_TOKEN);
  assert.equal(current?.account_key, "acct_abc123");
  assert.equal(kv.map.has(`link_token:${TOKEN}`), false);
});

test("revoking an account erases the token lookup, and blocks the dead one", async () => {
  const kv = await withLink();

  await revokeIdentity(kv, "1234567890");

  const keys = [...kv.map.keys()];
  assert.deepEqual(
    keys.filter((key) => !key.startsWith("blocked:")),
    [],
  );
  assert.equal(await readIdentityByInstallToken(kv, TOKEN), null);
  // A digest, with a bounded life: the guard outlives the link, the token does not.
  assert.equal(keys.filter((key) => key.startsWith("blocked:")).length, 1);
  assert.equal(keys.some((key) => key.includes(TOKEN)), false);
});
