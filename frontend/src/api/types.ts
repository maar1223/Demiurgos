/** Info about a single world returned by GET /api/worlds. */
export interface WorldInfo {
  name: string;
  path: string;
  lore_count: number;
  character_count: number;
  saga_count: number;
}

/** A file or directory node in the section tree. */
export interface FileNode {
  name: string;
  path: string;
  is_dir: boolean;
  children?: FileNode[];
  /**
   * OKF ficha status (draft|stable) parsed from the file's leading
   * frontmatter. Present ONLY when the backend knows a valid status —
   * unknown values (e.g. the idea-bank `synced`) and directories never
   * carry the field.
   */
  status?: FichaStatus;
  /**
   * Mundo-relative cover path (e.g. `wiki/media/x.jpg`).
   * Only present when the tree was requested with `?covers=true`;
   * `null` when the file has no resolvable cover (dirs are always null).
   */
  portada?: string | null;
}

/** Content and metadata of a single file. */
export interface FileContent {
  path: string;
  content: string;
  /** Legacy metadata is optional because the current file endpoint omits it. */
  name?: string;
  /** Current backend response field; legacy metadata remains for consumers. */
  size: number;
  size_bytes?: number;
  modified?: string; // ISO 8601
  extension?: string;
  /** SHA-256 digest of the exact bytes used as the edit base. */
  revision: string;
}

/** Generic success response for save/create/delete. */
export interface SuccessResponse {
  success: boolean;
  path: string;
}

/** Status returned by the explicit loopback-only local development session. */
export interface LocalDevSessionStatus {
  mode: string;
  enabled: boolean;
  authenticated: boolean;
  label: string | null;
}

// ---------------------------------------------------------------------------
// Global runtime configuration (GET /api/config)
// ---------------------------------------------------------------------------

/** Normalized UI language code from the backend (DEMIURGOS_LANGUAGE). */
export type AppLanguage = "es" | "en";

/** Non-sensitive global runtime metadata exposed by GET /api/config. */
export interface AppConfig {
  /** Normalized UI copy language: "es" or "en". */
  language: AppLanguage;
}

// ---------------------------------------------------------------------------
// Onboarding / Configuration Center (Slice 1 — Foundation)
// ---------------------------------------------------------------------------

export type OnboardingStep =
  | "step0"
  | "ai"
  | "telegram"
  | "world"
  | "backup_handoff"
  | "ready";

/** First-run gate state from GET /api/onboarding/status. */
export interface OnboardingStatus {
  completed: boolean;
  current_step: OnboardingStep;
  completed_steps: OnboardingStep[];
  pending_steps: OnboardingStep[];
  remote_pending: OnboardingStep[];
  blocking_pending: OnboardingStep[];
}

/** G7/OC3 locale: independent UI/conversation/content languages + region + IANA zone. */
export interface LocaleSettings {
  ui: string;
  conversation: string;
  content: string;
  region: string | null;
  region_explicit: boolean;
  iana_timezone: string;
}

/** Input for POST /api/onboarding/step0. */
export interface LocaleInput {
  ui: string;
  conversation: string;
  content: string;
  region?: string | null;
  region_explicit?: boolean;
  iana_timezone: string;
}

export type WorldCreateKind =
  | "created"
  | "already_exists"
  | "invalid_name"
  | "collision"
  | "io_error";

/** Result of POST /api/worlds. */
export interface WorldCreateResult {
  kind: WorldCreateKind;
  name: string;
  path: string | null;
  message: string;
}

/** Configuration Center card states (OC12). */
export type CardState =
  | "pending"
  | "configured"
  | "requires_connection"
  | "error";

/** Essential local readiness + per-card states (OC11/OC21). */
export interface ReadinessSnapshot {
  local_editor: { probe: string; ok: boolean; detail: string };
  cards: Record<string, CardState>;
}

// ---------------------------------------------------------------------------
// Idea capture configuration (Profile → Integraciones → Captura de ideas)
// ---------------------------------------------------------------------------

/** Media/retention limits persisted in config/idea-capture.yaml. */
export interface IdeaCaptureLimits {
  image_mb: number;
  audio_mb: number;
  audio_minutes: number;
  raw_retention_days: number;
}

