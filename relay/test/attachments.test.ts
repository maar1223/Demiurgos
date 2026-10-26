/**
 * Screenshot attachments (S5).
 *
 * Up to two images, 5 MB each, chosen explicitly by the person. The relay
 * receives them as multipart file parts — never inside the JSON bundle, which is
 * capped at 98 KB — and publishes each as a **document**, because `sendPhoto`
 * recompresses and destroys exactly the UI detail the screenshot exists to show.
 */

import { test } from "node:test";
import assert from "node:assert/strict";

import worker from "../src/index.ts";
import { publishReport, type ReportAttachment } from "../src/publication.ts";

const BOT = "123456:fake-bot-token";
const CHAT = "-1001234567890";

const REPORT = {
  schema: 2,
  app_version: "0.9.3-alpha",
  platform: { os: "linux" },
  description: "El selector de relaciones se queda vacío.",
  contact: null,
  logs: null,
  context: { route: "/perfil", view: "perfil" },
};

class MemoryKv {
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

function env(kv: MemoryKv, overrides: Record<string, unknown> = {}) {
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

const PNG_BYTES = new Uint8Array([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 0x00]);

function multipartRequest(
  report: Record<string, unknown> = REPORT,
  files: Array<{ name: string; type: string; bytes: Uint8Array }>,
  headers: Record<string, string> = {},
): Request {
  const form = new FormData();
  form.set("report", JSON.stringify(report));
  for (const file of files) {
    form.append(
      "attachments",
      new File([file.bytes], file.name, { type: file.type }),
      file.name,
    );
  }
  return new Request("https://relay.example/", {
    method: "POST",
    headers: { "CF-Connecting-IP": "203.0.113.9", ...headers },
    body: form,
  });
}

test("two screenshots are published as documents before the bundle", async () => {
  const kv = new MemoryKv();
  const telegram = stubTelegram();
  try {
    const response = await worker.fetch(
      multipartRequest(REPORT, [
        { name: "pantalla-1.png", type: "image/png", bytes: PNG_BYTES },
        { name: "pantalla-2.png", type: "image/png", bytes: PNG_BYTES },
      ]),
      env(kv),
      {} as never,
    );

    assert.equal(response.status, 200);
    assert.deepEqual(
      telegram.calls.map((call) => call.method),
      ["createForumTopic", "sendMessage", "sendDocument", "sendDocument", "sendDocument"],
    );

    const first = telegram.calls[2].form;
    assert.ok(first !== null);
    assert.equal(first.get("chat_id"), CHAT);
    assert.equal(first.get("message_thread_id"), "7");
    const document = first.get("document");
    assert.ok(document instanceof File);
    assert.equal(document.name, "pantalla-1.png");
    assert.equal(document.type, "image/png");
    assert.match(String(first.get("caption")), /Captura 1/);

    // The summary never carries image bytes, only the text report.
    assert.equal(JSON.stringify(telegram.calls[1].json).includes("PNG"), false);
  } finally {
    telegram.restore();
  }
});

test("a third screenshot is refused", async () => {
  const kv = new MemoryKv();
  const telegram = stubTelegram();
  try {
    const response = await worker.fetch(
      multipartRequest(REPORT, [
        { name: "a.png", type: "image/png", bytes: PNG_BYTES },
        { name: "b.png", type: "image/png", bytes: PNG_BYTES },
        { name: "c.png", type: "image/png", bytes: PNG_BYTES },
      ]),
      env(kv),
      {} as never,
    );

    assert.equal(response.status, 413);
    assert.deepEqual(await response.json(), { ok: false, code: "relay.too_large" });
    assert.equal(telegram.calls.length, 0);
  } finally {
    telegram.restore();
  }
});

test("an oversized screenshot is refused before any Telegram call", async () => {
  const kv = new MemoryKv();
  const telegram = stubTelegram();
  try {
    const response = await worker.fetch(
      multipartRequest(REPORT, [
        {
          name: "huge.png",
          type: "image/png",
          bytes: new Uint8Array(5 * 1024 * 1024 + 1),
        },
      ]),
      env(kv),
      {} as never,
    );

    assert.equal(response.status, 413);
    assert.equal(telegram.calls.length, 0);
  } finally {
    telegram.restore();
  }
});

test("a non-image or empty file is refused", async () => {
  const kv = new MemoryKv();
  const telegram = stubTelegram();
  try {
    const notAnImage = await worker.fetch(
      multipartRequest(REPORT, [
        { name: "notes.txt", type: "text/plain", bytes: new Uint8Array([65]) },
      ]),
      env(kv),
      {} as never,
    );
    assert.equal(notAnImage.status, 400);
    assert.deepEqual(await notAnImage.json(), {
      ok: false,
      code: "relay.invalid_attachment",
    });

    const empty = await worker.fetch(
      multipartRequest(REPORT, [
        { name: "empty.png", type: "image/png", bytes: new Uint8Array() },
      ]),
      env(kv),
      {} as never,
    );
    assert.equal(empty.status, 400);
    assert.equal(telegram.calls.length, 0);
  } finally {
    telegram.restore();
  }
});

test("a path in the filename never becomes a path", async () => {
  const kv = new MemoryKv();
  const telegram = stubTelegram();
  try {
    await worker.fetch(
      multipartRequest(REPORT, [
        {
          name: "../../evil/../captura.png",
          type: "image/png",
          bytes: PNG_BYTES,
        },
      ]),
      env(kv),
      {} as never,
    );

    const document = telegram.calls[2].form?.get("document");
    assert.ok(document instanceof File);
    assert.equal(document.name, "captura.png");
  } finally {
    telegram.restore();
  }
});

test("a multipart body without the report part is refused", async () => {
  const kv = new MemoryKv();
  const form = new FormData();
  form.set("attachments", new File([PNG_BYTES], "a.png", { type: "image/png" }));

  const response = await worker.fetch(
    new Request("https://relay.example/", { method: "POST", body: form }),
    env(kv),
    {} as never,
  );

  assert.equal(response.status, 400);
  assert.deepEqual(await response.json(), {
    ok: false,
    code: "relay.invalid_payload",
  });
});

test("the email channel states the attachments it could not carry", async () => {
  const kv = new MemoryKv();
  const original = globalThis.fetch;
  const sent: Array<Record<string, unknown>> = [];
  globalThis.fetch = (async (_input: RequestInfo | URL, init?: RequestInit) => {
    sent.push(JSON.parse(String(init?.body ?? "{}")) as Record<string, unknown>);
    return new Response(JSON.stringify({ messageId: "m1" }), { status: 201 });
  }) as typeof fetch;
  try {
    const response = await worker.fetch(
      multipartRequest(REPORT, [
        { name: "a.png", type: "image/png", bytes: PNG_BYTES },
      ]),
      env(kv, {
        TELEGRAM_BOT_TOKEN: "",
        TELEGRAM_CHAT_ID: "",
        BREVO_API_KEY: "b",
        OWNER_INBOX: "owner@example.com",
        SENDER_FROM: "reports@example.com",
      }),
      {} as never,
    );

    assert.equal(response.status, 200);
    const body = String(sent[0]?.textContent ?? "");
    assert.match(body, /Attachments: 1 \(not delivered over email\)/);
    assert.equal(body.includes("PNG"), false);
  } finally {
    globalThis.fetch = original;
  }
});

test("publishing without attachments keeps the three-call sequence", async () => {
  const telegram = stubTelegram();
  try {
    const attachments: ReportAttachment[] = [];
    await publishReport(
      { TELEGRAM_BOT_TOKEN: BOT, TELEGRAM_CHAT_ID: CHAT },
      {
        app_version: "0.9.3-alpha",
        platform: { os: "linux" },
        description: "boom",
        contact: null,
        logs: null,
        context: {},
        attribution: {
          level: "none",
          line: "👤 sin contacto",
          tag: "sin contacto",
          label: "sin contacto",
          identity: null,
        },
      },
      "abc-123",
      attachments,
    );

    assert.deepEqual(
      telegram.calls.map((call) => call.method),
      ["createForumTopic", "sendMessage", "sendDocument"],
    );
  } finally {
    telegram.restore();
  }
});


test("a renamed text file is not an image, whatever it claims", async () => {
  const kv = new MemoryKv();
  const telegram = stubTelegram();
  try {
    const response = await worker.fetch(
      multipartRequest(REPORT, [
        {
          name: "captura.png",
          type: "image/png",
          bytes: new TextEncoder().encode("<html>hola</html>"),
        },
      ]),
      env(kv),
      {} as never,
    );

    assert.equal(response.status, 400);
    assert.deepEqual(await response.json(), {
      ok: false,
      code: "relay.invalid_attachment",
    });
    assert.equal(telegram.calls.length, 0);
  } finally {
    telegram.restore();
  }
});

test("the bytes decide the type, not the declared one", async () => {
  const kv = new MemoryKv();
  const telegram = stubTelegram();
  try {
    await worker.fetch(
      multipartRequest(REPORT, [
        { name: "captura.jpg", type: "image/jpeg", bytes: PNG_BYTES },
      ]),
      env(kv),
      {} as never,
    );

    const document = telegram.calls[2].form?.get("document");
    assert.ok(document instanceof File);
    assert.equal(document.type, "image/png");
  } finally {
    telegram.restore();
  }
});


const JPEG_BYTES = new Uint8Array([0xff, 0xd8, 0xff, 0xe0, 0, 16, 0x4a, 0x46]);
const WEBP_BYTES = new Uint8Array([
  0x52, 0x49, 0x46, 0x46, 0x10, 0, 0, 0, 0x57, 0x45, 0x42, 0x50, 0x56, 0x50, 0x38,
]);

test("exactly 5 MB is accepted and one byte more is refused", async () => {
  const exact = new Uint8Array(5 * 1024 * 1024);
  exact.set(PNG_BYTES);
  const over = new Uint8Array(5 * 1024 * 1024 + 1);
  over.set(PNG_BYTES);

  const okTg = stubTelegram();
  try {
    const ok = await worker.fetch(
      multipartRequest(REPORT, [{ name: "big.png", type: "image/png", bytes: exact }]),
      env(new MemoryKv()),
      {} as never,
    );
    assert.equal(ok.status, 200);
    const doc = okTg.calls[2].form?.get("document");
    assert.ok(doc instanceof File);
    assert.equal(doc.size, exact.length);
  } finally {
    okTg.restore();
  }

  const badTg = stubTelegram();
  try {
    const bad = await worker.fetch(
      multipartRequest(REPORT, [{ name: "big.png", type: "image/png", bytes: over }]),
      env(new MemoryKv()),
      {} as never,
    );
    assert.equal(bad.status, 413);
    assert.equal(badTg.calls.length, 0);
  } finally {
    badTg.restore();
  }
});

test("JPEG and WebP are typed by their bytes", async () => {
  const telegram = stubTelegram();
  try {
    await worker.fetch(
      multipartRequest(REPORT, [
        { name: "a.png", type: "image/png", bytes: JPEG_BYTES },
        { name: "b.bin", type: "text/plain", bytes: WEBP_BYTES },
      ]),
      env(new MemoryKv()),
      {} as never,
    );

    assert.equal((telegram.calls[2].form?.get("document") as File).type, "image/jpeg");
    assert.equal((telegram.calls[3].form?.get("document") as File).type, "image/webp");
  } finally {
    telegram.restore();
  }
});

test("a partial PNG signature is not a PNG", async () => {
  const telegram = stubTelegram();
  try {
    const response = await worker.fetch(
      multipartRequest(REPORT, [
        {
          name: "fake.png",
          type: "image/png",
          bytes: new Uint8Array([0x89, 0x50, 0x4e, 0x47, 0x41, 0x42, 0x43, 0x44]),
        },
      ]),
      env(new MemoryKv()),
      {} as never,
    );

    assert.equal(response.status, 400);
    assert.equal(telegram.calls.length, 0);
  } finally {
    telegram.restore();
  }
});

test("a filename part that is not a file is refused, not silently dropped", async () => {
  const kv = new MemoryKv();
  const form = new FormData();
  form.set("report", JSON.stringify(REPORT));
  form.append("attachments", "" as unknown as Blob);

  const response = await worker.fetch(
    new Request("https://relay.example/", { method: "POST", body: form }),
    env(kv),
    {} as never,
  );

  assert.equal(response.status, 400);
  assert.deepEqual(await response.json(), {
    ok: false,
    code: "relay.invalid_attachment",
  });
});

test("invisible characters are stripped from the filename", async () => {
  const telegram = stubTelegram();
  try {
    await worker.fetch(
      multipartRequest(REPORT, [
        {
          name: "a\u0085b\u202ec\u061cd\u2060e.png",
          type: "image/png",
          bytes: PNG_BYTES,
        },
      ]),
      env(new MemoryKv()),
      {} as never,
    );

    const document = telegram.calls[2].form?.get("document");
    assert.ok(document instanceof File);
    assert.equal(document.name, "abcde.png");
  } finally {
    telegram.restore();
  }
});

test("a screenshot you had forgotten is not swallowed by dedup", async () => {
  const kv = new MemoryKv();
  const first = stubTelegram();
  try {
    await worker.fetch(multipartRequest(REPORT, []), env(kv), {} as never);
  } finally {
    first.restore();
  }

  const second = stubTelegram();
  try {
    const response = await worker.fetch(
      multipartRequest(REPORT, [
        { name: "olvidada.png", type: "image/png", bytes: PNG_BYTES },
      ]),
      env(kv),
      {} as never,
    );

    assert.equal(response.status, 200);
    const body = (await response.json()) as Record<string, unknown>;
    assert.equal(body.deduped, undefined);
    // topic + summary + the screenshot + the bundle document
    assert.equal(second.calls.length, 4);
  } finally {
    second.restore();
  }

  const third = stubTelegram();
  try {
    const response = await worker.fetch(
      multipartRequest(REPORT, [
        { name: "olvidada.png", type: "image/png", bytes: PNG_BYTES },
      ]),
      env(kv),
      {} as never,
    );

    const body = (await response.json()) as Record<string, unknown>;
    assert.equal(body.deduped, true);
    assert.equal(third.calls.length, 0);
  } finally {
    third.restore();
  }
});
