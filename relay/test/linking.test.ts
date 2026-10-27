/**
 * Linking-flow tests — tickets, redemption, one-time token handover, revoke.
 *
 * Run with: `npm test`. The clock is injected, so expiry is tested by moving
 * time, never by sleeping.
 */

import { test } from "node:test";
import assert from "node:assert/strict";

import { readIdentity, readIdentityByAccount, type KvLike } from "../src/identity.ts";
import {
  LINK_START_MAX_PER_HOUR,
  LinkError,
  linkStatus,
  redeemTicket,
  revokeLink,
  startLink,
} from "../src/linking.ts";

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

const T0 = new Date("2026-10-25T12:00:00.000Z");

function later(minutes: number): Date {
  return new Date(T0.getTime() + minutes * 60_000);
}

function telegram(id = "1234567890") {
  return { id, username: "brook", displayName: "Brook" };
}

test("startLink mints a ticket and reuses it while it is live", async () => {
  const kv = new MemoryKv();

  const first = await startLink(kv, { account_key: "acct_abc123" }, T0);
  const second = await startLink(kv, { account_key: "acct_abc123" }, later(2));

  assert.equal(first.reused, false);
  assert.equal(second.reused, true);
  assert.equal(second.ticket, first.ticket);
  assert.equal(second.expires_at, first.expires_at);
});

test("reuse never burns the hourly allowance", async () => {
  const kv = new MemoryKv();

  for (let i = 0; i < LINK_START_MAX_PER_HOUR + 3; i += 1) {
    await startLink(kv, { account_key: "acct_abc123" }, later(i));
  }

  const counter = kv.map.get("linkstart:acct_abc123");
  assert.equal(counter, "1");
});

test("minting a fourth ticket in the hour is rate limited", async () => {
  const kv = new MemoryKv();

  for (let i = 0; i < LINK_START_MAX_PER_HOUR; i += 1) {
    await startLink(kv, { account_key: "acct_abc123" }, later(i));
    // A consumed ticket is not reusable, so each loop mints a fresh one.
    await redeemTicket(kv, kv.map.get(`ticket:pending:acct_abc123`)!, telegram("10000000" + i), later(i));
    await kv.delete("ticket:pending:acct_abc123");
  }

  await assert.rejects(
    () => startLink(kv, { account_key: "acct_abc123" }, later(5)),
    (error: unknown) => error instanceof LinkError && error.code === "link.rate_limited",
  );
});

test("startLink refuses only what a KV key cannot hold", async () => {
  const kv = new MemoryKv();

  for (const bad of ["", " ana", "ana\u0000x", "x".repeat(401)]) {
    await assert.rejects(
      () => startLink(kv, { account_key: bad }, T0),
      (error: unknown) => error instanceof LinkError && error.code === "link.invalid_account",
      `expected ${JSON.stringify(bad)} to be refused`,
    );
  }
});

test("a vault username is a valid account key, including spaces and @", async () => {
  const kv = new MemoryKv();

  for (const key of ["ana", "Mr. Smith", "jose@example.com"]) {
    const started = await startLink(kv, { account_key: key }, T0);
    assert.equal(typeof started.ticket, "string", `${key} was refused`);
  }
});

test("explicit permissions on a reused ticket are honored, not dropped", async () => {
  const kv = new MemoryKv();
  await startLink(kv, { account_key: "acct_abc123" }, T0);

  const reused = await startLink(
    kv,
    { account_key: "acct_abc123", report_identity: false, notify_releases: false },
    later(1),
  );
  assert.equal(reused.reused, true);

  const identity = await redeemTicket(kv, reused.ticket, telegram(), later(2));
  assert.deepEqual(identity.permissions, {
    report_identity: false,
    notify_releases: false,
  });
});

test("revoke invalidates an outstanding ticket instead of leaving it redeemable", async () => {
  const kv = new MemoryKv();
  const { ticket } = await startLink(kv, { account_key: "acct_abc123" }, T0);

  await revokeLink(kv, "acct_abc123");

  await assert.rejects(
    () => redeemTicket(kv, ticket, telegram(), later(1)),
    (error: unknown) => error instanceof LinkError && error.code === "link.ticket_invalid",
  );
  assert.equal(kv.map.has(`ticket:${ticket}`), false);
  assert.equal(kv.map.has("ticket:pending:acct_abc123"), false);
});

test("redeem binds the identity and the poll hands over the token exactly once", async () => {
  const kv = new MemoryKv();
  const { ticket } = await startLink(kv, { account_key: "acct_abc123" }, T0);

  const identity = await redeemTicket(kv, ticket, telegram(), later(1));
  assert.equal(identity.account_key, "acct_abc123");
  assert.equal(identity.telegram_user_id, "1234567890");
  assert.deepEqual(identity.started_bots, { ideas: false, reports: true });
  assert.deepEqual(identity.permissions, {
    report_identity: true,
    notify_releases: true,
  });
  assert.deepEqual(await readIdentityByAccount(kv, "acct_abc123"), identity);

  const first = await linkStatus(kv, ticket, later(2));
  assert.equal(first.state, "linked");
  assert.ok(first.state === "linked" && typeof first.install_token === "string");
  assert.ok(first.state === "linked" && first.install_token!.length === 64);

  const second = await linkStatus(kv, ticket, later(3));
  assert.equal(second.state, "linked");
  assert.equal(second.state === "linked" ? second.install_token : "x", null);
});

