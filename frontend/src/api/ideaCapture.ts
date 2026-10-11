import { apiFetch } from "@/api/client";
import type {
  ChatDiscoveryResult,
  IdeaCaptureAuthorizeResult,
  IdeaCaptureConfig,
  IdeaCaptureStatus,
  TelegramTestResult,
  TokenStatus,
} from "@/api/types";

// All idea-capture endpoints live behind the local-dev session boundary, so
// every call carries the HttpOnly session cookie (same-origin credentials),
// matching the secure-editing API.

const CREDENTIALS = { credentials: "same-origin" as const };

/** GET /api/idea-capture/status — config, validation, token presence, and
 *  the exact serve command for the current local runtime. */
export function getIdeaCaptureStatus(): Promise<IdeaCaptureStatus> {
  return apiFetch<IdeaCaptureStatus>("/api/idea-capture/status", CREDENTIALS);
}

/** PUT /api/idea-capture/config — validate and persist config/idea-capture.yaml.
 *  Empty allowlists are preserved (fail-closed). */
export function saveIdeaCaptureConfig(
  config: IdeaCaptureConfig,
): Promise<IdeaCaptureStatus> {
  return apiFetch<IdeaCaptureStatus>("/api/idea-capture/config", {
    method: "PUT",
    body: JSON.stringify({ config }),
    ...CREDENTIALS,
  });
}

/** POST /api/idea-capture/token — store TELEGRAM_BOT_TOKEN server-side (.env).
 *  The token is never returned; the response only confirms presence. */
export function setIdeaCaptureToken(token: string): Promise<TokenStatus> {
  return apiFetch<TokenStatus>("/api/idea-capture/token", {
    method: "POST",
    body: JSON.stringify({ token }),
    ...CREDENTIALS,
  });
}

/** DELETE /api/idea-capture/token — remove the stored bot token. */
export function clearIdeaCaptureToken(): Promise<TokenStatus> {
  return apiFetch<TokenStatus>("/api/idea-capture/token", {
    method: "DELETE",
    ...CREDENTIALS,
  });
}

/** POST /api/idea-capture/test-connection — ask the server to probe the stored
 *  token against Telegram (getMe). The token is read server-side and never
 *  crosses the wire; the response reports the resulting Telegram card state.
 *  Generous timeout: the probe performs a live Telegram round-trip. */
export function testTelegramConnection(): Promise<TelegramTestResult> {
  return apiFetch<TelegramTestResult>("/api/idea-capture/test-connection", {
    method: "POST",
    timeout: 20_000,
    ...CREDENTIALS,
  });
}

/** POST /api/idea-capture/chats/discover — read-only getUpdates snapshot
 *  (offset=-1: confirms nothing), so discovery never loses pending messages.
 *  Refuses with 409 while the real serve owner holds the bot lock (no second
 *  polling consumer). */
export function discoverChatCandidates(): Promise<ChatDiscoveryResult> {
  return apiFetch<ChatDiscoveryResult>("/api/idea-capture/chats/discover", {
    method: "POST",
    timeout: 10_000,
    ...CREDENTIALS,
  });
}

/** Explicit authorization payload for a discovered chat. */
export interface AuthorizeChatInput {
  /** Internal selection value returned by discovery. */
  chat_id: number;
  /** Telegram chat type from the candidate: private | group | supergroup. */
  chat_type: string;
  /** Required for group/supergroup chats (fail-closed). */
  sender_ids?: number[];
  /** Required for group/supergroup chats — must be exactly true. */
  confirm_group?: boolean;
}

/** POST /api/idea-capture/chats/authorize — persist an explicit chat
 *  authorization through the existing config writer. Returns the refreshed
 *  panel status plus a friendly confirmation message. */
export function authorizeChat(
  input: AuthorizeChatInput,
): Promise<IdeaCaptureAuthorizeResult> {
  return apiFetch<IdeaCaptureAuthorizeResult>("/api/idea-capture/chats/authorize", {
    method: "POST",
    body: JSON.stringify(input),
    ...CREDENTIALS,
  });
}
