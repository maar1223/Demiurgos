/**
 * T5 regression probes, kept from the independent verification round.
 *
 * Each test pins one defect the verifier found, so it can never come back:
 * a topic that did not state the identity level, an unbound namespace that
 * threw instead of degrading, and the handover order that makes a token
 * unusable before the app ever receives it.
 */

import { test } from "node:test";
import assert from "node:assert/strict";

import worker from "../src/index.ts";
import { linkStatus, redeemTicket, startLink } from "../src/linking.ts";
import {
  readIdentityByInstallToken,
  recordInstallToken,
  writeIdentity,
  type IdentityRecord,
  type KvLike,
} from "../src/identity.ts";

const BOT = "123456:fake-bot-token";
const CHAT = "-1001234567890";
const BODY = {
  schema: 1,
  app_version: "0.9.3-alpha",
  platform: { os: "linux" },
  description: "boom",
  contact: null as string | null,
  logs: null,
};

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

async function linkedKv(token: string): Promise<MemoryKv> {
  const kv = new MemoryKv();
  await writeIdentity(kv, linked());
  await recordInstallToken(kv, token, "1234567890");
  return kv;
}

type EnvOverrides = Record<string, unknown>;

function env(
  kv: KvLike | null,
  overrides: EnvOverrides = {},
): Parameters<typeof worker.fetch>[1] {
  return {
    RATE_LIMIT: kv ?? new MemoryKv(),
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

interface Call {
  method: string;
  json: Record<string, unknown> | null;
  form: FormData | null;
}

function stubTelegram(): { calls: Call[]; restore: () => void } {
  const original = globalThis.fetch;
  const calls: Call[] = [];
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const method = String(input).split("/").pop() ?? "";
    const body = init?.body;
    const isForm = typeof FormData !== "undefined" && body instanceof FormData;
    calls.push({
      method,
      json: isForm ? null : JSON.parse(String(body ?? "{}")),
      form: isForm ? (body as FormData) : null,
    });
    if (method === "createForumTopic") {
      return new Response(
        JSON.stringify({ ok: true, result: { message_thread_id: 7 } }),
        { status: 200 },
      );
    }
    return new Response(JSON.stringify({ ok: true, result: {} }), { status: 200 });
  }) as typeof fetch;
  return { calls, restore: () => { globalThis.fetch = original; } };
}

function request(payload: unknown = BODY, token?: string): Request {
  const headers: Record<string, string> = { "content-type": "application/json" };
  if (token !== undefined) {
    headers["x-install-token"] = token;
  }
  return new Request("https://relay.example/", {
    method: "POST",
    headers,
    body: JSON.stringify(payload),
  });
}

function callNamed(calls: Call[], method: string): Call {
  const call = calls.find((entry) => entry.method === method);
  assert.ok(call !== undefined, `${method} was never called`);
  return call;
}

test("a typed handle never produces the topic name of a verified account", async () => {
  const token = "1".repeat(64);
  const verified = stubTelegram();
  let verifiedName = "";
  try {
    await worker.fetch(
      request({ ...BODY, contact: null }, token),
      env(await linkedKv(token)),
      {} as never,
    );
    verifiedName = String(callNamed(verified.calls, "createForumTopic").json?.name);
  } finally {
    verified.restore();
  }

  for (const contact of ["@brook", "owner", "Brook"]) {
    const telegram = stubTelegram();
    try {
      await worker.fetch(
        request({ ...BODY, contact }),
        env(new MemoryKv()),
        {} as never,
      );
      const name = String(callNamed(telegram.calls, "createForumTopic").json?.name);
      assert.notEqual(name, verifiedName, `${contact} impersonated a verified topic`);
      assert.ok(name.includes("declared · local session"), name);
    } finally {
      telegram.restore();
    }
  }

  assert.ok(verifiedName.includes("verified by Telegram"), verifiedName);
});

