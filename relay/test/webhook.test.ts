/**
 * Webhook tests — auth, the two accepted commands, and the one-way rule.
 *
 * The Telegram API is stubbed by replacing the global `fetch`, so no network
 * leaves the process and every outbound call is asserted.
 */

import { test } from "node:test";
import assert from "node:assert/strict";

import worker from "../src/index.ts";
import { readIdentity, type KvLike } from "../src/identity.ts";
import { startLink } from "../src/linking.ts";

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

const TOKEN = "123456:fake-bot-token";
const SECRET = "webhook-secret";
const KEY = "shared-relay-key";

function makeEnv(kv: MemoryKv, overrides: Record<string, unknown> = {}) {
  return {
    RATE_LIMIT: kv,
    LINKS: kv,
    RELAY_KEY: KEY,
    TELEGRAM_BOT_TOKEN: TOKEN,
    TELEGRAM_WEBHOOK_SECRET: SECRET,
    BREVO_API_KEY: "",
    OWNER_INBOX: "",
    SENDER_FROM: "",
    ...overrides,
  } as unknown as Parameters<typeof worker.fetch>[1];
}

type Sent = { chatId: string; text: string };

/** Replace global fetch for one test; return the recorded outbound messages. */
async function withTelegram(
  run: () => Promise<void>,
): Promise<{ sent: Sent[]; calls: string[] }> {
  const original = globalThis.fetch;
  const sent: Sent[] = [];
  const calls: string[] = [];
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    calls.push(String(input));
    const body = JSON.parse(String(init?.body ?? "{}")) as {
      chat_id?: string;
      text?: string;
    };
    sent.push({ chatId: String(body.chat_id), text: String(body.text) });
    return new Response(JSON.stringify({ ok: true }), { status: 200 });
  }) as typeof fetch;
  try {
    await run();
  } finally {
    globalThis.fetch = original;
  }
  return { sent, calls };
}

function webhook(body: unknown, secret: string | null = SECRET): Request {
  const headers: Record<string, string> = { "content-type": "application/json" };
  if (secret !== null) {
    headers["x-telegram-bot-api-secret-token"] = secret;
  }
  return new Request("https://relay.example/telegram/webhook", {
    method: "POST",
    headers,
    body: JSON.stringify(body),
  });
}

function update(text: string, userId = 1234567890): unknown {
  return {
    update_id: 1,
    message: {
      message_id: 1,
      chat: { id: userId },
      from: { id: userId, username: "brook", first_name: "Brook" },
      text,
    },
  };
}

test("the webhook refuses a missing or wrong Telegram secret", async () => {
  const kv = new MemoryKv();

  const missing = await worker.fetch(webhook(update("/start ABCDEFGH"), null), makeEnv(kv), {} as never);
  assert.equal(missing.status, 401);
  assert.deepEqual(await missing.json(), { ok: false, code: "relay.unauthorized" });

  const wrong = await worker.fetch(webhook(update("/start ABCDEFGH"), "nope"), makeEnv(kv), {} as never);
  assert.equal(wrong.status, 401);
});

test("the webhook fails closed when its configuration is missing", async () => {
  const kv = new MemoryKv();
  const response = await worker.fetch(
    webhook(update("/start ABCDEFGH")),
    makeEnv(kv, { TELEGRAM_BOT_TOKEN: "" }),
    {} as never,
  );

  assert.equal(response.status, 500);
  assert.deepEqual(await response.json(), { ok: false, code: "relay.not_configured" });
});

test("/start with a live ticket links the account and confirms once", async () => {
  const kv = new MemoryKv();
  const { ticket } = await startLink(kv, { account_key: "acct_abc123" }, new Date());

  let status = 0;
  const { sent, calls } = await withTelegram(async () => {
    const response = await worker.fetch(
      webhook(update(`/start ${ticket}`)),
      makeEnv(kv),
      {} as never,
    );
    status = response.status;
    assert.deepEqual(await response.json(), { ok: true });
  });

  assert.equal(status, 200);
  assert.equal(calls.length, 1);
  assert.ok(calls[0].includes("/sendMessage"));
  assert.equal(sent[0].chatId, "1234567890");
  assert.match(sent[0].text, /^Conectado/);
  const identity = await readIdentity(kv, "1234567890");
  assert.equal(identity?.account_key, "acct_abc123");
  assert.equal(identity?.username, "brook");
  assert.equal(identity?.display_name, "Brook");
});

