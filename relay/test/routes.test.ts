/**
 * Route-level tests for the identity endpoints.
 *
 * The Worker is exercised through its exported `fetch`, with an in-memory KV
 * standing in for both namespaces, so the guard (shared key), the routing and
 * the wire shape are pinned without a Workers runtime.
 */

import { test } from "node:test";
import assert from "node:assert/strict";

import worker from "../src/index.ts";
import { LinkError, redeemTicket } from "../src/linking.ts";
import type { KvLike } from "../src/identity.ts";

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

const KEY = "shared-relay-key";

function makeEnv(kv: MemoryKv, overrides: Record<string, unknown> = {}) {
  return {
    RATE_LIMIT: kv,
    LINKS: kv,
    RELAY_KEY: KEY,
    BREVO_API_KEY: "",
    OWNER_INBOX: "",
    SENDER_FROM: "",
    ...overrides,
  } as unknown as Parameters<typeof worker.fetch>[1];
}

function call(
  path: string,
  body: unknown,
  options: { key?: string | null; method?: string } = {},
): Request {
  const headers: Record<string, string> = { "content-type": "application/json" };
  const presented = options.key === undefined ? KEY : options.key;
  if (presented !== null) {
    headers["x-relay-key"] = presented;
  }
  return new Request(`https://relay.example${path}`, {
    method: options.method ?? "POST",
    headers,
    body: options.method === "GET" ? undefined : JSON.stringify(body),
  });
}

test("identity routes refuse a caller without the shared key", async () => {
  const kv = new MemoryKv();
  const response = await worker.fetch(
    call("/link/start", { account_key: "acct_abc123" }, { key: null }),
    makeEnv(kv),
    {} as never,
  );

  assert.equal(response.status, 401);
  assert.deepEqual(await response.json(), { ok: false, code: "relay.unauthorized" });
});

test("identity routes fail closed when the shared key is not configured", async () => {
  const kv = new MemoryKv();
  const response = await worker.fetch(
    call("/link/start", { account_key: "acct_abc123" }),
    makeEnv(kv, { RELAY_KEY: "" }),
    {} as never,
  );

  assert.equal(response.status, 500);
  assert.deepEqual(await response.json(), { ok: false, code: "relay.not_configured" });
});

test("start mints a ticket, status reports it pending, revoke answers", async () => {
  const kv = new MemoryKv();
  const env = makeEnv(kv);

  const started = await worker.fetch(
    call("/link/start", { account_key: "acct_abc123" }),
    env,
    {} as never,
  );
  assert.equal(started.status, 200);
  const startedBody = (await started.json()) as Record<string, unknown>;
  assert.equal(typeof startedBody.ticket, "string");
  assert.equal((startedBody.ticket as string).length, 8);
  assert.equal(startedBody.reused, false);

  const pending = await worker.fetch(
    call("/link/status", { ticket: startedBody.ticket }),
    env,
    {} as never,
  );
  assert.equal(pending.status, 200);
  assert.equal(((await pending.json()) as Record<string, unknown>).state, "pending");

  const revoked = await worker.fetch(
    call("/link/revoke", { account_key: "acct_abc123" }),
    env,
    {} as never,
  );
  assert.equal(revoked.status, 200);
  assert.equal(((await revoked.json()) as Record<string, unknown>).revoked, false);
});

test("a ticket is never accepted from a URL, only from the POST body", async () => {
  const kv = new MemoryKv();
  const response = await worker.fetch(
    new Request("https://relay.example/link/status?ticket=ABCDEFGH", {
      method: "GET",
      headers: { "x-relay-key": KEY },
    }),
    makeEnv(kv),
    {} as never,
  );

  assert.equal(response.status, 405);
  assert.deepEqual(await response.json(), {
    ok: false,
    code: "relay.method_not_allowed",
  });
});

test("an unauthenticated bad body is rejected before it is parsed", async () => {
  const kv = new MemoryKv();
  const response = await worker.fetch(
    new Request("https://relay.example/link/start", {
      method: "POST",
      headers: { "x-relay-key": "wrong", "content-type": "application/json" },
      body: "{not json",
    }),
    makeEnv(kv),
    {} as never,
  );

  assert.equal(response.status, 401);
});

