import { ApiError } from "@/api/types";
import type {
  AssistantActivityEvent,
  AssistantActivityTerminalStatus,
  SemanticDecisionAction,
  SemanticDecisionContinuation,
  SemanticDecisionEvent,
  SemanticDecisionState,
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
  "guided_handoff",
]);
const SEMANTIC_STATES = new Set<SemanticDecisionState>([
  "allow",
  "clarify",
  "require_confirmation",
  "proposal_ready",
  "blocked",
]);

// Provider-supplied authority claims never reach the client as typed
// continuations; any of these keys inside a delta fails the event closed.
const AUTHORITATIVE_CONTINUATION_KEYS = new Set([
  "target",
  "digest",
  "revision",
  "authority",
  "reference",
  "acceptance",
  "accepted_canon",
  "authorization",
]);
const MAX_CONTINUATION_DEPTH = 4;

function continuationDeltaHasAuthoritativeKey(value: unknown, depth = 0): boolean {
  if (depth > MAX_CONTINUATION_DEPTH) return true;
  if (isRecord(value)) {
    return Object.entries(value).some(([key, item]) =>
      AUTHORITATIVE_CONTINUATION_KEYS.has(key) ||
      continuationDeltaHasAuthoritativeKey(item, depth + 1),
    );
  }
  return false;
}

export type AssistantActivityUnavailableReason =
  | "file_evidence_contract_unverified"
  | "provider_activity_unavailable"
  | "guided_handoff";

export interface AssistantActivityRequest {
  prompt: string;
  session_id: string;
  section?: string;
  file_path?: string;
  guided_session_id?: string;
  guided_revision?: number;
  /** Opaque references to the conversation's uploaded documents. */
  attachment_ids?: string[];
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
  /**
   * The authoritative additive `semantic_decision` event, or `null` when the
   * stream lacked one (or emitted it out of order / malformed). Consumers MUST
   * treat `null` as fail-closed and never infer permission from answer text.
   */
  semanticDecision: SemanticDecisionEvent | null;
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
    ["lore", "personajes", "referencias", "media"].includes(parts[0]) &&
    parts.every((part) => part && part !== "." && part !== ".." && !part.startsWith("."))
  );
}

/**
 * Strictly validate a server `semantic_decision` continuation. Unknown,
 * malformed, or over-bounded continuations fail the whole event closed.
 */
function parseSemanticContinuation(
  value: unknown,
): { ok: true; continuation: SemanticDecisionContinuation | null } | { ok: false } {
  if (value === null) return { ok: true, continuation: null };
  if (!isRecord(value)) return { ok: false };
  const keys = Object.keys(value);
  const outcome = value.outcome;
  if (outcome === "question") {
    if (keys.length !== 2 || !Object.prototype.hasOwnProperty.call(value, "question")) {
      return { ok: false };
    }
    if (typeof value.question !== "string" || !value.question.trim()) return { ok: false };
    return { ok: true, continuation: { outcome: "question", question: value.question } };
  }
  if (outcome === "delta") {
    if (keys.length !== 2 || !Object.prototype.hasOwnProperty.call(value, "delta")) {
      return { ok: false };
    }
    if (!isRecord(value.delta) || Object.keys(value.delta).length === 0) {
      return { ok: false };
    }
    if (continuationDeltaHasAuthoritativeKey(value.delta)) {
      return { ok: false };
    }
    return {
      ok: true,
      continuation: { outcome: "delta", delta: value.delta as Record<string, unknown> },
    };
  }
  return { ok: false };
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

  if (value.kind === "semantic_decision") {
    if (
      typeof value.state !== "string" ||
      !SEMANTIC_STATES.has(value.state as SemanticDecisionState) ||
      typeof value.action !== "string" ||
      !value.action ||
      typeof value.unavailable !== "boolean"
    ) {
      return null;
    }
    const parsed = parseSemanticContinuation(value.continuation);
    if (!parsed.ok) return null;
    const event: SemanticDecisionEvent = {
      kind: "semantic_decision",
      request_id: value.request_id,
      state: value.state as SemanticDecisionState,
      action: value.action as SemanticDecisionAction,
      unavailable: value.unavailable,
      continuation: parsed.continuation,
    };
    return event;
  }

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
    // A conversation-scoped rejection (an expired attachment, for example) is
    // actionable by the caller: surface the structured code, never a raw body.
    const body: unknown = await response.json().catch(() => ({}));
    if (isRecord(body) && typeof body.code === "string" && body.code.startsWith("attachment.")) {
      const detail = typeof body.detail === "string" ? body.detail : undefined;
      throw new ApiError(response.status, detail ?? `HTTP ${response.status}`, detail, body.code);
    }
    throw new Error("Assistant activity request failed");
  }
  if (!response.body) throw new Error("Assistant activity stream is empty");
  options.onAccepted?.();

  const events: AssistantActivityEvent[] = [];
  let answer: string | null = null;
  let terminalStatus: AssistantActivityTerminalStatus | null = null;
  let semanticDecision: SemanticDecisionEvent | null = null;
  let answerSeen = false;
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
    if (event.kind === "semantic_decision") {
      // The additive event is authoritative and must precede any compatible
      // answer; a duplicate or out-of-order event fails the stream closed.
      if (semanticDecision !== null || answerSeen) return;
      semanticDecision = event;
    }
    if (event.kind === "answer") answerSeen = true;
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

  return { accepted: true, events, answer, terminalStatus, semanticDecision };
}
