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
  options: { key?: string | null; method?: string; token?: string } = {},
): Request {
  const headers: Record<string, string> = { "content-type": "application/json" };
  const presented = options.key === undefined ? KEY : options.key;
  if (presented !== null) {
    headers["x-relay-key"] = presented;
  }
  if (options.token !== undefined) {
    headers["x-install-token"] = options.token;
  }
  return new Request(`https://relay.example${path}`, {
    method: options.method ?? "POST",
    headers,
    body: options.method === "GET" ? undefined : JSON.stringify(body),
  });
}

/** Link one account end to end and return the install token it was handed. */
async function linkedToken(
  kv: MemoryKv,
  env: Parameters<typeof worker.fetch>[1],
  accountKey: string,
  telegramId = "1234567890",
  username = "brook",
): Promise<string> {
  const started = await worker.fetch(
    call("/link/start", { account_key: accountKey }),
    env,
    {} as never,
  );
  const { ticket } = (await started.json()) as Record<string, string>;
  await redeemTicket(
    kv,
    ticket,
    { id: telegramId, username, displayName: username },
    new Date(),
  );
  const polled = await worker.fetch(
    call("/link/status", { ticket }),
    env,
    {} as never,
  );
  const body = (await polled.json()) as Record<string, unknown>;
  assert.equal(body.state, "linked");
  return body.install_token as string;
}

test("the client routes need no shared key, but self-service needs the token", async () => {
  const kv = new MemoryKv();
  const env = makeEnv(kv);

  // An install that cannot carry a secret can still start a link and poll it.
  const started = await worker.fetch(
    call("/link/start", { account_key: "acct_open01" }, { key: null }),
    env,
    {} as never,
  );
  assert.equal(started.status, 200);

  // Reading or revoking a link requires the token the relay issued at handover,
  // so a guessed account key can never reveal or destroy somebody's link.
  for (const path of ["/link/state", "/link/revoke"]) {
    const response = await worker.fetch(call(path, {}, { key: null }), env, {} as never);
    assert.equal(response.status, 401, path);
    assert.deepEqual(await response.json(), { ok: false, code: "relay.unauthorized" });
  }
});

