/**
 * Publication tests — topic per report, summary message, full bundle document,
 * and the degradation when the group has no forum topics.
 */

import { test } from "node:test";
import assert from "node:assert/strict";

import worker from "../src/index.ts";
import {
  bundleText,
  publishReport,
  summaryText,
  topicName,
  type PublishableReport,
} from "../src/publication.ts";
import type { Attribution } from "../src/attribution.ts";
import {
  recordInstallToken,
  writeIdentity,
  type KvLike,
} from "../src/identity.ts";

const TOKEN_BOT = "123456:fake-bot-token";
const CHAT = "-1001234567890";

const DECLARED: Attribution = {
  level: "declared",
  line: "👤 maria@example.com — declared · local session",
  tag: "declared · local session",
  label: "maria@example.com",
  identity: null,
};

function report(overrides: Partial<PublishableReport> = {}): PublishableReport {
  return {
    app_version: "0.9.3-alpha",
    platform: { os: "linux", arch: "x86_64" },
    description: "El selector de relaciones se queda vacío.",
    contact: "maria@example.com",
    logs: "line one\nline two",
    context: { route: "/perfil", view: "perfil" },
    attribution: DECLARED,
    ...overrides,
  };
}

type Call = {
  method: string;
  json: Record<string, unknown> | null;
  form: FormData | null;
};

/** Stub the Telegram API; `fail` names a method that answers 400. */
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
      form: isForm ? (body as FormData) : null,
    });
    if (fail === method) {
      return new Response(JSON.stringify({ ok: false }), { status: 400 });
    }
    if (method === "createForumTopic") {
      return new Response(
        JSON.stringify({ ok: true, result: { message_thread_id: 42 } }),
        { status: 200 },
      );
    }
    return new Response(JSON.stringify({ ok: true, result: {} }), { status: 200 });
  }) as typeof fetch;
  return { calls, restore: () => { globalThis.fetch = original; } };
}

test("the topic name is bounded and names the version and reporter", () => {
  const name = topicName(report());

  assert.equal(name, "BUG · v0.9.3-alpha · declared · local session · maria@example.com");
  assert.ok(topicName(report({ contact: "x".repeat(400) })).length <= 128);
});

test("the summary carries the header and the description, bounded", () => {
  const text = summaryText(report());

  assert.match(text, /v0\.9\.3-alpha/);
  assert.match(text, /linux/);
  assert.ok(text.includes("🧭 route=/perfil view=perfil"));
  assert.ok(text.includes("👤 maria@example.com — declared · local session"));
  assert.ok(text.includes("El selector de relaciones"));
  assert.ok(summaryText(report({ description: "x".repeat(9000) })).length <= 3800);
});

test("the bundle document carries the full logs without truncation", () => {
  const logs = "x".repeat(65536);

  const text = bundleText(report({ logs }), "abc-123");

  assert.match(text, /Report id: abc-123/);
  assert.ok(text.includes(logs));
  assert.ok(text.includes("Where: route=/perfil view=perfil"));
  assert.ok(text.includes("Reported by: 👤 maria@example.com — declared · local session"));
});

test("a schema-1 report without context still renders and delivers", () => {
  const text = summaryText(report({ context: {} }));

  assert.equal(text.includes("🧭"), false);
  assert.ok(bundleText(report({ context: {} }), "abc-123").includes("Where: (not provided)"));
});

test("a report with no context omits the line from the summary", () => {
  const text = summaryText(report({ context: {} }));

  assert.ok(text.includes("🐞 v0.9.3-alpha"));
  assert.equal(text.split("\n").length >= 3, true);
});

test("publishing opens a topic, sends the summary there, then the bundle", async () => {
  const telegram = stubTelegram();
  try {
    const result = await publishReport(
      { TELEGRAM_BOT_TOKEN: TOKEN_BOT, TELEGRAM_CHAT_ID: CHAT },
      report(),
      "abc-123",
    );

    assert.deepEqual(result, { threadId: 42 });
    assert.deepEqual(
      telegram.calls.map((call) => call.method),
      ["createForumTopic", "sendMessage", "sendDocument"],
    );
    assert.equal(telegram.calls[0].json?.chat_id, CHAT);
    assert.equal(telegram.calls[1].json?.message_thread_id, 42);
    assert.equal(telegram.calls[1].json?.chat_id, CHAT);

    const form = telegram.calls[2].form;
    assert.ok(form !== null);
    assert.equal(form.get("chat_id"), CHAT);
    assert.equal(form.get("message_thread_id"), "42");
    const document = form.get("document");
    assert.ok(document instanceof Blob);
    const text = await document.text();
    assert.ok(text.includes("line one"));
    assert.ok(String(form.get("caption")).length <= 1024);
  } finally {
    telegram.restore();
  }
});

