/**
 * Abuse-control tests (S13).
 *
 * The channel must stay usable for legitimate reports, so the bounds are
 * layered and each one is asserted on its own:
 *
 *   - the same report twice in 24 h is not published twice,
 *   - a linked principal gets 5 an hour and 20 a day,
 *   - an unlinked reporter keeps the per-IP and global ceilings,
 *   - a revoked install cannot keep reporting through the dead credential,
 *   - a counter backend failure fails CLOSED.
 */

import { test } from "node:test";
import assert from "node:assert/strict";

import worker from "../src/index.ts";
import {
  PRINCIPAL_DAILY_MAX,
  PRINCIPAL_HOURLY_MAX,
  reportFingerprint,
} from "../src/abuse.ts";
import {
  recordInstallToken,
  revokeIdentity,
  writeIdentity,
  type IdentityRecord,
  type KvLike,
} from "../src/identity.ts";

const BOT = "123456:fake-bot-token";
const CHAT = "-1001234567890";

class MemoryKv implements KvLike {
  readonly map = new Map<string, string>();
  readonly ttls = new Map<string, number | undefined>();

  async get(key: string): Promise<string | null> {
    return this.map.get(key) ?? null;
  }

  async put(
    key: string,
    value: string,
    options?: { expirationTtl?: number },
  ): Promise<void> {
    this.ttls.set(key, options?.expirationTtl);
    this.map.set(key, value);
  }

  async delete(key: string): Promise<void> {
    this.map.delete(key);
  }
}

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

const REPORT = {
  schema: 1,
  app_version: "0.9.3-alpha",
  platform: { os: "linux", arch: "x86_64" },
  description: "El selector de relaciones se queda vacío.",
  contact: null as string | null,
  logs: "line one",
};

interface Call {
  method: string;
  json: Record<string, unknown> | null;
}

function stubTelegram(fail: string | null = null): {
  calls: Call[];
  restore: () => void;
} {
  const original = globalThis.fetch;
  const calls: Call[] = [];
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const method = String(input).split("/").pop() ?? "";
    const body = init?.body;
    const isForm = typeof FormData !== "undefined" && body instanceof FormData;
    calls.push({
      method,
      json: isForm ? null : JSON.parse(String(body ?? "{}")),
    });
    if (fail === method) {
      return new Response(JSON.stringify({ ok: false }), { status: 400 });
    }
    return new Response(JSON.stringify({ ok: true, result: { message_thread_id: 7 } }), {
      status: 200,
    });
  }) as typeof fetch;
  return { calls, restore: () => { globalThis.fetch = original; } };
}

function env(kv: KvLike, overrides: Record<string, unknown> = {}) {
  return {
    RATE_LIMIT: kv,
    LINKS: kv,
    RELAY_KEY: "k",
    TELEGRAM_BOT_TOKEN: BOT,
    TELEGRAM_WEBHOOK_SECRET: "s",
    TELEGRAM_CHAT_ID: CHAT,
    BREVO_API_KEY: "",
    OWNER_INBOX: "",
    SENDER_FROM: "",
    ...overrides,
  } as unknown as Parameters<typeof worker.fetch>[1];
}

function post(
  payload: unknown = REPORT,
  options: { token?: string; ip?: string; installId?: string } = {},
): Request {
  const headers: Record<string, string> = { "content-type": "application/json" };
  if (options.token !== undefined) {
    headers["x-install-token"] = options.token;
  }
  if (options.installId !== undefined) {
    headers["x-install-id"] = options.installId;
  }
  headers["CF-Connecting-IP"] = options.ip ?? "203.0.113.7";
  return new Request("https://relay.example/", {
    method: "POST",
    headers,
    body: JSON.stringify(payload),
  });
}

async function submit(
  kv: KvLike,
  payload: unknown = REPORT,
  options: {
    token?: string;
    ip?: string;
    installId?: string;
    env?: Record<string, unknown>;
  } = {},
): Promise<{ status: number; body: Record<string, unknown> }> {
  const response = await worker.fetch(
    post(payload, options),
    env(kv, options.env),
    {} as never,
  );
  return { status: response.status, body: (await response.json()) as Record<string, unknown> };
}