test("unknown paths are 404, not 405", async () => {
  const kv = new MemoryKv();
  const response = await worker.fetch(
    new Request("https://relay.example/link/nope", { method: "GET" }),
    makeEnv(kv),
    {} as never,
  );

  assert.equal(response.status, 404);
  assert.deepEqual(await response.json(), { ok: false, code: "relay.not_found" });
});

test("POST /link/start accepts vault usernames and refuses only unusable keys", async () => {
  for (const key of ["ana", "Mr. Smith", "jose@example.com"]) {
    const kv = new MemoryKv();
    const response = await worker.fetch(
      call("/link/start", { account_key: key }),
      makeEnv(kv),
      {} as never,
    );
    assert.equal(response.status, 200, `${key} was refused`);
  }

  for (const bad of ["", " ana", "ana\u0000x", "x".repeat(401)]) {
    const kv = new MemoryKv();
    const response = await worker.fetch(
      call("/link/start", { account_key: bad }),
      makeEnv(kv),
      {} as never,
    );
    assert.equal(response.status, 400);
    assert.deepEqual(await response.json(), {
      ok: false,
      code: "link.invalid_account",
    });
    assert.equal(kv.map.size, 0);
  }
});

test("a flag omitted when a live ticket is reused keeps its stored value", async () => {
  const kv = new MemoryKv();
  const env = makeEnv(kv);

  const first = await worker.fetch(
    call("/link/start", {
      account_key: "acct_http01",
      report_identity: false,
      notify_releases: false,
    }),
    env,
    {} as never,
  );
  const firstBody = (await first.json()) as Record<string, unknown>;

  const reuse = await worker.fetch(
    call("/link/start", { account_key: "acct_http01" }),
    env,
    {} as never,
  );
  const reuseBody = (await reuse.json()) as Record<string, unknown>;
  assert.equal(reuseBody.reused, true);
  assert.equal(reuseBody.ticket, firstBody.ticket);

  const identity = await redeemTicket(
    kv,
    reuseBody.ticket as string,
    { id: "1234567890", username: "brook", displayName: "Brook" },
    new Date(),
  );
  assert.deepEqual(identity.permissions, {
    report_identity: false,
    notify_releases: false,
  });
});

test("a non-boolean permission flag is rejected, never coerced", async () => {
  const kv = new MemoryKv();
  const response = await worker.fetch(
    call("/link/start", { account_key: "acct_http02", notify_releases: "false" }),
    makeEnv(kv),
    {} as never,
  );

  assert.equal(response.status, 400);
  assert.deepEqual(await response.json(), {
    ok: false,
    code: "relay.invalid_payload",
  });
  assert.equal(kv.map.size, 0);
});

test("a ticket minted before an HTTP revoke cannot be redeemed", async () => {
  const kv = new MemoryKv();
  const env = makeEnv(kv);

  const started = await worker.fetch(
    call("/link/start", { account_key: "acct_http03" }),
    env,
    {} as never,
  );
  const { ticket } = (await started.json()) as Record<string, string>;
  await worker.fetch(
    call("/link/revoke", { account_key: "acct_http03" }),
    env,
    {} as never,
  );

  await assert.rejects(
    () => redeemTicket(kv, ticket, { id: "1234567890" }, new Date()),
    (error: unknown) => error instanceof LinkError && error.code === "link.ticket_invalid",
  );
});

test("an explicit single flag on reuse applies without touching the other", async () => {
  const kv = new MemoryKv();
  const env = makeEnv(kv);

  await worker.fetch(
    call("/link/start", {
      account_key: "acct_http04",
      report_identity: false,
      notify_releases: false,
    }),
    env,
    {} as never,
  );
  const reuse = await worker.fetch(
    call("/link/start", { account_key: "acct_http04", notify_releases: true }),
    env,
    {} as never,
  );
  const { ticket } = (await reuse.json()) as Record<string, string>;

  const identity = await redeemTicket(
    kv,
    ticket,
    { id: "1234567891" },
    new Date(),
  );
  assert.deepEqual(identity.permissions, {
    report_identity: false,
    notify_releases: true,
  });
});
