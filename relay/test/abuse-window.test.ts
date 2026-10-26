/**
 * Window regressions kept from independent verification.
 *
 * The blocker: a counter rewrite also rewrites its expiry, so a caller refused
 * at the limit that kept retrying pushed the window forward on every attempt
 * and could never get through. `admitCounter` reads first and only writes when
 * there is room; these tests use a KV that actually honours TTLs, so the window
 * can roll without sleeping.
 */

import { test } from "node:test";
import assert from "node:assert/strict";

import { admitReport } from "../src/abuse.ts";
import { LINK_START_MAX_PER_HOUR, LinkError, startLink } from "../src/linking.ts";
import type { KvLike } from "../src/identity.ts";

class TtlKv implements KvLike {
  readonly map = new Map<string, string>();
  readonly expires = new Map<string, number>();
  now = 0;

  async get(key: string): Promise<string | null> {
    const expiry = this.expires.get(key);
    if (expiry !== undefined && expiry <= this.now) {
      this.map.delete(key);
      this.expires.delete(key);
      return null;
    }
    return this.map.get(key) ?? null;
  }

  async put(
    key: string,
    value: string,
    options?: { expirationTtl?: number },
  ): Promise<void> {
    this.map.set(key, value);
    if (options?.expirationTtl !== undefined) {
      this.expires.set(key, this.now + options.expirationTtl * 1000);
    }
  }

  async delete(key: string): Promise<void> {
    this.map.delete(key);
    this.expires.delete(key);
  }
}

const T0 = Date.parse("2026-10-25T10:00:00Z");
const MINUTE = 60_000;

function report(description: string) {
  return { description, platform: {}, logs: null };
}

test("the principal hour rolls; a refused retry does not extend the lockout", async () => {
  const kv = new TtlKv();
  kv.now = T0;

  for (let i = 0; i < 5; i += 1) {
    const admission = await admitReport(kv, report(`r${i}`), "acct", new Date(kv.now));
    assert.equal(admission.verdict, "accepted", `report ${i} was refused`);
  }

  kv.now = T0 + 30 * MINUTE;
  assert.deepEqual(await admitReport(kv, report("r5"), "acct", new Date(kv.now)), {
    verdict: "limited",
    code: "relay.rate_limited",
  });

  // The refusal above must not have moved the window: the five accepted
  // reports' hour ended at 11:00.
  kv.now = T0 + 61 * MINUTE;
  assert.equal(
    (await admitReport(kv, report("r6"), "acct", new Date(kv.now))).verdict,
    "accepted",
  );
});

test("hammering the limit never extends the window it is refusing", async () => {
  const kv = new TtlKv();
  kv.now = T0;
  for (let i = 0; i < 5; i += 1) {
    await admitReport(kv, report(`r${i}`), "acct", new Date(kv.now));
  }
  const key = "principal:hour:acct";
  const expiry = kv.expires.get(key);
  assert.ok(expiry !== undefined);

  // A reporter retrying every five minutes for the rest of the hour.
  for (let minute = 5; minute <= 55; minute += 5) {
    kv.now = T0 + minute * MINUTE;
    assert.equal(
      (await admitReport(kv, report(`retry ${minute}`), "acct", new Date(kv.now)))
        .verdict,
      "limited",
    );
  }

  assert.equal(kv.map.get(key), "5");
  assert.equal(kv.expires.get(key), expiry, "a refusal moved the window");

  kv.now = T0 + 61 * MINUTE;
  assert.equal(
    (await admitReport(kv, report("finally"), "acct", new Date(kv.now))).verdict,
    "accepted",
  );
});

test("the linking window rolls instead of being pushed by refused attempts", async () => {
  const kv = new TtlKv();
  kv.now = T0;

  for (let i = 0; i < LINK_START_MAX_PER_HOUR; i += 1) {
    // Tickets expire after ten minutes, so each mint is a fresh one.
    kv.now = T0 + i * 11 * MINUTE;
    await startLink(kv, { account_key: "acct_abc123" }, new Date(kv.now));
  }

  kv.now = T0 + 40 * MINUTE;
  await assert.rejects(
    () => startLink(kv, { account_key: "acct_abc123" }, new Date(kv.now)),
    (error: unknown) => error instanceof LinkError && error.code === "link.rate_limited",
  );

  // The last accepted mint was at minute 22, so its hour ends at 82.
  kv.now = T0 + 83 * MINUTE;
  const started = await startLink(kv, { account_key: "acct_abc123" }, new Date(kv.now));
  assert.equal(started.reused, false);
});