async function linkedKv(token: string): Promise<MemoryKv> {
  const kv = new MemoryKv();
  await writeIdentity(kv, linked());
  await recordInstallToken(kv, token, "1234567890");
  return kv;
}

test("the same report twice returns the first delivery and publishes once", async () => {
  const kv = new MemoryKv();
  const telegram = stubTelegram();
  try {
    const first = await submit(kv, REPORT);
    const second = await submit(kv, REPORT);

    assert.equal(first.status, 200);
    assert.equal(second.status, 200);
    assert.equal(second.body.delivery_id, first.body.delivery_id);
    assert.equal(second.body.deduped, true);
    assert.deepEqual(
      telegram.calls.map((call) => call.method),
      ["createForumTopic", "sendMessage", "sendDocument"],
    );
  } finally {
    telegram.restore();
  }
});

test("a different report is published even within the same window", async () => {
  const kv = new MemoryKv();
  const telegram = stubTelegram();
  try {
    const first = await submit(kv, REPORT);
    const second = await submit(kv, { ...REPORT, description: "Otro fallo distinto." });

    assert.notEqual(second.body.delivery_id, first.body.delivery_id);
    assert.equal(second.body.deduped, undefined);
    assert.equal(telegram.calls.length, 6);
  } finally {
    telegram.restore();
  }
});

test("an install pseudonym labels the report and counts the accepted ones", async () => {
  const kv = new MemoryKv();
  const installId = `install_${"ab".repeat(12)}`;
  const telegram = stubTelegram();
  try {
    const first = await submit(kv, { ...REPORT, description: "primer fallo" }, { installId });
    assert.equal(first.status, 200);
    const second = await submit(kv, { ...REPORT, description: "segundo fallo" }, { installId });
    assert.equal(second.status, 200);

    const summaries = telegram.calls
      .filter((call) => call.method === "sendMessage")
      .map((call) => JSON.stringify(call.json));
    assert.match(summaries[0] ?? "", /instalación [0-9a-f]{4} · 1 reporte/);
    assert.match(summaries[1] ?? "", /instalación [0-9a-f]{4} · 2 reportes/);

    // Only the digest is stored: neither the key nor the value carries the id.
    for (const [key, value] of kv.map) {
      assert.equal(key.includes(installId), false);
      assert.equal(value.includes(installId), false);
    }
  } finally {
    telegram.restore();
  }
});

test("a deduped report does not inflate the pseudonym count", async () => {
  const kv = new MemoryKv();
  const installId = `install_${"cd".repeat(12)}`;
  const telegram = stubTelegram();
  try {
    assert.equal((await submit(kv, REPORT, { installId })).status, 200);
    const duplicate = await submit(kv, REPORT, { installId });
    assert.equal(duplicate.body.deduped, true);
    await submit(kv, { ...REPORT, description: "otro fallo" }, { installId });

    const summaries = telegram.calls
      .filter((call) => call.method === "sendMessage")
      .map((call) => JSON.stringify(call.json));
    // Two publications, and the second one counts two — not three.
    assert.equal(summaries.length, 2);
    assert.match(summaries[1] ?? "", /· 2 reportes/);
  } finally {
    telegram.restore();
  }
});

test("an unusable install id is ignored, never published", async () => {
  const kv = new MemoryKv();
  const telegram = stubTelegram();
  try {
    for (const installId of ["install_ZZZ", "install_" + "a".repeat(23), "x".repeat(80)]) {
      const result = await submit(kv, { ...REPORT, description: `fallo ${installId}` }, { installId });
      assert.equal(result.status, 200);
    }
    for (const call of telegram.calls) {
      assert.equal(JSON.stringify(call.json).includes("instalación"), false);
    }
  } finally {
    telegram.restore();
  }
});

test("the fingerprint ignores key order and an absent log", async () => {
  const a = await reportFingerprint({
    description: "boom",
    platform: { os: "linux", arch: "x86_64" },
    logs: null,
  });
  const b = await reportFingerprint({
    description: "boom",
    platform: { arch: "x86_64", os: "linux" },
    logs: null,
  });
  const c = await reportFingerprint({
    description: "boom",
    platform: { arch: "x86_64", os: "linux" },
    logs: "",
  });

  assert.equal(a, b);
  assert.notEqual(a, c);
});