/** Single-user idea-capture configuration (config/idea-capture.yaml). */
export interface IdeaCaptureConfig {
  /** Owner private chat ids. Empty list = fail closed (reject everything). */
  private_chat_ids: number[];
  /** Group chat id → approved sender ids. Empty mapping = fail closed. */
  approved_groups: Record<string, number[]>;
  /** World used by the serve command; empty when not chosen yet. */
  active_world: string;
  limits: IdeaCaptureLimits;
}

/** Exact serve command for the current local runtime + readiness gates. */
export interface IdeaCaptureServeStatus {
  command: string;
  runnable: boolean;
  blocked_reasons: string[];
}

/** Full panel status from GET /api/idea-capture/status. */
export interface IdeaCaptureStatus {
  config: IdeaCaptureConfig;
  /** Whether TELEGRAM_BOT_TOKEN is configured — the token itself is never
   *  returned by the API (server-side .env storage). */
  has_token: boolean;
  validation: { ok: boolean; errors: string[] };
  serve: IdeaCaptureServeStatus;
  worlds: string[];
  limitations: string[];
}

/** Result of setting/clearing the bot token — never contains the token. */
export interface TokenStatus {
  has_token: boolean;
}

/** Telegram card status (ONB-3.3) from GET /api/telegram/status. The token
 *  value is never present — only its write-only presence boolean. */
export interface TelegramStatus {
  state: CardState;
  has_token: boolean;
  tested_at: string | null;
  error_code: string;
}

/** Result of POST /api/telegram/test-connection — same shape plus a friendly
 *  server message; never carries the token value. */
export interface TelegramTestResult extends TelegramStatus {
  message?: string;
}

/** A discoverable Telegram chat candidate. The numeric id is an INTERNAL
 *  selection value — the UI shows the human-readable title/type and never
 *  asks the user to type or copy the id. */
export interface ChatCandidate {
  id: number;
  /** Telegram chat type: private | group | supergroup. */
  type: string;
  /** UI category: private chats are directly authorizable; groups need an
   *  explicit sender list + confirmation (fail-closed). */
  kind: "private" | "group";
  title: string;
}

/** Result of POST /api/idea-capture/chats/discover. Never carries message
 *  content; ids are internal selection values only. */
export interface ChatDiscoveryResult {
  ok: boolean;
  candidates: ChatCandidate[];
  /** Friendly guidance shown when there are no candidates yet. */
  message: string;
}

/** Full panel status after authorizing a discovered chat, plus the friendly
 *  confirmation message. */
export interface IdeaCaptureAuthorizeResult extends IdeaCaptureStatus {
  message: string;
}

/** Server-owned model option for the Wiki assistant. */
export interface AssistantModelOption {
  id: string;
  label: string;
  capability: "multimodal" | "text-only" | "unknown";
  pricing: { input?: number; output?: number } | null;
}

/** Presence/configuration metadata for the active Hermes assistant profile. */
export interface AssistantSettingsStatus {
  provider: string;
  base_url: string;
  model: string;
  model_metadata: AssistantModelOption;
  key_configured: boolean;
  models: AssistantModelOption[];
  active_profile: string;
  revision: number;
  runtime_state: "active" | "pending-reload" | "saved-not-active";
}

export interface AssistantConnectionInput {
  provider: string;
  base_url?: string;
  /** Write-only; never store this value in React state or response types. */
  api_key: string;
}

export interface AssistantValidationResult {
  outcome: "validated" | "failed";
  category: string;
  provider: string;
  message?: string;
}

export interface AssistantDiscoveryResult extends Omit<AssistantValidationResult, "outcome"> {
  outcome: "discovered" | "failed";
  models: AssistantModelOption[];
  loaded_models?: string[];
  jit_load_allowed?: boolean;
}

export interface AssistantProbeResult {
  outcome: "passed" | "malformed" | "timeout" | "provider_failure" | "not_causal";
  oracle: string;
  message?: string;
}

export interface AssistantProbeInput extends AssistantConnectionInput {
  model?: AssistantModelOption;
  manual_model_id?: string;
}