test("a group without forum topics still receives the report", async () => {
  const telegram = stubTelegram("createForumTopic");
  try {
    const result = await publishReport(
      { TELEGRAM_BOT_TOKEN: TOKEN_BOT, TELEGRAM_CHAT_ID: CHAT },
      report(),
      "abc-123",
    );

    assert.deepEqual(result, { threadId: null });
    assert.deepEqual(
      telegram.calls.map((call) => call.method),
      ["createForumTopic", "sendMessage", "sendDocument"],
    );
    assert.equal(telegram.calls[1].json?.message_thread_id, undefined);
    assert.equal(telegram.calls[2].form?.get("message_thread_id"), null);
  } finally {
    telegram.restore();
  }
});

test("a failed summary throws, so the caller reports a real failure", async () => {
  const telegram = stubTelegram("sendMessage");
  try {
    await assert.rejects(
      () =>
        publishReport(
          { TELEGRAM_BOT_TOKEN: TOKEN_BOT, TELEGRAM_CHAT_ID: CHAT },
          report(),
          "abc-123",
        ),
      /telegram\.sendMessage\.rejected/,
    );
  } finally {
    telegram.restore();
  }
});

test("the bot token never appears in the message or the document", async () => {
  const telegram = stubTelegram();
  try {
    await publishReport(
      { TELEGRAM_BOT_TOKEN: TOKEN_BOT, TELEGRAM_CHAT_ID: CHAT },
      report(),
      "abc-123",
    );

    const summary = JSON.stringify(telegram.calls[1].json);
    const document = await (telegram.calls[2].form?.get("document") as Blob).text();
    assert.equal(summary.includes(TOKEN_BOT), false);
    assert.equal(document.includes(TOKEN_BOT), false);
  } finally {
    telegram.restore();
  }
});

test("POST / accepts schema 2 with context and refuses an unknown context key", async () => {
  const kv = new (class {
    readonly map = new Map<string, string>();
    async get(key: string) { return this.map.get(key) ?? null; }
    async put(key: string, value: string) { this.map.set(key, value); }
    async delete(key: string) { this.map.delete(key); }
  })();
  const telegram = stubTelegram();
  const send = (payload: Record<string, unknown>) =>
    worker.fetch(
      new Request("https://relay.example/", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(payload),
      }),
      {
        RATE_LIMIT: kv,
        LINKS: kv,
        RELAY_KEY: "k",
        TELEGRAM_BOT_TOKEN: TOKEN_BOT,
        TELEGRAM_WEBHOOK_SECRET: "s",
        TELEGRAM_CHAT_ID: CHAT,
        BREVO_API_KEY: "",
        OWNER_INBOX: "",
        SENDER_FROM: "",
      } as unknown as Parameters<typeof worker.fetch>[1],
      {} as never,
    );
  const base = {
    schema: 2,
    app_version: "0.9.3-alpha",
    platform: { os: "linux" },
    description: "boom",
    contact: null,
    logs: null,
  };
  try {
    const accepted = await send({ ...base, context: { route: "/perfil", view: "perfil", ui_area: "reportes", world_id: "w1" } });
    assert.equal(accepted.status, 200);
    const summary = JSON.stringify(telegram.calls[1].json);
    assert.ok(summary.includes("🧭 route=/perfil view=perfil ui_area=reportes world_id=w1"));

    const unknownKey = await send({ ...base, context: { screen: "perfil" } });
    assert.equal(unknownKey.status, 400);

    const tooLong = await send({ ...base, context: { route: "x".repeat(201) } });
    assert.equal(tooLong.status, 413);

    const unsupported = await send({ ...base, schema: 3 });
    assert.equal(unsupported.status, 400);
  } finally {
    telegram.restore();
  }
});

test("POST / publishes to the group when a chat id is configured", async () => {
  const kv = new (class {
    readonly map = new Map<string, string>();
    async get(key: string) { return this.map.get(key) ?? null; }
    async put(key: string, value: string) { this.map.set(key, value); }
    async delete(key: string) { this.map.delete(key); }
  })();
  const telegram = stubTelegram();
  try {
    const response = await worker.fetch(
      new Request("https://relay.example/", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          schema: 1,
          app_version: "0.9.3-alpha",
          platform: { os: "linux" },
          description: "boom",
          contact: null,
          logs: null,
        }),
      }),
      {
        RATE_LIMIT: kv,
        LINKS: kv,
        RELAY_KEY: "k",
        TELEGRAM_BOT_TOKEN: TOKEN_BOT,
        TELEGRAM_WEBHOOK_SECRET: "s",
        TELEGRAM_CHAT_ID: CHAT,
        BREVO_API_KEY: "",
        OWNER_INBOX: "",
        SENDER_FROM: "",
      } as unknown as Parameters<typeof worker.fetch>[1],
      {} as never,
    );

    assert.equal(response.status, 200);
    const body = (await response.json()) as Record<string, unknown>;
    assert.equal(body.ok, true);
    assert.equal(typeof body.delivery_id, "string");
    assert.deepEqual(
      telegram.calls.map((call) => call.method),
      ["createForumTopic", "sendMessage", "sendDocument"],
    );
  } finally {
    telegram.restore();
  }
});