test("a failed delivery is not remembered, so a retry can still arrive", async () => {
  const kv = new MemoryKv();
  const telegram = stubTelegram("sendMessage");
  try {
    const failed = await submit(kv, REPORT);
    assert.equal(failed.status, 502);
  } finally {
    telegram.restore();
  }

  const retry = stubTelegram();
  try {
    const second = await submit(kv, REPORT);
    assert.equal(second.status, 200);
    assert.equal(second.body.deduped, undefined);
    assert.deepEqual(
      retry.calls.map((call) => call.method),
      ["createForumTopic", "sendMessage", "sendDocument"],
    );
  } finally {
    retry.restore();
  }
});

/** A KV whose dedup writes fail for the first `failures` attempts. */
class FlakyDedupKv extends MemoryKv {
  failures: number;
  attempts = 0;

  constructor(failures: number) {
    super();
    this.failures = failures;
  }

  async put(
    key: string,
    value: string,
    options?: { expirationTtl?: number },
  ): Promise<void> {
    if (key.startsWith("dedup:")) {
      this.attempts += 1;
      if (this.attempts <= this.failures) {
        throw new Error("kv write failed");
      }
    }
    return super.put(key, value, options);
  }
}

test("a dedup write that fails once is retried, so the next copy is caught", async () => {
  const kv = new FlakyDedupKv(1);
  const telegram = stubTelegram();
  try {
    const first = await submit(kv, REPORT);
    assert.equal(first.status, 200);
    // The first attempt failed; the retry is what remembered the report.
    assert.equal(kv.attempts, 2);

    const second = await submit(kv, REPORT);
    assert.equal(second.status, 200);
    assert.equal(second.body.delivery_id, first.body.delivery_id);
    assert.equal(second.body.deduped, true);
    assert.equal(telegram.calls.length, 3);
  } finally {
    telegram.restore();
  }
});

test("a dedup write that keeps failing still answers the delivery, never a 502", async () => {
  const kv = new FlakyDedupKv(Number.POSITIVE_INFINITY);
  const telegram = stubTelegram();
  try {
    const delivered = await submit(kv, REPORT);

    // The report reached the group; telling the reporter it failed would invite
    // a retry that publishes it again.
    assert.equal(delivered.status, 200);
    assert.equal(typeof delivered.body.delivery_id, "string");
    assert.equal(kv.attempts, 2);
  } finally {
    telegram.restore();
  }
});

test("two accounts sending the same failure get the first delivery, published once", async () => {
  const tokenA = "2".repeat(64);
  const tokenB = "3".repeat(64);
  const kv = new MemoryKv();
  await writeIdentity(kv, linked());
  await recordInstallToken(kv, tokenA, "1234567890");
  await writeIdentity(
    kv,
    linked({
      telegram_user_id: "9876543210",
      username: "other",
      account_key: "acct_other123",
    }),
  );
  await recordInstallToken(kv, tokenB, "9876543210");

  const telegram = stubTelegram();
  try {
    const first = await submit(kv, REPORT, { token: tokenA });
    const second = await submit(kv, REPORT, { token: tokenB });

    // S13 asks for one topic per unique failure: the second reporter is told it
    // is already reported, and only the first delivery is published.
    assert.equal(first.status, 200);
    assert.equal(second.status, 200);
    assert.equal(second.body.deduped, true);
    assert.equal(second.body.delivery_id, first.body.delivery_id);
    assert.equal(telegram.calls.length, 3);
  } finally {
    telegram.restore();
  }
});

test("a linked principal is capped per hour, and a duplicate does not count", async () => {
  const token = "1".repeat(64);
  const kv = await linkedKv(token);
  const telegram = stubTelegram();
  try {
    for (let i = 0; i < PRINCIPAL_HOURLY_MAX; i += 1) {
      const result = await submit(kv, { ...REPORT, description: `fallo ${i}` }, { token });
      assert.equal(result.status, 200);
    }

    // Repeating an already published report costs nothing.
    const duplicate = await submit(
      kv,
      { ...REPORT, description: "fallo 0" },
      { token },
    );
    assert.equal(duplicate.status, 200);
    assert.equal(duplicate.body.deduped, true);

    const limited = await submit(kv, { ...REPORT, description: "uno más" }, { token });
    assert.equal(limited.status, 429);
    assert.deepEqual(limited.body, { ok: false, code: "relay.rate_limited" });
  } finally {
    telegram.restore();
  }
});

