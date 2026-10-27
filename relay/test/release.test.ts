/**
 * Release records (S12) — "this version fixed these reports".
 *
 * The list is public and anonymous: a version and the report ids it closed. The
 * app matches its own ids against it, so nobody has to store who reported what.
 */

import { test } from "node:test";
import assert from "node:assert/strict";

import worker from "../src/index.ts";
import { MAX_REPORT_IDS, readReleases } from "../src/release.ts";
import { publishReport } from "../src/publication.ts";

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

const KEY = "shared-key";

function env(kv: MemoryKv, overrides: Record<string, unknown> = {}) {
  return {
    RATE_LIMIT: kv,
    LINKS: kv,
    RELAY_KEY: KEY,
    TELEGRAM_BOT_TOKEN: "",
    TELEGRAM_WEBHOOK_SECRET: "",
    TELEGRAM_CHAT_ID: "",
    BREVO_API_KEY: "",
    OWNER_INBOX: "",
    SENDER_FROM: "",
    ...overrides,
  } as unknown as Parameters<typeof worker.fetch>[1];
}

function call(
  path: string,
  body: unknown,
  options: { key?: string | null } = {},
): Request {
  const headers: Record<string, string> = { "content-type": "application/json" };
  const presented = options.key === undefined ? KEY : options.key;
  if (presented !== null) {
    headers["x-relay-key"] = presented;
  }
  return new Request(`https://relay.example${path}`, {
    method: "POST",
    headers,
    body: JSON.stringify(body),
  });
}

test("a recorded release is readable and replaces an earlier call for the same version", async () => {
  const kv = new MemoryKv();

  const first = await worker.fetch(
    call("/release", { version: "v0.5.0", report_ids: ["11111111-aaaa"] }),
    env(kv),
    {} as never,
  );
  assert.equal(first.status, 200);

  const corrected = await worker.fetch(
    call("/release", {
      version: "v0.5.0",
      report_ids: ["11111111-aaaa", "22222222-bbbb"],
    }),
    env(kv),
    {} as never,
  );
  assert.equal(corrected.status, 200);

  const listed = await worker.fetch(call("/releases", {}), env(kv), {} as never);
  const body = (await listed.json()) as {
    ok: boolean;
    releases: Array<{ version: string; report_ids: string[]; at: string }>;
  };

  assert.equal(body.ok, true);
  assert.equal(body.releases.length, 1);
  assert.equal(body.releases[0].version, "v0.5.0");
  assert.deepEqual(body.releases[0].report_ids, ["11111111-aaaa", "22222222-bbbb"]);
  assert.equal(typeof body.releases[0].at, "string");
});

test("newer releases come first", async () => {
  const kv = new MemoryKv();
  await worker.fetch(
    call("/release", { version: "v0.4.0", report_ids: [] }),
    env(kv),
    {} as never,
  );
  await worker.fetch(
    call("/release", { version: "v0.5.0", report_ids: ["33333333-cccc"] }),
    env(kv),
    {} as never,
  );

  const releases = await readReleases(kv);

  assert.deepEqual(
    releases.map((release) => release.version),
    ["v0.5.0", "v0.4.0"],
  );
});

test("a duplicate report id is stored once", async () => {
  const kv = new MemoryKv();

  await worker.fetch(
    call("/release", {
      version: "v0.6.0",
      report_ids: ["44444444-dddd", "44444444-dddd"],
    }),
    env(kv),
    {} as never,
  );

  assert.deepEqual((await readReleases(kv))[0].report_ids, ["44444444-dddd"]);
});

test("writing a release needs the shared key, reading the list does not", async () => {
  const kv = new MemoryKv();

  const write = await worker.fetch(
    call("/release", { version: "v1", report_ids: [] }, { key: null }),
    env(kv),
    {} as never,
  );
  assert.equal(write.status, 401);

  // Every install shows "this was fixed" without holding any secret (S19): the
  // list is versions and report ids, never a reporter.
  const read = await worker.fetch(
    call("/releases", {}, { key: null }),
    env(kv),
    {} as never,
  );
  assert.equal(read.status, 200);
  assert.deepEqual(await read.json(), { ok: true, releases: [] });
});

test("a malformed version or report id is refused", async () => {
  const kv = new MemoryKv();

  for (const payload of [
    { version: "", report_ids: [] },
    { version: "x".repeat(65), report_ids: [] },
    { version: "v1", report_ids: [""] },
    { version: "v1", report_ids: ["has spaces"] },
    { version: "v1" },
  ]) {
    const response = await worker.fetch(
      call("/release", payload),
      env(kv),
      {} as never,
    );
    assert.equal(response.status, 400, JSON.stringify(payload));
  }
  assert.equal(kv.map.size, 0);
});

test("more report ids than the cap is refused", async () => {
  const kv = new MemoryKv();
  const ids = Array.from({ length: MAX_REPORT_IDS + 1 }, (_, index) => `id-${index}-aaaa`);

  const response = await worker.fetch(
    call("/release", { version: "v1", report_ids: ids }),
    env(kv),
    {} as never,
  );

  assert.equal(response.status, 413);
});

test("the topic summary carries the report id a release needs", async () => {
  const original = globalThis.fetch;
  const sent: Array<Record<string, unknown>> = [];
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const method = String(input).split("/").pop() ?? "";
    if (method === "createForumTopic") {
      return new Response(
        JSON.stringify({ ok: true, result: { message_thread_id: 7 } }),
        { status: 200 },
      );
    }
    const body = init?.body;
    if (typeof body === "string") {
      sent.push(JSON.parse(body) as Record<string, unknown>);
    }
    return new Response(JSON.stringify({ ok: true, result: {} }), { status: 200 });
  }) as typeof fetch;
  try {
    await publishReport(
      { TELEGRAM_BOT_TOKEN: "1:x", TELEGRAM_CHAT_ID: "-1" },
      {
        app_version: "0.9.3",
        platform: {},
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
      "55555555-eeee",
    );

    assert.match(String(sent[0]?.text), /🆔 55555555-eeee/);
  } finally {
    globalThis.fetch = original;
  }
});