test("the document caption states the attribution level too", async () => {
  const token = "2".repeat(64);
  const telegram = stubTelegram();
  try {
    await worker.fetch(
      request({ ...BODY, contact: null }, token),
      env(await linkedKv(token)),
      {} as never,
    );
    const form = callNamed(telegram.calls, "sendDocument").form;
    assert.ok(form !== null);
    assert.match(String(form.get("caption")), /verified by Telegram/);
  } finally {
    telegram.restore();
  }
});

test("an unbound LINKS namespace degrades to declared instead of failing the report", async () => {
  const telegram = stubTelegram();
  try {
    const response = await worker.fetch(
      request({ ...BODY, contact: "Maria" }, "f".repeat(64)),
      env(null, { LINKS: null }),
      {} as never,
    );

    assert.equal(response.status, 200);
    const summary = JSON.stringify(callNamed(telegram.calls, "sendMessage").json);
    assert.ok(summary.includes("👤 Maria — declared · local session"));
  } finally {
    telegram.restore();
  }
});

test("a failing store refuses the report instead of assuming the credential is clean", async () => {
  const token = "3".repeat(64);
  const broken: KvLike = {
    async get(): Promise<string | null> {
      throw new Error("kv down");
    },
    async put(): Promise<void> {},
    async delete(): Promise<void> {},
  };
  const telegram = stubTelegram();
  try {
    const response = await worker.fetch(
      request({ ...BODY, contact: "Maria" }, token),
      env(new MemoryKv(), { LINKS: broken }),
      {} as never,
    );

    assert.equal(response.status, 503);
    assert.deepEqual(await response.json(), {
      ok: false,
      code: "relay.rate_limit_unavailable",
    });
    assert.equal(telegram.calls.length, 0);
  } finally {
    telegram.restore();
  }

  // Without a credential nothing is checked, so an outage cannot silence the
  // anonymous fallback path.
  const anonymous = stubTelegram();
  try {
    const response = await worker.fetch(
      request({ ...BODY, contact: "Maria" }),
      env(new MemoryKv(), { LINKS: broken }),
      {} as never,
    );
    assert.equal(response.status, 200);
  } finally {
    anonymous.restore();
  }
});

test("a token in the JSON body is rejected, never accepted as a header substitute", async () => {
  const response = await worker.fetch(
    request({ ...BODY, install_token: "x".repeat(64) }),
    env(new MemoryKv()),
    {} as never,
  );

  assert.equal(response.status, 400);
  assert.deepEqual(await response.json(), {
    ok: false,
    code: "relay.invalid_payload",
  });
});

test("a token signs only after the handover, never at redemption", async () => {
  const kv = new MemoryKv();
  const started = await startLink(
    kv,
    { account_key: "acct_abc123" },
    new Date("2026-10-25T12:00:00Z"),
  );
  await redeemTicket(
    kv,
    started.ticket,
    { id: "1234567890", username: "brook", displayName: "Brook" },
    new Date("2026-10-25T12:01:00Z"),
  );
  const stored = JSON.parse(kv.map.get(`ticket:${started.ticket}`) ?? "{}") as {
    install_token?: string;
  };
  assert.equal(typeof stored.install_token, "string");
  const token = stored.install_token ?? "";

  assert.equal(await readIdentityByInstallToken(kv, token), null);

  const status = await linkStatus(kv, started.ticket, new Date("2026-10-25T12:02:00Z"));
  assert.equal(status.state, "linked");
  assert.notEqual(await readIdentityByInstallToken(kv, token), null);
});

test("only the hash of the token is stored", async () => {
  const token = "abcd".repeat(16);
  const kv = new MemoryKv();
  await recordInstallToken(kv, token, "1234567890");

  const digest = Array.from(
    new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(token))),
    (byte) => byte.toString(16).padStart(2, "0"),
  ).join("");

  assert.ok(kv.map.has(`link_token:${digest}`));
  for (const [key, value] of kv.map) {
    assert.equal(key.includes(token), false);
    assert.equal(value.includes(token), false);
  }
});