test("declining the signature is not a way out of the principal ceiling", async () => {
  const token = "7".repeat(64);
  const kv = new MemoryKv();
  await writeIdentity(
    kv,
    linked({ permissions: { report_identity: false, notify_releases: false } }),
  );
  await recordInstallToken(kv, token, "1234567890");
  const telegram = stubTelegram();
  try {
    for (let i = 0; i < PRINCIPAL_HOURLY_MAX; i += 1) {
      const result = await submit(kv, { ...REPORT, description: `unsigned ${i}` }, { token });
      assert.equal(result.status, 200);
    }

    const limited = await submit(kv, { ...REPORT, description: "unsigned over" }, { token });
    assert.equal(limited.status, 429);
    assert.equal(kv.map.get("principal:hour:acct_abc123"), "5");
  } finally {
    telegram.restore();
  }
});

test("the daily cap applies even when the hourly one is clear", async () => {
  const token = "2".repeat(64);
  const kv = await linkedKv(token);
  kv.map.set("principal:day:acct_abc123", String(PRINCIPAL_DAILY_MAX));
  const telegram = stubTelegram();
  try {
    const limited = await submit(kv, REPORT, { token });

    assert.equal(limited.status, 429);
    assert.deepEqual(limited.body, { ok: false, code: "relay.rate_limited" });
  } finally {
    telegram.restore();
  }
});

test("an unlinked reporter keeps the per-IP ceiling", async () => {
  const kv = new MemoryKv();
  const telegram = stubTelegram();
  try {
    for (let i = 0; i < 5; i += 1) {
      const result = await submit(kv, { ...REPORT, description: `ip ${i}` });
      assert.equal(result.status, 200);
    }

    const limited = await submit(kv, { ...REPORT, description: "ip 6" });
    assert.equal(limited.status, 429);
  } finally {
    telegram.restore();
  }
});

test("a counter backend failure fails closed", async () => {
  const broken: KvLike = {
    async get(): Promise<string | null> {
      throw new Error("kv down");
    },
    async put(): Promise<void> {},
    async delete(): Promise<void> {},
  };

  const result = await submit(broken, REPORT);

  assert.equal(result.status, 503);
  assert.deepEqual(result.body, { ok: false, code: "relay.rate_limit_unavailable" });
});

test("a revoked install cannot keep reporting through the dead token", async () => {
  const token = "3".repeat(64);
  const kv = await linkedKv(token);
  await revokeIdentity(kv, "1234567890");

  const telegram = stubTelegram();
  try {
    const blocked = await submit(kv, REPORT, { token });
    assert.equal(blocked.status, 403);
    assert.deepEqual(blocked.body, { ok: false, code: "relay.report_blocked" });
    assert.equal(telegram.calls.length, 0);
  } finally {
    telegram.restore();
  }
});

test("relinking gives a fresh token that is not blocked", async () => {
  const revoked = "4".repeat(64);
  const fresh = "5".repeat(64);
  const kv = await linkedKv(revoked);
  await revokeIdentity(kv, "1234567890");

  await writeIdentity(kv, linked({ linked_at: "2026-10-25T13:00:00.000Z" }));
  await recordInstallToken(kv, fresh, "1234567890");

  const telegram = stubTelegram();
  try {
    const result = await submit(kv, REPORT, { token: fresh });
    assert.equal(result.status, 200);
    assert.equal(result.body.deduped, undefined);
  } finally {
    telegram.restore();
  }
});

test("a block is time-bounded, never a permanent shadow", async () => {
  const token = "6".repeat(64);
  const kv = await linkedKv(token);
  await revokeIdentity(kv, "1234567890");

  const blockedKey = [...kv.map.keys()].find((key) => key.startsWith("blocked:"));
  assert.ok(blockedKey !== undefined);
  assert.equal(kv.ttls.get(blockedKey), 30 * 24 * 3600);
  // The token itself is never stored: only its digest names the block.
  assert.equal(blockedKey.includes(token), false);
});
