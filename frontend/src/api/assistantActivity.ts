import type {
  AssistantActivityEvent,
  AssistantActivityTerminalStatus,
} from "@/api/types";

export const INCOMPLETE_EVIDENCE_WARNING = "Evidence incomplete.";
export const NEUTRAL_EVIDENCE_WARNING = "No confirmed world evidence.";

const SAFE_WARNINGS = new Set([
  INCOMPLETE_EVIDENCE_WARNING,
  NEUTRAL_EVIDENCE_WARNING,
]);
const SAFE_OPERATIONS = new Set(["Search world", "Read world"]);
const SAFE_STATUSES = new Set(["running", "succeeded", "failed"]);
const SAFE_TERMINAL_STATUSES = new Set(["succeeded", "failed", "unknown"]);
const SAFE_UNAVAILABLE_REASONS = new Set([
  "file_evidence_contract_unverified",
  "provider_activity_unavailable",
]);

export type AssistantActivityUnavailableReason =
  | "file_evidence_contract_unverified"
  | "provider_activity_unavailable";

export interface AssistantActivityRequest {
  prompt: string;
  session_id: string;
  section?: string;
  file_path?: string;
}

export class AssistantActivityUnavailable extends Error {
  constructor(
    public readonly status: number,
    public readonly reasonCode: AssistantActivityUnavailableReason =
      "provider_activity_unavailable",
  ) {
    super("Assistant activity is unavailable");
    this.name = "AssistantActivityUnavailable";
  }
}

export interface AssistantActivityStreamResult {
  accepted: boolean;
  events: AssistantActivityEvent[];
  answer: string | null;
  terminalStatus: AssistantActivityTerminalStatus | null;
}

export interface StreamAssistantActivityOptions {
  signal?: AbortSignal;
  onAccepted?: () => void;
  onEvent?: (event: AssistantActivityEvent) => void;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isSafePath(value: unknown): value is string {
  if (typeof value !== "string" || !value || value.includes("\\") || value.startsWith("/")) {
    return false;
  }
  const parts = value.split("/");
  return (
    ["lore", "personajes", "sagas", "referencias", "media"].includes(parts[0]) &&
    parts.every((part) => part && part !== "." && part !== ".." && !part.startsWith("."))
  );
}

/** Accept only the application-owned normalized SSE contract. */
export function parseAssistantActivityEvent(
  value: unknown,
  expectedRequestId?: string,
): AssistantActivityEvent | null {
  if (!isRecord(value) || typeof value.request_id !== "string" || !value.request_id) {
    return null;
  }
  if (expectedRequestId && value.request_id !== expectedRequestId) return null;

  if (value.kind === "activity") {
    if (
      typeof value.item_id !== "string" ||
      !value.item_id ||
      typeof value.operation !== "string" ||
      !SAFE_OPERATIONS.has(value.operation) ||
      typeof value.status !== "string" ||
      !SAFE_STATUSES.has(value.status)
    ) {
      return null;
    }
    const event: AssistantActivityEvent = {
      kind: "activity",
      request_id: value.request_id,
      item_id: value.item_id,
      operation: value.operation as "Search world" | "Read world",
      status: value.status as "running" | "succeeded" | "failed",
    };
    if (isSafePath(value.path)) event.path = value.path;
    if (typeof value.warning === "string" && SAFE_WARNINGS.has(value.warning)) {
      event.warning = value.warning;
    }
    return event;
  }

  if (value.kind === "answer") {
    return typeof value.response === "string"
      ? { kind: "answer", request_id: value.request_id, response: value.response }
      : null;
  }

  if (value.kind === "terminal") {
    if (
      typeof value.status !== "string" ||
      !SAFE_TERMINAL_STATUSES.has(value.status)
    ) {
      return null;
    }
    const event: AssistantActivityEvent = {
      kind: "terminal",
      request_id: value.request_id,
      status: value.status as AssistantActivityTerminalStatus,
    };
    if (typeof value.warning === "string" && SAFE_WARNINGS.has(value.warning)) {
      event.warning = value.warning;
    }
    return event;
  }

  return null;
}

function unavailableStatus(status: number): boolean {
  return status === 404 || status === 501 || status === 503;
}

export async function streamAssistantActivity(
  mundo: string,
  request: AssistantActivityRequest,
  options: StreamAssistantActivityOptions = {},
): Promise<AssistantActivityStreamResult> {
  const response = await fetch(
    `/api/${encodeURIComponent(mundo)}/ai/ask/activity`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
      signal: options.signal,
    },
  );
  if (!response.ok) {
    if (unavailableStatus(response.status)) {
      const body = await response.json().catch(() => ({}));
      const reasonCode =
        isRecord(body) &&
        typeof body.reason_code === "string" &&
        SAFE_UNAVAILABLE_REASONS.has(body.reason_code)
          ? (body.reason_code as AssistantActivityUnavailableReason)
          : "provider_activity_unavailable";
      throw new AssistantActivityUnavailable(response.status, reasonCode);
    }
    throw new Error("Assistant activity request failed");
  }
  if (!response.body) throw new Error("Assistant activity stream is empty");
  options.onAccepted?.();

  const events: AssistantActivityEvent[] = [];
  let answer: string | null = null;
  let terminalStatus: AssistantActivityTerminalStatus | null = null;
  let requestId = response.headers.get("X-Assistant-Activity-Request-Id") ?? "";
  let buffer = "";
  let dataLines: string[] = [];
  let terminalSeen = false;

  const handleRecord = (data: string): void => {
    let raw: unknown;
    try {
      raw = JSON.parse(data) as unknown;
    } catch {
      return;
    }
    const event = parseAssistantActivityEvent(raw, requestId || undefined);
    if (!event || terminalSeen) return;
    requestId ||= event.request_id;
    events.push(event);
    options.onEvent?.(event);
    if (event.kind === "answer") answer = event.response;
    if (event.kind === "terminal") {
      terminalStatus = event.status;
      terminalSeen = true;
    }
  };

  const dispatch = (line: string): void => {
    if (line === "") {
      if (dataLines.length) handleRecord(dataLines.join("\n"));
      dataLines = [];
      return;
    }
    if (line.startsWith("data:")) dataLines.push(line.slice(5).trimStart());
  };

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  while (true) {
    const chunk = await reader.read();
    buffer += decoder.decode(chunk.value ?? new Uint8Array(), { stream: !chunk.done });
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";
    lines.forEach(dispatch);
    if (chunk.done) break;
  }
  if (buffer) dispatch(buffer);
  dispatch("");

  return { accepted: true, events, answer, terminalStatus };
}