test("a repeated /start from the same account succeeds again", async () => {
  const kv = new MemoryKv();
  const { ticket } = await startLink(kv, { account_key: "acct_abc123" }, new Date());

  const { sent } = await withTelegram(async () => {
    await worker.fetch(webhook(update(`/start ${ticket}`)), makeEnv(kv), {} as never);
    await worker.fetch(webhook(update(`/start ${ticket}`)), makeEnv(kv), {} as never);
  });

  assert.equal(sent.length, 2);
  for (const message of sent) {
    assert.match(message.text, /^Conectado/);
  }
});

test("an expired ticket answers 200 with a message and links nothing", async () => {
  const kv = new MemoryKv();
  const past = new Date(Date.now() - 20 * 60_000);
  const { ticket } = await startLink(kv, { account_key: "acct_abc123" }, past);

  let status = 0;
  const { sent } = await withTelegram(async () => {
    const response = await worker.fetch(
      webhook(update(`/start ${ticket}`)),
      makeEnv(kv),
      {} as never,
    );
    status = response.status;
  });

  assert.equal(status, 200, "Telegram must not redeliver a handled update");
  assert.match(sent[0].text, /ya no es válido/);
  assert.equal(await readIdentity(kv, "1234567890"), null);
});

test("a ticket already claimed by another account explains itself", async () => {
  const kv = new MemoryKv();
  const { ticket } = await startLink(kv, { account_key: "acct_abc123" }, new Date());

  const { sent } = await withTelegram(async () => {
    await worker.fetch(webhook(update(`/start ${ticket}`)), makeEnv(kv), {} as never);
    await worker.fetch(webhook(update(`/start ${ticket}`, 999999999)), makeEnv(kv), {} as never);
  });

  assert.equal(sent.length, 2);
  assert.match(sent[1].text, /ya se usó con otra cuenta/);
  assert.equal(await readIdentity(kv, "999999999"), null);
});

test("/link/revoke disconnects and erases the identity", async () => {
  const kv = new MemoryKv();
  const { ticket } = await startLink(kv, { account_key: "acct_abc123" }, new Date());
  await withTelegram(async () => {
    await worker.fetch(webhook(update(`/start ${ticket}`)), makeEnv(kv), {} as never);
  });

  const { sent } = await withTelegram(async () => {
    await worker.fetch(webhook(update("/link/revoke")), makeEnv(kv), {} as never);
  });

  assert.match(sent[0].text, /^Desconectado/);
  assert.equal(await readIdentity(kv, "1234567890"), null);
  assert.equal(kv.map.has("identity:acct:acct_abc123"), false);
});

test("/link/revoke on an unlinked account says so without failing", async () => {
  const kv = new MemoryKv();

  let status = 0;
  const { sent } = await withTelegram(async () => {
    const response = await worker.fetch(
      webhook(update("/link/revoke")),
      makeEnv(kv),
      {} as never,
    );
    status = response.status;
  });

  assert.equal(status, 200);
  assert.match(sent[0].text, /no estaba conectada/);
});

test("free text and non-message updates are ignored without any outbound call", async () => {
  const kv = new MemoryKv();

  const { sent, calls } = await withTelegram(async () => {
    await worker.fetch(webhook(update("hola, ¿me ayudas?")), makeEnv(kv), {} as never);
    await worker.fetch(webhook({ update_id: 2, edited_message: {} }), makeEnv(kv), {} as never);
    await worker.fetch(webhook({ update_id: 3 }), makeEnv(kv), {} as never);
  });

  assert.equal(calls.length, 0);
  assert.equal(sent.length, 0);
});

test("the bot token never appears in a webhook response", async () => {
  const kv = new MemoryKv();
  const { ticket } = await startLink(kv, { account_key: "acct_abc123" }, new Date());

  let body = "";
  await withTelegram(async () => {
    const response = await worker.fetch(
      webhook(update(`/start ${ticket}`)),
      makeEnv(kv),
      {} as never,
    );
    body = await response.text();
  });

  assert.equal(body.includes(TOKEN), false);
  assert.equal(body.includes(SECRET), false);
});