export interface SaveAssistantConfigurationInput extends AssistantConnectionInput {
  model?: AssistantModelOption;
  manual_model_id?: string;
  revision?: number;
}

// ---------------------------------------------------------------------------
// Assistant activity evidence
// ---------------------------------------------------------------------------

export type AssistantActivityItemStatus = "running" | "succeeded" | "failed";
export type AssistantActivityTerminalStatus = "succeeded" | "failed" | "unknown";

export interface AssistantActivityItem {
  item_id: string;
  operation: "Search world" | "Read world";
  status: AssistantActivityItemStatus;
  path?: string;
  warning?: string;
}

export type AssistantActivityEvent =
  | ({ kind: "activity"; request_id: string } & AssistantActivityItem)
  | { kind: "answer"; request_id: string; response: string }
  | SemanticDecisionEvent
  | {
      kind: "terminal";
      request_id: string;
      status: AssistantActivityTerminalStatus;
      warning?: string;
    };

export interface AssistantActivityEvidence {
  sources: string[];
  warnings: string[];
  status: "confirmed" | "incomplete" | "neutral";
}

// ---------------------------------------------------------------------------
// Guided character creation
// ---------------------------------------------------------------------------

export type GuidedCharacterPhase = "confirmation" | "conversation" | "review" | "complete";
export type GuidedCharacterMode = "full" | "fast";
export type GuidedCharacterDepth = "standard" | "fundamental";
export type GuidedCharacterIndexStatus = "indexed" | "pending" | "failed" | "dirty";

export interface GuidedCharacterMessage {
  role: "author" | "assistant";
  content: string;
}

/** Public candidate data. Provider provenance is intentionally not typed here. */
export interface GuidedCharacterCandidate {
  accepted_canon: Record<string, unknown>;
  proposals: Record<string, unknown>;
  unresolved_references: unknown[];
  conflicts: unknown[];
}

export interface GuidedCharacterProposal {
  key: string;
  label: string;
  value: string;
  rationale?: string;
}

export interface GuidedCharacterSession {
  protocol_version: string;
  session_id: string;
  world: string;
  phase: GuidedCharacterPhase;
  mode: GuidedCharacterMode;
  depth: GuidedCharacterDepth;
  revision: number;
  pending_question: string | null;
  messages: GuidedCharacterMessage[];
  candidate: GuidedCharacterCandidate;
  proposal: GuidedCharacterProposal | null;
  index_status?: GuidedCharacterIndexStatus;
  retryable?: boolean;
  message?: string;
  reference?: {
    name: string | null;
    verified: boolean;
    context: string;
    source: string | null;
    goal?: string | null;
  };
}

/** OKF ficha status — UI maps Borrador → draft, Canon → stable. */
export type FichaStatus = "draft" | "stable";

/** Response from POST /api/{mundo}/move — same shape as SuccessResponse. */
export interface MoveResponse {
  success: boolean;
  path: string;
}

/** Response from POST /api/{mundo}/duplicate — same shape as SuccessResponse. */
export interface DuplicateResponse {
  success: boolean;
  path: string;
}

/** A single line in a diff preview. */
export interface DiffLine {
  type: "same" | "added" | "removed";
  text: string;
}

/** Preview of a diff between current and proposed content. */
export interface DiffPreview {
  original_path: string;
  original_content: string;
  new_content: string;
  diff: DiffLine[];
}

// ---------------------------------------------------------------------------
// Secure editing
// ---------------------------------------------------------------------------

export type EditKind = "edit" | "new" | "restore";

/** Validated, diskless proposal returned by the Hermes edit endpoint. */
export interface EditProposal {
  proposal_id: string;
  target: string;
  base_revision: string;
  proposed_content: string;
  proposed_digest: string;
  rationale: string;
  is_new_file: boolean;
  guided_session_id?: string;
  guided_revision?: number;
}

// ---------------------------------------------------------------------------
// Semantic intent decisions
// ---------------------------------------------------------------------------

/**
 * Server-validated semantic decision states emitted by the semantic seam.
 * The server is the authority: the client maps exactly these states and never
 * invents or infers others.
 */