test("the client routes need the identity store, not the shared key", async () => {
  const kv = new MemoryKv();

  const withoutKey = await worker.fetch(
    call("/link/start", { account_key: "acct_open02" }, { key: null }),
    makeEnv(kv, { RELAY_KEY: "" }),
    {} as never,
  );
  assert.equal(withoutKey.status, 200);

  // No store is a configuration failure, and it fails closed.
  const withoutStore = await worker.fetch(
    call("/link/start", { account_key: "acct_open02" }, { key: null }),
    makeEnv(kv, { LINKS: undefined }),
    {} as never,
  );
  assert.equal(withoutStore.status, 500);
  assert.deepEqual(await withoutStore.json(), {
    ok: false,
    code: "relay.not_configured",
  });
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

  // Revoking is self-service: no token, no revoke.
  const anonymous = await worker.fetch(
    call("/link/revoke", { account_key: "acct_abc123" }),
    env,
    {} as never,
  );
  assert.equal(anonymous.status, 401);
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

test("a malformed body is rejected before any work happens", async () => {
  const kv = new MemoryKv();
  const response = await worker.fetch(
    new Request("https://relay.example/link/start", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: "{not json",
    }),
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
    // The per-IP budget is consumed (that is the point), but no ticket exists.
    assert.equal(
      [...kv.map.keys()].some((key) => key.startsWith("ticket:")),
      false,
      `${bad} left a ticket behind`,
    );
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
  assert.equal(
    [...kv.map.keys()].some((key) => key.startsWith("ticket:")),
    false,
  );
});

test("a ticket minted before a revoke cannot be redeemed", async () => {
  const kv = new MemoryKv();
  const env = makeEnv(kv);

  const token = await linkedToken(kv, env, "acct_http03");

  const started = await worker.fetch(
    call("/link/start", { account_key: "acct_http03" }),
    env,
    {} as never,
  );
  const { ticket } = (await started.json()) as Record<string, string>;

  // Revoking is self-service: the token is the proof, the account key is not.
  const revoked = await worker.fetch(
    call("/link/revoke", {}, { token }),
    env,
    {} as never,
  );
  assert.equal(revoked.status, 200);
  assert.equal(((await revoked.json()) as Record<string, unknown>).revoked, true);

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

test("ticket minting is bounded per IP even without a shared key", async () => {
  const kv = new MemoryKv();
  const env = makeEnv(kv);

  let last = 0;
  for (let i = 0; i < 11; i += 1) {
    const response = await worker.fetch(
      call("/link/start", { account_key: `acct_ip_${i}` }, { key: null }),
      env,
      {} as never,
    );
    last = response.status;
  }

  // A distinct account key per call escapes the per-account ceiling, so the IP
  // budget is what has to stop it.
  assert.equal(last, 429);
});

test("state answers unlinked for an unknown token and linked for the real one", async () => {
  const kv = new MemoryKv();
  const env = makeEnv(kv);

  const unknown = await worker.fetch(
    call("/link/state", {}, { token: "a".repeat(64) }),
    env,
    {} as never,
  );
  assert.equal(unknown.status, 200);
  assert.deepEqual(await unknown.json(), { ok: true, state: "unlinked" });

  const token = await linkedToken(kv, env, "acct_state01");
  const after = await worker.fetch(
    call("/link/state", {}, { token }),
    env,
    {} as never,
  );
  assert.equal(after.status, 200);
  const body = (await after.json()) as Record<string, unknown>;
  assert.equal(body.state, "linked");
  const identity = body.identity as Record<string, unknown>;
  assert.equal(identity.username, "brook");
  // A state read never hands back a signing credential.
  assert.equal("install_token" in identity, false);
  assert.equal("install_token" in body, false);
});

test("state refuses a caller without a token and exposes no account key", async () => {
  const kv = new MemoryKv();
  const env = makeEnv(kv);

  const missing = await worker.fetch(call("/link/state", {}), env, {} as never);
  assert.equal(missing.status, 401);
  assert.deepEqual(await missing.json(), { ok: false, code: "relay.unauthorized" });

  // The token is the only anchor: naming somebody's account key, with or without
  // the shared key, does not reach the store at all.
  const byAccount = await worker.fetch(
    call("/link/state", { account_key: "acct_state02" }, { token: "b".repeat(64) }),
    env,
    {} as never,
  );
  assert.deepEqual(await byAccount.json(), { ok: true, state: "unlinked" });

  const token = await linkedToken(kv, env, "acct_state03");
  const response = await worker.fetch(
    call("/link/state", {}, { token }),
    env,
    {} as never,
  );
  const body = (await response.json()) as Record<string, unknown>;
  assert.equal(body.state, "linked");
  // The caller renders a handle and two flags; nothing else leaves the store.
  assert.deepEqual(
    Object.keys(body.identity as Record<string, unknown>).sort(),
    ["display_name", "permissions", "username"],
  );
});

test("the open link routes fail CLOSED when the counter store errors", async () => {
  const kv = new MemoryKv();
  const broken = {
    get: async () => {
      throw new Error("kv.down");
    },
    put: async () => {
      throw new Error("kv.down");
    },
    delete: async () => undefined,
  };
  const env = makeEnv(kv, { RATE_LIMIT: broken });

  for (const [path, body] of [
    ["/link/start", { account_key: "acct_x" }],
    ["/link/status", { ticket: "ABCD1234" }],
  ] as const) {
    const response = await worker.fetch(call(path, body, { key: null }), env, {} as never);
    assert.equal(response.status, 503, path);
    assert.deepEqual(await response.json(), {
      ok: false,
      code: "relay.rate_limit_unavailable",
    });
  }
});

test("binding a guessed account key neither locks out nor erases the owner", async () => {
  const kv = new MemoryKv();
  const env = makeEnv(kv);
  const ownerToken = await linkedToken(kv, env, "acct_bound01");

  // The owner keeps the ability to mint again: token loss must not lock anybody
  // out of linking (S19).
  const again = await worker.fetch(
    call("/link/start", { account_key: "acct_bound01" }, { key: null }),
    env,
    {} as never,
  );
  assert.equal(again.status, 200);

  // A second Telegram claims the same account key: the pointer moves, but the
  // owner's identity and token survive, so their reports stay signed.
  const intruderToken = await linkedToken(kv, env, "acct_bound01", "2234567890", "other");
  const ownerState = await worker.fetch(
    call("/link/state", {}, { token: ownerToken }),
    env,
    {} as never,
  );
  const ownerBody = (await ownerState.json()) as Record<string, unknown>;
  assert.equal(ownerBody.state, "linked");
  assert.equal((ownerBody.identity as Record<string, unknown>).username, "brook");

  // Revoking with the owner's token revokes the owner, never the intruder's.
  const ownerRevoke = await worker.fetch(
    call("/link/revoke", {}, { token: ownerToken }),
    env,
    {} as never,
  );
  assert.deepEqual(await ownerRevoke.json(), { ok: true, revoked: true });
  const intruderState = await worker.fetch(
    call("/link/state", {}, { token: intruderToken }),
    env,
    {} as never,
  );
  assert.equal(((await intruderState.json()) as Record<string, unknown>).state, "linked");
});

test("operator reset clears a stuck binding, and needs the shared key", async () => {
  const kv = new MemoryKv();
  const env = makeEnv(kv);
  await linkedToken(kv, env, "acct_stuck01");

  const refused = await worker.fetch(
    call("/link/reset", { account_key: "acct_stuck01" }, { key: null }),
    env,
    {} as never,
  );
  assert.equal(refused.status, 401);

  const reset = await worker.fetch(
    call("/link/reset", { account_key: "acct_stuck01" }),
    env,
    {} as never,
  );
  assert.equal(reset.status, 200);
  assert.deepEqual(await reset.json(), { ok: true, revoked: true });

  const id = await worker.fetch(
    call("/link/start", { account_key: "acct_stuck01" }, { key: null }),
    env,
    {} as never,
  );
  assert.equal(id.status, 200);
});

test("a valid install token ignores a foreign account key", async () => {
  const kv = new MemoryKv();
  const env = makeEnv(kv);
  const foreignToken = await linkedToken(kv, env, "acct_foreign", "2234567890", "other");
  const mine = await linkedToken(kv, env, "acct_mine");

  const state = await worker.fetch(
    call("/link/state", { account_key: "acct_foreign" }, { token: mine }),
    env,
    {} as never,
  );
  const body = (await state.json()) as Record<string, unknown>;
  assert.equal(body.state, "linked");
  assert.equal((body.identity as Record<string, unknown>).username, "brook");
  const raw = JSON.stringify(body);
  for (const secret of [mine, "acct_mine", "acct_foreign", "1234567890"]) {
    assert.equal(raw.includes(secret), false, secret);
  }

  // Revoking with my token revokes MY link, never the one named in the body.
  const revoke = await worker.fetch(
    call("/link/revoke", { account_key: "acct_foreign" }, { token: mine }),
    env,
    {} as never,
  );
  assert.deepEqual(await revoke.json(), { ok: true, revoked: true });
  const untouched = await worker.fetch(
    call("/link/state", {}, { token: foreignToken }),
    env,
    {} as never,
  );
  assert.equal(((await untouched.json()) as Record<string, unknown>).state, "linked");
});
