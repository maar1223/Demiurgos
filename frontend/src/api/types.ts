/** Info about a single world returned by GET /api/worlds. */
export interface WorldInfo {
  name: string;
  path: string;
  lore_count: number;
  character_count: number;
  reference_count: number;
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

/** Auth mode reported by the backend (DEMIURGOS_AUTH_MODE). */
export type AuthMode = "disabled" | "local-dev" | "credentials";

/** Active session provider reported by the unified status endpoint. */
export type AuthProvider = "local-dev" | "credentials";

/**
 * Unified mode-aware session status (GET /api/auth/session/status). Works for
 * every auth mode: `provider` is present only when a session is active.
 * Credentials sessions additionally expose the soft re-auth countdown
 * (R-AC-04): `last_auth_at` (ISO 8601) and `days_until_reauth` (clamped at 0).
 */
export interface AuthSessionStatus {
  mode: AuthMode;
  enabled: boolean;
  authenticated: boolean;
  label: string | null;
  provider?: AuthProvider;
  /** ISO 8601 timestamp of the last password entry — credentials sessions only. */
  last_auth_at?: string;
  /** Days left before the soft re-auth reminder (0 once the interval elapsed). */
  days_until_reauth?: number;
}

/** The single local account (credentials mode). `has_password` is false for
 *  passwordless accounts (password_hash = null server-side). */
export interface AccountInfo {
  username: string;
  has_password: boolean;
}

/** Response of POST /api/auth/credentials/account — the recovery words are
 *  returned in plaintext exactly once; the server persists only their hash. */
export interface AccountCreateResult {
  username: string;
  words: string;
}

/** Response of POST /api/auth/credentials/recover — short-lived single-use
 *  token proving recovery-words ownership. */
export interface RecoveryTokenResponse {
  recovery_token: string;
}

/** Success envelope of every credential-management write
 *  (recover/complete, password, password/remove, username). */
export interface CredentialChangeResult {
  success: boolean;
}

/**
 * Response of POST /api/auth/emergency/rotate — the new plaintext recovery
 * key, shown to the user exactly once (the server persists only its hash).
 */
export interface EmergencyKeyRotationResponse {
  new_key: string;
}

/**
 * Response from POST /api/system/{action} (restart/shutdown). `accepted: true`
 * means the launcher was dispatched and the stack is going down; a 500 carries
 * the launcher's stderr excerpt in `error`.
 */
export interface SystemControlResponse {
  action: "restart" | "shutdown";
  accepted: boolean;
  error?: string;
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
  | "account"
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

/**
 * A single entry in the world-level recycle bin (data/world-trash/), returned
 * by DELETE /api/worlds/{name} and GET /api/worlds/trash.
 */
export interface WorldTrashEntry {
  world_name: string;
  deleted_at: string; // ISO 8601
  size_bytes: number;
  lore_count: number;
  character_count: number;
  /** Days left before the 30-day purge permanently deletes the entry. */
  days_remaining: number;
}

/** Configuration Center card states (OC12). */
export type CardState =
  | "pending"
  | "configured"
  | "requires_connection"
  | "error";

/** Honest offline/dispositivo breakdown (OC5/ONB-3.4): the local core works
 *  without connection while remote capabilities stay pending. */
export interface OfflineBreakdown {
  local_ready: boolean;
  remote_pending: string[];
}

/** Read-only legacy-layout finding (ONB-4.2): a world whose top level uses
 *  uppercase `Lore`/`Personajes` folders instead of the canonical lowercase
 *  tree. Detection never mutates; migration is a separate, explicitly
 *  approved step (ONB-4.3) and never automatic. */
export interface LegacyFinding {
  world: string;
  folders: string[];
}

/** Honest migration outcome (ONB-4.3): the approved folders moved to the
 *  canonical lowercase tree, or were restored after a mid-transaction
 *  failure. Never any other value — the server is the authority. */
export type MigrationOutcomeStatus = "completed" | "rolled_back";

/** One approved folder inside a migration transaction. The source/destination
 *  are ABSOLUTE filesystem paths and the hashes are sha256 digests: the UI
 *  renders only `folder` and never exposes the rest (no path/hash leak). */
export interface MigrationStep {
  folder: string;
  source: string;
  destination: string;
  source_hash: string;
  destination_hash: string;
  restored: boolean;
}

/** Response of POST /api/migration/execute — mirrors the persisted evidence
 *  record (transaction id, restore flag, timestamps, per-folder steps). */
export interface MigrationExecuteResult {
  status: MigrationOutcomeStatus;
  transaction_id: string;
  world: string;
  restore_verified: boolean;
  started_at: string;
  finished_at: string;
  error: string | null;
  steps: MigrationStep[];
}

/** Essential local readiness + per-card states (OC11/OC21). */
export interface ReadinessSnapshot {
  local_editor: { probe: string; ok: boolean; detail: string };
  cards: Record<string, CardState>;
  offline: OfflineBreakdown;
  /** Worlds using the legacy uppercase layout (read-only detection). */
  legacy: LegacyFinding[];
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
  /** Legacy world selector, read backward-compatibly when present. Capture
   *  always goes to the global Taller de Ideas, so this is never required. */
  active_world?: string;
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
// World Importer (world-importer slice 3 — typed lifecycle)
// ---------------------------------------------------------------------------

/** Server-owned import job states (mirror of import_models.ImportJobState). */
export type ImportJobState =
  | "pending"
  | "intaking"
  | "analyzing"
  | "review"
  | "failed"
  | "cancelled"
  | "approved"
  | "executing"
  | "completed"
  | "rolled_back";

/** Source kinds accepted by the server-owned spool. */
export type ImportSourceKind = "folder" | "loose" | "zip";

/** Source proximity contract — every candidate keeps its traceable origin. */
export interface ImportProvenance {
  source_path: string;
  source_kind: ImportSourceKind;
  source_hash: string;
  heading_path: string;
  source_sequence: number;
  chunk_id: string | null;
  nearby_text_anchor: string;
  image_anchor: string;
  source_order: number;
}

/** Contextual image placement — `ambiguous` always requires review. */
export type ImagePlacementStatus =
  | "proposed"
  | "approved"
  | "ambiguous"
  | "inserted"
  | "skip";

export interface ImportImagePlacement {
  gallery_asset_id: string;
  relative_media_path: string;
  alt_text: string;
  target_ficha: string;
  confidence: number;
  placement_status: ImagePlacementStatus;
  /**
   * DOCX position contract (additive — present for converted DOCX sources,
   * absent for markdown/source-order placements). Server-provided and
   * excluded from identity/digest inputs.
   */
  document_order?: number;   // 1-based global order of extracted images
  paragraph_index?: number;  // 0-based index of the containing paragraph
  anchor_type?: string;      // "inline" | "anchor" | "" ("" when unknown)
  structural_path?: string;  // e.g. body/p[3]/r[1]/inline[0]
  heading_path?: string;     // heading hierarchy at extraction time
  context_text?: string;     // paragraph/heading text around the image
  warnings?: string[];       // per-image actionable notes
}

/** Preservation-first merge decision (server-owned). */
export interface ImportMergeDecision {
  target: string;
  base_revision: string;
  mode: "add" | "replace";
  action: "add" | "keep" | "replace" | "skip" | "review";
  reason: string;
  approver: string;
  approval_digest: string;
  outcome: string;
}

/** Explicit-replacement snapshot record (30-day `.papelera` recovery). */
export interface ImportReplacementRecord {
  prior_snapshot: string;
  new_revision: string;
  papelera_entry: string;
  expiry: string;
  recovery_status: string;
}

/**
 * Hermes-suggested classification (advisory only — server is the authority).
 *
 * Suggestions are NON-AUTHORITATIVE: they ride on each candidate without
 * mutating deterministic identity/digest, are surfaced in review as advisory,
 * and only materialize into canon during a gated execute. ``review_state`` is
 * initially ``pending`` and toggled to ``approved``/``rejected`` via the
 * ``POST /{job_id}/review/decisions`` endpoint. ``provenance`` is server-
 * attached (provider, model, prompt version) so reviewers can attribute.
 */
export interface ClassificationSuggestion {
  id: string;
  candidate_id: string;
  type: string;
  tags: string[];
  confidence: number;
  evidence: string;
  provenance: Record<string, string>;
  review_state: "pending" | "approved" | "rejected";
}

/**
 * Hermes-suggested relationship between candidates (or to a named target).
 *
 * ``target_candidate_id`` is set when the target is another candidate in the
 * same batch; ``target_name`` is set when Hermes names an entity not present
 * in the batch (validation rejects ungrounded names). Self-links are rejected.
 */
export interface RelationshipSuggestion {
  id: string;
  source_candidate_id: string;
  target_candidate_id: string | null;
  target_name: string | null;
  relationship_type: string;
  confidence: number;
  evidence: string;
  provenance: Record<string, string>;
  review_state: "pending" | "approved" | "rejected";
}

/**
 * Vision verdict vocabulary (mirror of the PR2/PR3 server contract). The
 * verdict is ADVISORY: it never gates writes — only the reviewer's explicit
 * approval does.
 */
export type VisionVerdict = "confirma" | "rechaza" | "no_aplica" | "contradice";

/**
 * Vision analysis for one extracted image (sync-lore-in-importer, PR3+).
 *
 * Rides on the candidate's ``enrichment_json`` as a ``__type__: "vision"``
 * entry (the PR3 server shape). ``relative_media_path`` is the SPOOL-relative
 * path of the extracted original (``media/<stem>/<file>``) — it becomes the
 * gallery path only after an approved execute, so it is NOT servable from the
 * world media base during review; ``thumbnail_url`` is populated by the
 * server only when a preview is actually servable. ``review_state`` toggles
 * via the existing ``POST /{job_id}/review/decisions`` endpoint.
 */
export interface VisionSuggestion {
  id: string;
  candidate_id: string;
  /** Spool-relative media path of the extracted original (PR1 layout). */
  relative_media_path: string;
  /** Optional servable preview URL; absent when the spool path is not
   *  servable yet (review-time images are pre-gallery). */
  thumbnail_url?: string;
  /** Vision description — used as the markdown alt-text on approval. */
  description: string;
  verdict: VisionVerdict;
  analysis: string;
  tags: string[];
  confidence: number;
  provenance: Record<string, string>;
  evidence: string;
  review_state: "pending" | "approved" | "rejected";
}

/** Discriminated union for advisory suggestions on a candidate. */
export type ImportSuggestion =
  | (ClassificationSuggestion & { __type__: "classification" })
  | (RelationshipSuggestion & { __type__: "relationship" })
  | (VisionSuggestion & { __type__: "vision" });

/** Server-attributed diagnostic state of an enrichment attempt. */
export type EnrichmentStatus =
  | "disabled"
  | "ok"
  | "no_suggestions"
  | "error";

/**
 * Enrichment state of a candidate's frontmatter (design Step 4).
 *
 * Mirrors ``import_models.FrontmatterState``:
 * - ``generated`` — produced by Hermes enrichment.
 * - ``manual`` — author decision / no enrichment requested.
 * - ``fallback`` — fail-open (timeout, malformed, or unavailable Hermes).
 */
export type FrontmatterState = "generated" | "manual" | "fallback";

/**
 * Reviewable OKF frontmatter for one ficha (analysis output, not the body).
 *
 * ``relaciones`` carry canonical ids (``::``-qualified), never ambiguous leaf
 * names. ``state`` lets review attribute the metadata. The candidate body
 * stays the original source text — frontmatter never replaces it.
 */
export interface FrontmatterCandidate {
  title: string;
  type: string | null;
  description: string;
  relaciones: string[];
  state: FrontmatterState;
}

/**
 * Diagnostic for one reference-style image placement (``![..][key]``).
 *
 * The original span is preserved verbatim in ``reference`` so execution can
 * render it untouched. ``status`` is ``resolved`` when a matching
 * ``[key]: path`` definition exists in the same ficha, otherwise
 * ``unresolved`` — that placement is excluded from gallery registration but
 * never blocks the ficha or the job (review warning only).
 */
export interface MediaDiagnostic {
  reference: string;
  image_key: string;
  alt_text: string;
  status: "resolved" | "unresolved";
  target_path: string;
  target_ficha: string;
  message: string;
}

/** A diagnosed, eligible intake candidate (read-only until approved). */
export interface ImportCandidate {
  candidate_id: string;
  job_id: string;
  world: string;
  normalized_identity: string;
  /** Parent-qualified "::"-joined identity (analysis). */
  canonical_id: string;
  source_hash: string;
  provenance: ImportProvenance;
  content_preview: string;
  /**
   * Importador-auto-frontmatter — analyzed metadata for the ficha:
   * ``display_title`` (ficha title, covers the implicit single-ficha path),
   * the dense per-ficha ``summary`` (Step 2), the reviewable
   * ``frontmatter`` (Step 4) and the reference-image ``media_diagnostics``.
   * All advisory; ``content_preview`` stays the original body text.
   */
  display_title: string;
  summary: string;
  frontmatter: FrontmatterCandidate | null;
  media_diagnostics: MediaDiagnostic[];
  /** pending | eligible | conflict | rejected — server is the authority. */
  status: string;
  okf_issues: Array<Record<string, unknown>>;
  size_bytes: number;
  images: ImportImagePlacement[];
  merge: ImportMergeDecision | null;
  replacement: ImportReplacementRecord | null;
  /**
   * Slice 2 — advisory suggestions from the optional Hermes enricher.
   * ``null`` when enrichment was not requested or was disabled; the review
   * row is always populated, so downstream code MUST treat absence as
   * "no suggestions", not as an error.
   */
  enrichment_json: ImportSuggestion[] | null;
  /** Server-attributed diagnostic state of the enrichment attempt. */
  enrichment_status: EnrichmentStatus;
}

/** Public job view — never carries the opaque observability token. */
export interface ImportJob {
  job_id: string;
  world: string;
  owner_principal: string;
  state: ImportJobState;
  source_kind: ImportSourceKind;
  aggregate_uncompressed_bytes: number;
  aggregate_compressed_bytes: number;
  file_count: number;
  revision: number;
  error: string;
  created_at: string;
  updated_at: string;
  /** Server-owned analysis progress (live Web App). ``pct`` is ``null`` when
   *  the current phase is indeterminate. Optional for legacy fixtures; the
   *  server always sends it after the progress contract landed. */
  progress_stage?: string;
  progress_pct?: number | null;
  /** Classifier (BLOQUE 1 piece 1): author-chosen section per relative
   *  source path, persisted server-side as ``sections_json``. Surfaced so a
   *  resumed job can re-populate the selection dropdowns. */
  sections?: Record<string, string>;
}

/** Response of POST /api/{mundo}/imports and GET /api/{mundo}/imports/{id}. */
export interface ImportJobResponse {
  job: ImportJob;
}

/**
 * Cursor-paginated slice of the caller's import-job history
 * (GET /api/{mundo}/imports, world-importer slice 2). ``next_cursor`` is an
 * opaque server token — clients must echo it back unchanged for the next
 * page, never parse or reconstruct it.
 */
export interface JobPage {
  jobs: ImportJob[];
  next_cursor: string | null;
}

/** Request body for POST /api/{mundo}/imports/{id}/analyze. */
export interface AnalyzeImportRequest {
  /** Slice 2 — opt into Hermes advisory enrichment after deterministic analysis. */
  enrich?: boolean;
  /**
   * Vision opt-out — when ``false`` the per-image analysis is skipped and the
   * import is text-only (cheaper, no vision model). Defaults to ``true``.
   */
  vision?: boolean;
}

/** Response of POST /api/{mundo}/imports/{id}/analyze. */
export interface ImportAnalyzeResponse {
  job: ImportJob;
  candidates: number;
  /** Slice 2 — server-attributed diagnostic state of the enrichment attempt. */
  enrichment_status?: EnrichmentStatus;
}

/** Response of GET /api/{mundo}/imports/{id}/review — candidates + digest. */
export interface ImportReviewResponse {
  job: ImportJob;
  digest: string;
  candidates: ImportCandidate[];
  /** Slice 2 — batch-level diagnostic state rolled up from per-candidate. */
  enrichment_status: EnrichmentStatus;
  /**
   * Slice 2 — per-candidate advisory suggestions keyed by ``candidate_id``.
   * An empty array means no suggestions were produced or were all filtered
   * during validation; the deterministic digest is unchanged either way.
   */
  suggestions: Record<string, ImportSuggestion[]>;
}

/** A reviewer decision for one suggestion (slice 2). */
export interface ImportReviewDecision {
  suggestion_id: string;
  decision: "approve" | "reject";
}

/** Request body for POST /api/{mundo}/imports/{id}/review/decisions. */
export interface ImportDecisionsRequest {
  decisions: ImportReviewDecision[];
}

/** Response of POST /api/{mundo}/imports/{id}/review/decisions. */
export interface ImportDecisionsResponse {
  accepted: number;
}

/** Approval issued for a reviewed, unchanged digest (token is single-use). */
export interface ImportApprovalResponse {
  approval_id: string;
  token: string;
  digest: string;
  expires_at: string;
}

/** Outcome of one executed candidate (merge/placement/write). */
export interface ImportExecutionOutcome {
  candidate_id: string;
  target: string;
  action: "add" | "keep" | "replace" | "skip" | "review";
  placement_status: string;
  written: boolean;
  detail: string;
  papelera_entry: string;
}

/** Response of POST /api/{mundo}/imports/{id}/execute. */
export interface ImportExecuteResponse {
  job: ImportJob;
  outcomes: ImportExecutionOutcome[];
}

/** Request body for POST /api/{mundo}/imports. */
export interface ImportCreateJobInput {
  source_kind: ImportSourceKind;
  files: string[];
  /** Classifier (BLOQUE 1 piece 1): author-chosen section per relative
   *  source path (`lore` | `personajes` | `referencias`). Optional — legacy
   *  clients omit it and the server defaults to `{}` (all candidates fall
   *  through to the legacy resolve_target branch). */
  sections?: Record<string, string>;
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
  /** Canonical importer identity (frontmatter ``id``); empty for legacy files. */
  id: string;
  name: string;
  type: string;
  path: string;
  /** OKF ficha status (draft|stable); null when the source omits it. */
  status: FichaStatus | null;
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