export type SemanticDecisionState =
  | "allow"
  | "clarify"
  | "require_confirmation"
  | "proposal_ready"
  | "blocked";

/** Server-derived action for a semantic decision envelope. */
export type SemanticDecisionAction =
  | "answer"
  | "ask_question"
  | "request_confirmation"
  | "show_proposal"
  | "blocked_explanation";

/**
 * Typed single-run continuation carried by the additive `semantic_decision`
 * SSE event. Mirrors the server-validated `SemanticContinuation`: `question`
 * backs `require_confirmation`, `delta` backs `proposal_ready`. Proposed data
 * only — the server re-derives targets, digests, and revisions.
 */
export type SemanticDecisionContinuation =
  | { outcome: "question"; question: string }
  | { outcome: "delta"; delta: Record<string, unknown> };

/**
 * The additive authoritative SSE event emitted by
 * `/api/{mundo}/ai/ask/activity` BEFORE any compatible `answer`/`terminal`
 * event. `state`, `action`, and `unavailable` are server-derived; consumers
 * MUST use this event for permission/state decisions and never infer them
 * from answer text. Legacy clients may ignore the additive event.
 */
export interface SemanticDecisionEvent {
  kind: "semantic_decision";
  request_id: string;
  state: SemanticDecisionState;
  action: SemanticDecisionAction;
  unavailable: boolean;
  continuation: SemanticDecisionContinuation | null;
}

/**
 * Decision envelope emitted by POST /api/{mundo}/ai/ask when the semantic
 * seam is active. The self-contained envelope (`allow`/`clarify`/`blocked`)
 * carries `state`, `response`, `action`, `request_id`, `attempts`, and
 * `unavailable`; the guided continuation envelopes
 * (`require_confirmation`/`proposal_ready`) add `fallback`, `guided`,
 * `session_id`, `guided_session_id`, `guided_revision`, `guided_state`, and
 * (for `proposal_ready`) the server-owned proposal fields.
 */
export interface SemanticDecisionEnvelope {
  state: SemanticDecisionState;
  response: string;
  action: SemanticDecisionAction;
  request_id: string;
  attempts: number;
  /** Present on the self-contained envelope; absent on guided continuations. */
  unavailable?: boolean;
  /** Present only on guided continuation envelopes; never a fallback path. */
  fallback?: boolean;
  guided?: boolean;
  session_id?: string;
  reference?: string;
  guided_session_id?: string;
  guided_revision?: number;
  guided_state?: GuidedCharacterSession;
  proposal_id?: string;
  target?: string;
  base_revision?: string;
  proposed_content?: string;
  proposed_digest?: string;
  rationale?: string;
  is_new_file?: boolean;
}

/**
 * Everything POST /api/{mundo}/ai/ask may return: a legacy chat answer, a
 * guided handoff envelope, or a semantic decision envelope.
 */
export type AiAskResponse =
  | { response: string; guided_state?: GuidedCharacterSession }
  | SemanticDecisionEnvelope;

/** Request body for POST /api/{mundo}/ai/edit-suggest. */
export interface EditSuggestionRequest {
  section: string;
  path: string;
  prompt: string;
  session_id?: string;
}

/** Response envelope for the bounded Hermes proposal flow. */
export interface EditSuggestionResponse {
  proposal: EditProposal | null;
  attempts: number;
  outcome: "proposal" | "fallback";
  fallback_action?: string;
  message?: string;
}

/** Request body for issuing a server-verifiable confirmation token. */
export interface EditConfirmationRequest {
  edit_id: string;
  base_revision?: string;
  proposed_content?: string;
  kind: EditKind;
  snapshot_id?: string;
}

/** Single-use proof returned by the confirmation endpoint. */
export interface EditConfirmation {
  token: string;
  expires_at: string;
  proposed_digest: string;
}

/** Proof fields required by the gated save/create endpoints. */
export interface ConfirmedEditRequest {
  content: string;
  base_revision?: string;
  proposed_digest: string;
  edit_id: string;
  token: string;
}

/** A retained snapshot returned by the history endpoint. */
export interface HistoryEntry {
  id: string;
  snapshot_id: string;
  target: string;
  created_at: string; // ISO 8601
  content: string;
  revision: string;
  size: number;
}