test("POST / fails closed when neither sink is configured", async () => {
  const kv = new (class {
    readonly map = new Map<string, string>();
    async get(key: string) { return this.map.get(key) ?? null; }
    async put(key: string, value: string) { this.map.set(key, value); }
    async delete(key: string) { this.map.delete(key); }
  })();

  const response = await worker.fetch(
    new Request("https://relay.example/", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ schema: 1, app_version: "x" }),
    }),
    {
      RATE_LIMIT: kv,
      LINKS: kv,
      RELAY_KEY: "k",
      TELEGRAM_BOT_TOKEN: "",
      TELEGRAM_WEBHOOK_SECRET: "",
      BREVO_API_KEY: "",
      OWNER_INBOX: "",
      SENDER_FROM: "",
    } as unknown as Parameters<typeof worker.fetch>[1],
    {} as never,
  );

  assert.equal(response.status, 500);
  assert.deepEqual(await response.json(), { ok: false, code: "relay.not_configured" });
});

const TOKEN = "0123456789abcdef".repeat(4);

class LinkKv implements KvLike {
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

async function linkedKv(token = TOKEN): Promise<LinkKv> {
  const kv = new LinkKv();
  await writeIdentity(kv, {
    telegram_user_id: "1234567890",
    username: "brook",
    display_name: "Brook",
    account_key: "acct_abc123",
    linked_at: "2026-10-25T12:00:00.000Z",
    started_bots: { ideas: false, reports: true },
    permissions: { report_identity: true, notify_releases: false },
  });
  await recordInstallToken(kv, token, "1234567890");
  return kv;
}

function reportRequest(token: string | null): Request {
  const headers: Record<string, string> = { "content-type": "application/json" };
  if (token !== null) {
    headers["x-install-token"] = token;
  }
  return new Request("https://relay.example/", {
    method: "POST",
    headers,
    body: JSON.stringify({
      schema: 1,
      app_version: "0.9.3-alpha",
      platform: { os: "linux" },
      description: "boom",
      contact: null,
      logs: null,
    }),
  });
}

function workerEnv(
  kv: KvLike,
  overrides: Record<string, unknown> = {},
): Parameters<typeof worker.fetch>[1] {
  return {
    RATE_LIMIT: kv,
    LINKS: kv,
    RELAY_KEY: "k",
    TELEGRAM_BOT_TOKEN: TOKEN_BOT,
    TELEGRAM_WEBHOOK_SECRET: "s",
    TELEGRAM_CHAT_ID: CHAT,
    BREVO_API_KEY: "",
    OWNER_INBOX: "",
    SENDER_FROM: "",
    ...overrides,
  } as unknown as Parameters<typeof worker.fetch>[1];
}

test("POST / signs the report when the install token proves the link", async () => {
  const kv = await linkedKv();
  const telegram = stubTelegram();
  try {
    const response = await worker.fetch(reportRequest(TOKEN), workerEnv(kv), {} as never);

    assert.equal(response.status, 200);
    assert.equal(
      telegram.calls[0].json?.name,
      "BUG · v0.9.3-alpha · verified by Telegram · @brook",
    );
    const summary = JSON.stringify(telegram.calls[1].json);
    assert.ok(summary.includes("👤 @brook · verified by Telegram"));
    const document = await (telegram.calls[2].form?.get("document") as Blob).text();
    assert.ok(document.includes("Reported by: 👤 @brook · verified by Telegram"));

    assert.equal(summary.includes(TOKEN), false);
    assert.equal(document.includes(TOKEN), false);
  } finally {
    telegram.restore();
  }
});

test("POST / never trusts a token the relay did not hand over", async () => {
  const kv = await linkedKv();
  const telegram = stubTelegram();
  try {
    const response = await worker.fetch(
      reportRequest("f".repeat(64)),
      workerEnv(kv),
      {} as never,
    );

    assert.equal(response.status, 200);
    const summary = JSON.stringify(telegram.calls[1].json);
    assert.ok(summary.includes("👤 sin contacto"));
    assert.equal(summary.includes("verified by Telegram"), false);
  } finally {
    telegram.restore();
  }
});

test("POST / labels a configured Owner id as owner, never as verification", async () => {
  const kv = await linkedKv();
  const telegram = stubTelegram();
  try {
    await worker.fetch(
      reportRequest(TOKEN),
      workerEnv(kv, { OWNER_TELEGRAM_USER_IDS: "42, 1234567890" }),
      {} as never,
    );

    const summary = JSON.stringify(telegram.calls[1].json);
    assert.ok(summary.includes("👤 owner"));
    assert.equal(summary.includes("verified by Telegram"), false);
  } finally {
    telegram.restore();
  }
});