test("permissions can be granted separately at start", async () => {
  const kv = new MemoryKv();
  const { ticket } = await startLink(
    kv,
    { account_key: "acct_abc123", notify_releases: false },
    T0,
  );

  const identity = await redeemTicket(kv, ticket, telegram(), later(1));

  assert.deepEqual(identity.permissions, {
    report_identity: true,
    notify_releases: false,
  });
});

test("a repeated /start from the same account is success, not an error", async () => {
  const kv = new MemoryKv();
  const { ticket } = await startLink(kv, { account_key: "acct_abc123" }, T0);

  const first = await redeemTicket(kv, ticket, telegram(), later(1));
  const again = await redeemTicket(kv, ticket, telegram(), later(2));

  assert.deepEqual(again, first);
});

test("a ticket already claimed by another Telegram account is refused", async () => {
  const kv = new MemoryKv();
  const { ticket } = await startLink(kv, { account_key: "acct_abc123" }, T0);
  await redeemTicket(kv, ticket, telegram(), later(1));

  await assert.rejects(
    () => redeemTicket(kv, ticket, telegram("999999999"), later(2)),
    (error: unknown) => error instanceof LinkError && error.code === "link.ticket_consumed",
  );
});

test("an expired ticket cannot be redeemed and reads as expired", async () => {
  const kv = new MemoryKv();
  const { ticket } = await startLink(kv, { account_key: "acct_abc123" }, T0);

  await assert.rejects(
    () => redeemTicket(kv, ticket, telegram(), later(11)),
    (error: unknown) => error instanceof LinkError && error.code === "link.ticket_expired",
  );
  assert.equal((await linkStatus(kv, ticket, later(11))).state, "expired");
  assert.equal(await readIdentity(kv, "1234567890"), null);
});

test("an unknown ticket reads as expired", async () => {
  const kv = new MemoryKv();

  assert.equal((await linkStatus(kv, "ZZZZZZZZ", T0)).state, "expired");
});

test("revokeLink erases the binding and the pending ticket", async () => {
  const kv = new MemoryKv();
  const { ticket } = await startLink(kv, { account_key: "acct_abc123" }, T0);
  await redeemTicket(kv, ticket, telegram(), later(1));

  assert.equal(await revokeLink(kv, "acct_abc123"), true);
  assert.equal(await readIdentityByAccount(kv, "acct_abc123"), null);
  assert.equal(await readIdentity(kv, "1234567890"), null);
  assert.equal(kv.map.has("ticket:pending:acct_abc123"), false);
  assert.equal(await revokeLink(kv, "acct_abc123"), false);
});

test("a telegram account moving to another account key leaves no stale pointer", async () => {
  const kv = new MemoryKv();
  const first = await startLink(kv, { account_key: "acct_first01" }, T0);
  await redeemTicket(kv, first.ticket, telegram(), later(1));

  const second = await startLink(kv, { account_key: "acct_second1" }, later(2));
  await redeemTicket(kv, second.ticket, telegram(), later(3));

  assert.equal(kv.map.has("identity:acct:acct_first01"), false);
  assert.equal((await readIdentityByAccount(kv, "acct_first01")), null);
  assert.equal(
    (await readIdentityByAccount(kv, "acct_second1"))?.account_key,
    "acct_second1",
  );
});

test("an omitted flag keeps the stored value and a flagless reuse changes nothing", async () => {
  const kv = new MemoryKv();
  await startLink(
    kv,
    { account_key: "acct_abc123", report_identity: false, notify_releases: false },
    T0,
  );
  await startLink(kv, { account_key: "acct_abc123", notify_releases: true }, later(1));
  const { ticket } = await startLink(kv, { account_key: "acct_abc123" }, later(2));

  const identity = await redeemTicket(kv, ticket, telegram(), later(3));

  assert.deepEqual(identity.permissions, {
    report_identity: false,
    notify_releases: true,
  });
});

test("the stored identity carries account_key and never principal_id", async () => {
  const kv = new MemoryKv();
  const { ticket } = await startLink(kv, { account_key: "Mr. Smith" }, T0);
  await redeemTicket(kv, ticket, telegram(), later(1));

  const raw = JSON.parse(kv.map.get("identity:tg:1234567890")!);

  assert.equal(raw.account_key, "Mr. Smith");
  assert.equal(Object.prototype.hasOwnProperty.call(raw, "principal_id"), false);
});