test("malformed updates never throw and never call out, including wrong-typed ids", async () => {
  const kv = new MemoryKv();
  const bodies: unknown[] = [
    { update_id: 1 },
    { update_id: 1, message: null },
    { update_id: 1, message: "hi" },
    { update_id: 1, message: [] },
    { update_id: 1, message: { chat: { id: 5 }, from: { id: 5 } } },
    { update_id: 1, message: { chat: { id: 5 }, from: { id: 5 }, text: 123 } },
    update("/start ABCDEFGH", 0),
    { update_id: 1, message: { chat: { id: null }, from: { id: 5 }, text: "/start ABCDEFGH" } },
    { update_id: 1, message: { chat: { id: true }, from: { id: 5 }, text: "/start ABCDEFGH" } },
    { update_id: 1, message: { chat: { id: {} }, from: { id: 5 }, text: "/start ABCDEFGH" } },
    { update_id: 1, message: { chat: { id: 5 }, from: { id: null }, text: "/start ABCDEFGH" } },
    { update_id: 1, message: { chat: { id: 5 }, from: { id: true }, text: "/start ABCDEFGH" } },
    { update_id: 1, message: { chat: { id: 5 }, from: { id: {} }, text: "/start ABCDEFGH" } },
    { update_id: 1, message: { chat: { id: 5 }, from: { id: -7 }, text: "/start ABCDEFGH" } },
    { update_id: 1, message: { chat: { id: 5 }, from: { id: 1.5 }, text: "/start ABCDEFGH" } },
    { update_id: 1, message: { chat: { id: 5 }, from: { id: "abc" }, text: "/start ABCDEFGH" } },
  ];

  for (const body of bodies) {
    const { sent, calls } = await withTelegram(async () => {
      const response = await worker.fetch(
        webhook(body),
        makeEnv(kv),
        {} as never,
      );
      assert.equal(response.status, 200, `status for ${JSON.stringify(body)}`);
    });
    assert.equal(calls.length, 0, `no outbound for ${JSON.stringify(body)}`);
    assert.equal(sent.length, 0);
  }

  assert.equal(kv.map.size, 0, "no identity written for a malformed update");
});

test("a negative group chat id and a positive user id still redeem", async () => {
  const kv = new MemoryKv();
  const { ticket } = await startLink(kv, { account_key: "acct_abc123" }, new Date());

  const group = {
    update_id: 1,
    message: {
      chat: { id: -1001234567890 },
      from: { id: 1234567890, username: "brook", first_name: "Brook" },
      text: `/start ${ticket}`,
    },
  };

  let status = 0;
  const { sent } = await withTelegram(async () => {
    const response = await worker.fetch(webhook(group), makeEnv(kv), {} as never);
    status = response.status;
  });

  assert.equal(status, 200);
  assert.equal(sent.length, 1);
  assert.equal(sent[0].chatId, "-1001234567890");
  assert.match(sent[0].text, /^Conectado/);
  assert.equal((await readIdentity(kv, "1234567890"))?.account_key, "acct_abc123");
});

test("a bare /start answers with where to get the link", async () => {
  const kv = new MemoryKv();

  const { sent, calls } = await withTelegram(async () => {
    const response = await worker.fetch(webhook(update("/start")), makeEnv(kv), {} as never);
    assert.equal(response.status, 200);
  });

  assert.equal(calls.length, 1);
  assert.match(sent[0].text, /^Para conectar tu cuenta/);
  assert.equal(kv.map.size, 0, "a bare /start links nothing");
});

test("a bare /start addressed to the bot is answered too, but other text is not", async () => {
  const kv = new MemoryKv();
  const bodies = ["/start@ReportesDemiurgosBot", "/help", "/start algo con espacios", "hola"];

  const counts: number[] = [];
  for (const body of bodies) {
    const { sent } = await withTelegram(async () => {
      await worker.fetch(webhook(update(body)), makeEnv(kv), {} as never);
    });
    counts.push(sent.length);
  }

  assert.deepEqual(counts, [1, 0, 0, 0]);
});