/** Response from GET /api/{mundo}/history?path=. */
export interface HistoryListResponse {
  target: string;
  entries: HistoryEntry[];
}

/** Request body for the confirmation-gated history restore endpoint. */
export interface RestoreFileRequest extends ConfirmedEditRequest {
  path: string;
  snapshot_id: string;
}

// ---------------------------------------------------------------------------
// Graph
// ---------------------------------------------------------------------------

/** Result item from graph entity search. */
export interface SearchResult {
  name: string;
  type: string;
  path: string;
  title: string;
  description: string;
  tags: string[];
  link_count: number;
  score: number;
}

/** Full entity detail from the knowledge graph. */
export interface GraphEntity {
  name: string;
  type: string;
  path: string;
  content: string;
  forward_links: string[];
  backlinks: string[];
  relaciones: Record<string, unknown>[];
}

/** A directed connection between two entities in the graph. */
export interface EntityLink {
  source: string;
  target: string;
  kind: string;
}

/** Graph indexing and health status. */
export interface GraphStatus {
  node_count: number;
  link_count: number;
  indexed: boolean;
}

// ---------------------------------------------------------------------------
// Media / Images
// ---------------------------------------------------------------------------

/** Info about a single image file in a world. */
export interface ImageInfo {
  path: string;
  name: string;
  size_bytes: number;
  extension: string;
  thumbnail_path?: string;
}

/** Response from GET /api/{mundo}/media/list — all images in a world. */
export interface MediaList {
  images: ImageInfo[];
  total: number;
}

/** Response from POST /api/{mundo}/media/upload. */
export interface UploadResponse {
  success: boolean;
  path: string;
  size_bytes: number;
  thumbnail_path?: string;
}

// ---------------------------------------------------------------------------
// Papelera (Trash)
// ---------------------------------------------------------------------------

/** A single entry in a world's trash (papelera). */
export interface TrashEntry {
  entry_id: string;
  section: string;
  original_path: string;
  kind: "file" | "dir";
  deleted_at: string; // ISO 8601
  size: number; // bytes
}

/**
 * Response from GET /api/{mundo}/papelera — the trash list plus the count of
 * expired entries the lazy 30-day TTL purge removed on this call.
 */
export interface TrashListResponse {
  entries: TrashEntry[];
  /**
   * Expired entries auto-purged by the 30-day TTL. OPTIONAL in the response:
   * the backend omits it when zero entries were purged (preserves the
   * byte-identical `{"entries": []}` empty contract) — consumers must
   * normalize with `?? 0`.
   */
  purged?: number;
}

/** Response from DELETE /api/{mundo}/papelera — emptying the whole trash. */
export interface EmptyTrashResponse {
  purged: "all";
  entries: number;
}

// ---------------------------------------------------------------------------
// Methodology library (Taller de Herramientas)
// ---------------------------------------------------------------------------

/** A published, immutable methodology version. */
export interface PublishedMethodology {
  skill_id: string;
  version: string;
  name: string;
  description: string;
  digest: string;
  published_at: string;
}

/** The compiled methodology/version pinned to one world. */
export interface MethodologyActivation {
  world: string;
  skill_id: string;
  version: string;
  digest: string;
  activated_at: string;
}

/** A editable methodology draft. */
export interface MethodologyDraft {
  draft_id: string;
  skill_id: string;
  version: string;
  name: string;
  source: string;
  description: string;
  updated_at: string;
}

/** Library status from GET /api/methodologies/status. */
export interface MethodologyStatus {
  published: PublishedMethodology[];
  activations: Record<string, MethodologyActivation>;
  drafts: MethodologyDraft[];
}

/** Input for creating a methodology draft. */
export interface MethodologyDraftInput {
  skill_id: string;
  version: string;
  name: string;
  source: string;
  description?: string;
}

/** Structured API error. `code` (when present) is a stable machine-readable
 *  remediation key from the backend (e.g. `webhook_conflict` for the
 *  Telegram webhook/getUpdates conflict) so the UI can render specific
 *  guidance instead of a bare message. */
export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public detail?: string,
    public code?: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}
