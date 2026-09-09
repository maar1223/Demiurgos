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
  /** True when the local account has a password (credentials mode only).
   *  False for passwordless accounts — the login UI then renders the
   *  "Enter" button without a password field (S-AC-02b). */
  has_password?: boolean;
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

/**
 * State of the local vault (GET /api/auth/vault/config). `enabled` mirrors
 * `_vault_active()`: the persisted `capabilities.vault.enabled` flag (PRIMARY)
 * OR the `DEMIURGOS_AUTH_MODE=credentials` operator override. The endpoint is
 * NOT auth-gated — read-only status, never secrets.
 */
export interface VaultConfig {
  enabled: boolean;
  account_exists: boolean;
  username: string | null;
  has_password: boolean;
  reauth_interval_d: number;
  env_override: boolean;
}

/** Result of POST /api/auth/vault/enable. When activation created a new
 *  account, `words` carries the recovery words in plaintext EXACTLY once. */
export interface VaultEnableResult {
  enabled: boolean;
  words?: string;
}

/** Result of POST /api/auth/vault/disable — removes auth entirely. */
export interface VaultDisableResult {
  enabled: boolean;
}

/** Result of POST /api/auth/vault/reauth-interval — the effective interval
 *  (may differ from the request when an env override is set). */
export interface ReauthIntervalResult {
  reauth_interval_d: number;
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
  /** True when source and destination were the SAME physical directory
   *  (case-insensitive filesystems: macOS APFS, Windows NTFS), so nothing
   *  moved — the folder was already canonical. The UI must not tell the user
   *  that files were moved in that case. */
  is_noop: boolean;
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

// ---------------------------------------------------------------------------
// Co-creation (Skill Madre — tool-workshop-skill-co-creation)
// ---------------------------------------------------------------------------

/** Server-owned milestone state (REQ-CC-3): the Skill Madre reports exactly
 *  one `actual` milestone per session; the rest are `completado` or
 *  `pendiente`. The client maps exactly these states and never infers them. */
export type CoCreationMilestoneState = "completado" | "actual" | "pendiente";

/** Session lifecycle phase — the backend is the authority. */
export type CoCreationPhase =
  | "conversation"
  | "materialized"
  | "review"
  | "complete";

/** One of the six milestone steps (Propósito → Revisión y publicación). */
export interface CoCreationMilestone {
  name: string;
  state: CoCreationMilestoneState;
}

/** A chat message in the co-creation transcript. */
export interface CoCreationMessage {
  role: "author" | "assistant";
  content: string;
}

/** One compiler finding surfaced by draft materialization (REQ-CC-5). The
 *  validation panel renders code + message (+ field when present). */
export interface CompileIssue {
  code: string;
  message: string;
  field: string | null;
}

/** Public principal-bound co-creation session (GET /api/co-creation/sessions/{id}).
 *  Provider provenance and authority keys are NEVER typed here (REQ-CC-7). */
export interface CoCreationSession {
  protocol_version: string;
  session_id: string;
  principal_id: string;
  world: string | null;
  revision: number;
  milestone: string;
  progress: CoCreationMilestone[];
  question_count: number;
  pending_question: string | null;
  pending_options: string[];
  messages: CoCreationMessage[];
  phase: CoCreationPhase;
  draft_id: string | null;
  compile_issues: CompileIssue[] | null;
  /** TW12 editable structured draft payload (null until the session has one).
   *  The canvas renders it and sends Author-originated edits back through the
   *  revision-guarded merge (REQ-CC-11). */
  draft_payload: DraftPayload | null;
  /** TW12 3-state validation warnings (REQ-CC-13). Pending warnings NEVER
   *  auto-clear; only the Author transitions out of `pendiente`. */
  warnings: DraftWarning[];
  /** TW12 immutable autosave snapshot count (REQ-CC-15). */
  history_count: number;
  /** TW14 server-injected provenance; null for non-derived sessions. The
   *  client NEVER sends this — the server reads it from the PUBLISHED record. */
  derived_from: DerivedFrom | null;
}

/** Milestone progress projection (GET .../sessions/{id}/progress). */
export interface CoCreationProgress {
  session_id: string;
  world: string | null;
  milestone: string;
  progress: CoCreationMilestone[];
  phase: CoCreationPhase;
  question_count: number;
  draft_id: string | null;
}

/** Author-confirmed metadata folded into the draft at materialization
 *  (all fields optional — the backend falls back to session payload values). */
export interface CoCreationMaterializeMetadata {
  skill_id?: string;
  version?: string;
  name?: string;
  description?: string;
  taller?: string;
  categoria_funcional?: string;
  etiquetas?: string[];
  language?: string;
}

/** Result of POST .../sessions/{id}/materialize. On success the full session
 *  public state is returned with `ok: true` and empty issues; on compile
 *  failure only the issue summary is returned and the session STAYS at
 *  `borrador_listo` so the Author can correct before retrying (REQ-CC-5). */
export interface CoCreationMaterializeResult {
  session_id?: string;
  draft_id: string | null;
  ok: boolean;
  issues: CompileIssue[];
  compile_issues: CompileIssue[] | null;
  phase: CoCreationPhase;
  milestone: string;
  revision: number;
}

/** Result of POST .../sessions/{id}/publish — the POST itself IS the Author's
 *  explicit approval signal (REQ-CC-6); publishing is immutable. */
export interface CoCreationPublishResult {
  session_id: string;
  phase: CoCreationPhase;
  revision: number;
  published: {
    skill_id: string;
    version: string;
    name: string;
    description: string;
    digest: string;
    published_at: string;
  };
}

/** Result of POST .../sessions/{id}/activate — pins one version per world
 *  (a new activation deactivates the previous). */
export interface CoCreationActivateResult {
  session_id: string;
  phase: CoCreationPhase;
  revision: number;
  activation: {
    world: string;
    skill_id: string;
    version: string;
    digest: string;
    activated_at: string;
  };
}

// ---------------------------------------------------------------------------
// TW12/TW13/TW14 — canvas payload, warnings, history, provenance
// ---------------------------------------------------------------------------

/** Three-state draft-review warning lifecycle (REQ-CC-13). Pending warnings
 *  NEVER auto-correct; only the Author transitions out of `pendiente`
 *  (`resuelta` or `aceptada_por_autor`). */
export type WarningState = "pendiente" | "resuelta" | "aceptada_por_autor";

/** A chat-appended pending question with its Author-owned state (REQ-CC-14):
 *  the canvas renders entries read-only; the Author may only transition
 *  `Pendiente -> Resuelta | Aceptada_por_Autor`. Legacy wire entries may be
 *  plain strings (normalized to `{text, state: "pendiente"}` at render). */
export interface PendingQuestion {
  text: string;
  state: WarningState;
}

/** One validation-panel warning with a 3-state lifecycle (REQ-CC-13). */
export interface DraftWarning {
  code: string;
  message: string;
  field: string | null;
  state: WarningState;
}

/** One immutable autosave snapshot (REQ-CC-15). Payloads are excluded from
 *  the list view; the restore route returns the chosen snapshot's payload. */
export interface DraftHistoryEntry {
  revision: number;
  source: "author" | "chat" | "autosave";
  ts: string; // ISO 8601
}

/** Server-injected parent identity for a derived draft (TW14). The client
 *  NEVER supplies this — the server reads it from the PUBLISHED record
 *  (REQ-CC-20); client-supplied provenance is ignored. */
export interface DerivedFrom {
  skill_id: string;
  version: string;
}

/** The typed, Author-editable structured draft sections exposed by the canvas
 *  (REQ-CC-11). `branches`/`rules`/`pending_questions` are lists; the rest are
 *  plain strings. `pending_questions` is chat-owned (REQ-CC-14): the canvas
 *  may display it but never authors it. */
export interface DraftPayload {
  name: string;
  description: string;
  purpose: string;
  scope: string;
  main_flow: string;
  branches: string[];
  rules: string[];
  pending_questions: PendingQuestion[];
  world: string | null;
}

/** TW13 per-section compare classification (REQ-CC-18). */
export type SectionClassification =
  | "conservado"
  | "modificado"
  | "añadido"
  | "eliminado";

/** PUT .../sessions/{id}/canvas — revision-guarded debounced autosave.
 *  The envelope keys (`base_revision`/`payload`) stay OUTSIDE the 8-key
 *  authority set (REQ-CC-23); the server merges and validates (render +
 *  compile, NO draft created) under the session's current revision. */
export interface CoCreationCanvasResult {
  revision: number;
  issues: CompileIssue[];
  warnings: DraftWarning[];
  ok: boolean;
}

/** POST .../sessions/{id}/validate — pure render+compile preview. Never
 *  creates, publishes, or mutates any session state (REQ-CC-13). */
export interface CoCreationValidationResult {
  issues: CompileIssue[];
  warnings: DraftWarning[];
  source_preview: string;
  ok: boolean;
}

/** GET .../sessions/{id}/history — immutable autosave snapshot list. */
export interface CoCreationHistoryList {
  entries: DraftHistoryEntry[];
}

/** POST .../sessions/{id}/history/restore — revision-guarded restore
 *  (REQ-CC-15); fails closed with REVISION_CONFLICT on a stale base. */
export interface CoCreationRestoreResult {
  revision: number;
  payload: DraftPayload;
}

/** POST .../sessions/{id}/warnings/{idx}/status — Author-only transition. */
export interface CoCreationWarningList {
  warnings: DraftWarning[];
}

/** POST .../sessions/{id}/pending-questions/{idx}/status — Author-only
 *  transition (REQ-CC-14). */
export interface CoCreationPendingQuestionList {
  pending_questions: PendingQuestion[];
}

/** POST /api/co-creation/derive — adaptation draft with server-injected
 *  provenance (TW13/TW14). The client sends ONLY the original identity. */
export interface CoCreationDeriveResult {
  session_id: string;
  draft_id: string;
  derived_from: DerivedFrom;
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
  /** Frontmatter `relaciones:` entries — canonical-id strings or objects.
   *  The backend ships the raw list, so both forms are valid on the wire. */
  relaciones: (string | Record<string, unknown>)[];
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

/**
 * Result of POST /api/{mundo}/graph/relation — a create/break write to the
 * source ficha's frontmatter `relaciones:` list, anchored by the target's
 * canonical id. `action` echoes the requested operation; `path` is the
 * normalized mundo-relative source ficha path.
 */
export interface RelationResponse {
  success: boolean;
  path: string;
  action: "create" | "break";
  target_id: string;
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
  /** Taller de Herramientas inventory metadata (Fase 1). */
  taller?: string | null;
  talleres_compatibles?: string[];
  categoria_funcional?: string | null;
  etiquetas?: string[];
  clasificacion?: string | null;
  trust_attributes?: string[];
  /** TW14 server-injected provenance: the parent published version this one
   *  was derived from (REQ-CC-21). Present only on derived publishes; list
   *  endpoints may omit them (the detail route always exposes them). */
  parent_skill_id?: string | null;
  parent_version?: string | null;
}

/** Full published version + source from
 *  GET /api/methodologies/published/{skill_id}/{version} (TW13 original render
 *  for adaptation; auth-required because it exposes the author `source`). */
export interface PublishedMethodologyDetail extends PublishedMethodology {
  phases: string[];
  language: string;
  source: string;
}

/** The compiled methodology/version pinned to one world. */
export interface MethodologyActivation {
  world: string;
  skill_id: string;
  version: string;
  digest: string;
  activated_at: string;
}

/** A published methodology version pinned as a per-world companion skill
 *  (several per world, independent of the single activation slot). */
export interface MethodologyCompanion {
  world: string;
  skill_id: string;
  version: string;
  description: string;
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
  /** Taller de Herramientas inventory metadata (Fase 1). */
  taller?: string | null;
  talleres_compatibles?: string[];
  categoria_funcional?: string | null;
  etiquetas?: string[];
  /** TW14 server-injected provenance (REQ-CC-20): parent published identity
   *  for derived drafts. The client never supplies these. */
  parent_skill_id?: string | null;
  parent_version?: string | null;
}

/** Library status from GET /api/methodologies/status. */
export interface MethodologyStatus {
  published: PublishedMethodology[];
  activations: Record<string, MethodologyActivation>;
  drafts: MethodologyDraft[];
  /** Additive companions map (world → entries) — only worlds with at least
   *  one companion appear; absent on pre-companion payloads (old servers
   *  keep parsing: optional, additive-only). */
  companions?: Record<string, MethodologyCompanion[]>;
}

/** One catalog entry from GET /api/methodologies/inventory (TW7). */
export interface MethodologyInventoryItem {
  skill_id: string;
  version: string;
  name: string;
  description: string;
  digest: string;
  published_at: string;
  taller?: string | null;
  talleres_compatibles?: string[];
  categoria_funcional?: string | null;
  etiquetas?: string[];
  clasificacion?: string | null;
  trust_attributes?: string[];
  /** TW14 provenance (REQ-CC-21) — populated when the inventory includes it
   *  for a derived publish; absent otherwise (the badge simply hides). */
  parent_skill_id?: string | null;
  parent_version?: string | null;
}

/** Integrity verdict of a `.zip` methodology package (REQ-IMP-3): the server
 *  re-inspects each quarantined package (checksum + official signature +
 *  compiler) and ships the verdict on every quarantine record. */
export interface PackageVerdict {
  ok: boolean;
  checksum_valid: boolean;
  signature_present: boolean;
  signature_valid: boolean | null;
  issues: string[];
}

/** One quarantined import (GET /api/methodologies/quarantine, REQ-IMP-3).
 *  `draft_id` is null until the Author trusts the package (REQ-IMP-4). */
export interface QuarantineRecord {
  package_id: string;
  verdict: PackageVerdict;
  trusted: boolean;
  clasificacion: string | null;
  trust_attributes: string[];
  draft_id: string | null;
}

/** Response of POST /api/methodologies/import — the package lands in
 *  quarantine with its integrity verdict; the library is never mutated by
 *  import (REQ-IMP-2). */
export interface ImportResult extends QuarantineRecord {}

/** Response of POST /api/methodologies/quarantine/{package_id}/trust — the
 *  promoted draft id when the Author trusts a package (REQ-IMP-4). */
export interface TrustQuarantineResult {
  package_id: string;
  trusted: boolean;
  draft_id: string | null;
  clasificacion: string | null;
  trust_attributes: string[];
}

/** Input for creating a methodology draft. */
export interface MethodologyDraftInput {
  skill_id: string;
  version: string;
  name: string;
  source: string;
  description?: string;
  phases?: string[];
  language?: string;
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
