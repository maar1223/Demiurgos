import { ApiError } from "@/api/types";
import type { ChatAttachment } from "@/api/types";

/** Mirrors the server's per-turn cap so the composer can stop early. */
export const MAX_ATTACHMENTS_PER_TURN = 5;

/**
 * POST /api/{mundo}/ai/attachments — extract a `.docx`/`.pdf` for the chat.
 *
 * The server converts the document to text and returns an opaque reference;
 * the bytes never reach the model. Rejections carry the stable
 * `attachment.*` code, surfaced as an {@link ApiError} so callers localize it
 * through the shared catalogue (`localizeApiError`).
 */
export async function uploadChatAttachment(
  mundo: string,
  file: File,
  signal?: AbortSignal,
): Promise<ChatAttachment> {
  const form = new FormData();
  form.append("file", file);
  const response = await fetch(
    `/api/${encodeURIComponent(mundo)}/ai/attachments`,
    { method: "POST", body: form, signal },
  );

  if (!response.ok) {
    const body: unknown = await response.json().catch(() => ({}));
    const record = typeof body === "object" && body !== null
      ? (body as Record<string, unknown>)
      : {};
    const detail = typeof record.detail === "string" ? record.detail : undefined;
    const code = typeof record.code === "string" && record.code.length > 0
      ? record.code
      : undefined;
    throw new ApiError(
      response.status,
      detail ?? `HTTP ${response.status}`,
      detail,
      code,
    );
  }

  const body: unknown = await response.json();
  if (!isChatAttachment(body)) {
    throw new ApiError(0, "Malformed attachment response", undefined, undefined);
  }
  return body;
}

function isChatAttachment(value: unknown): value is ChatAttachment {
  if (typeof value !== "object" || value === null) return false;
  const record = value as Record<string, unknown>;
  return (
    typeof record.id === "string" &&
    record.id.length > 0 &&
    typeof record.name === "string" &&
    (record.kind === "docx" || record.kind === "pdf" || record.kind === "image") &&
    typeof record.chars === "number" &&
    typeof record.truncated === "boolean"
  );
}

/** Relative URL of the bounded preview JPEG for one image attachment (S17). */
export function chatAttachmentThumbnailUrl(
  mundo: string,
  attachmentId: string,
): string {
  return `/api/${encodeURIComponent(mundo)}/ai/attachments/${encodeURIComponent(attachmentId)}/thumbnail`;
}
