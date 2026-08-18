import { apiFetch } from "@/api/client";
import type { TelegramStatus, TelegramTestResult } from "@/api/types";

// ONB-3.3 — Telegram configuration card API. All endpoints sit behind the
// local-dev session boundary (HttpOnly cookie), matching the other panels.
// The token is WRITE-ONLY: it leaves the browser only inside the PUT body and
// is stored server-side (.env); it is never returned, displayed, or logged.

const CREDENTIALS = { credentials: "same-origin" as const };

/** GET /api/telegram/status — card state; the token value is never returned. */
export function getTelegramStatus(): Promise<TelegramStatus> {
  return apiFetch<TelegramStatus>("/api/telegram/status", CREDENTIALS);
}

/** PUT /api/telegram/token — store the bot token write-only; the response
 *  confirms presence only and never echoes the value. */
export function setTelegramToken(token: string): Promise<TelegramStatus> {
  return apiFetch<TelegramStatus>("/api/telegram/token", {
    method: "PUT",
    body: JSON.stringify({ token }),
    ...CREDENTIALS,
  });
}

/** DELETE /api/telegram/token — remove the stored token; the card returns to
 *  pending. */
export function clearTelegramToken(): Promise<TelegramStatus> {
  return apiFetch<TelegramStatus>("/api/telegram/token", {
    method: "DELETE",
    ...CREDENTIALS,
  });
}

/** POST /api/telegram/test-connection — tests the STORED token server-side
 *  (Telegram getMe); the UI never sends a token in this call. */
export function testTelegramConnection(): Promise<TelegramTestResult> {
  return apiFetch<TelegramTestResult>("/api/telegram/test-connection", {
    method: "POST",
    timeout: 20_000,
    ...CREDENTIALS,
  });
}