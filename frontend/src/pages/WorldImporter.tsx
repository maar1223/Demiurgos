import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useWorlds } from "@/hooks/useWorlds";
import { WikiHomeLayout } from "@/components/templates/WikiHomeLayout";
import { Button } from "@/components/atoms/Button";
import { Icon } from "@/components/atoms/Icon";
import { Badge } from "@/components/atoms/Badge";
import { Spinner } from "@/components/atoms/Spinner";
import { ErrorBanner } from "@/components/organisms/ErrorBanner";
import { EmptyState } from "@/components/organisms/EmptyState";
import { ConfirmDialog } from "@/components/organisms/ConfirmDialog";
import { MarkdownViewer } from "@/components/organisms/MarkdownViewer";
import { getMediaUrl } from "@/api/wiki";
import { ApiError } from "@/api/types";
import { VisionSuggestionCard } from "@/components/molecules/VisionSuggestionCard";
import type {
  AppLanguage,
  ClassificationSuggestion,
  EnrichmentStatus,
  FrontmatterState,
  ImportApprovalResponse,
  ImportCandidate,
  ImportExecutionOutcome,
  ImportImagePlacement,
  ImportJob,
  ImportSuggestion,
  ImportSourceKind,
  MediaDiagnostic,
  RelationshipSuggestion,
  VisionSuggestion,
} from "@/api/types";
import {
  analyzeImportJob,
  approveImportGroups,
  cancelImportJob,
  createImportJob,
  deleteImportJob,
  executeImport,
  getImportJob,
  getImportReview,
  IMPORT_MAX_FILE_BYTES,
  IMPORT_MAX_JOB_BYTES,
  IMPORT_SYSTEM_DIRS,
  listImportJobs,
  postReviewDecisions,
  resumeImportJob,
  rollbackImportJob,
  streamImportFile,
  waitForJobTerminal,
} from "@/api/importer";
import { VALID_SECTIONS } from "@/lib/constants";
import { getErrorMessage } from "@/lib/utils";
import { cn } from "@/lib/utils";
import { useAppLanguage } from "@/hooks/useAppLanguage";
import type { MessageKey, TFunction } from "@/i18n/messages";

// ---------------------------------------------------------------------------
// World Importer — accessible, preservation-first import workflow (slice 3).
//
// Flow: select sources → analyze (read-only) → review + grouped approval →
// gated import → result. Write actions stay disabled until an explicit
// approval binds the reviewed diagnosis; the server is the authority for
// every state and the UI never implies success early.
// ---------------------------------------------------------------------------

// Classifier (BLOQUE 1 piece 1): per-document section choice offered by the
// importer. Local on purpose — deliberately NOT shared with VALID_SECTIONS,
// which also carries the full set. The server validates the same allow-list
// (CLASSIFIER_SECTIONS in import_router.py); this constant only pre-fills the
// dropdown (advisory, D2).
export const CLASSIFIER_SECTIONS = ["lore", "personajes", "referencias"] as const;
export type ClassifierSection = (typeof CLASSIFIER_SECTIONS)[number];

/** Bytes of file head scanned by the classifier heuristic. */
export const SUGGESTION_SCAN_BYTES = 8 * 1024;

const _PERSONAJES_KEYWORDS = [
  "personaje",
  "protagonista",
  "antagonista",
  "héroe",
  "villano",
  "criatura",
  "raza",
  "linaje",
  "clan",
  "familia",
];

const _REFERENCIAS_KEYWORDS = [
  "glosario",
  "índice",
  "apéndice",
  "términos",
  "vocabulario",
  "tabla de",
  "cronología",
  "bibliografía",
  "anexo",
];

/** Extract ``#``/``##`` heading lines (H1/H2) from a document. */
function extractHeadings(text: string): string[] {
  return text
    .split("\n")
    .filter((line) => /^(#{1,2})\s+/.test(line))
    .map((line) => line.replace(/^#{1,2}\s+/, "").trim());
}

/**
 * Deterministic, offline classifier suggestion for one source document.
 *
 * Scans the first ~8KB of text plus the H1/H2 heading lines (headings are
 * structure, so they count regardless of position). Spanish keyword tables
 * match case-insensitively; ``personajes`` signals win over ``referencias``,
 * and weak/no signal defaults to ``lore`` (neutral catch-all). Advisory only
 * (D2) — the author's explicit choice always wins; the server is the
 * authority for validation.
 */
export function suggestDocumentSection(text: string): string {
  const head = text.slice(0, SUGGESTION_SCAN_BYTES);
  const haystack = [head, ...extractHeadings(text)].join("\n").toLowerCase();
  if (_PERSONAJES_KEYWORDS.some((k) => haystack.includes(k))) {
    return "personajes";
  }
  if (_REFERENCIAS_KEYWORDS.some((k) => haystack.includes(k))) {
    return "referencias";
  }
  return "lore";
}

/** Catalogue key for a classifier section's display label (values stay lowercase). */
const CLASSIFIER_SECTION_KEYS: Record<ClassifierSection, MessageKey> = {
  lore: "section.lore",
  personajes: "section.personajes",
  referencias: "section.referencias",
};

function sectionKey(section: string): MessageKey {
  return CLASSIFIER_SECTION_KEYS[section as ClassifierSection] ?? "section.lore";
}

/** Read the first ``limit`` bytes of a File as text (advisory input).
 *  Uses FileReader — supported by every browser and jsdom (Blob.text() is
 *  not available in jsdom and degrades the heuristic to an empty string).
 *  Fail-open: any read error yields ``""`` → the heuristic defaults to lore. */
function readFileHead(file: File, limit: number): Promise<string> {
  const blob = file.slice(0, limit);
  return new Promise((resolve) => {
    const reader = new FileReader();
    reader.onload = () =>
      resolve(typeof reader.result === "string" ? reader.result : "");
    reader.onerror = () => resolve("");
    reader.readAsText(blob);
  });
}

type Step = "select" | "analyzing" | "review" | "result";

interface SelectedSource {
  file: File;
  relative: string;
  size: number;
  /** Classifier (BLOQUE 1 piece 1): lore | personajes | referencias. */
  section: string;
}

interface ApprovalGroup {
  id: string;
  label: string;
  description: string;
  count: number;
  requiresReview?: boolean;
}

const STORAGE_PREFIX = "demiurgos-importer-job:";

function storageKey(mundo: string): string {
  return `${STORAGE_PREFIX}${mundo}`;
}

function formatBytes(bytes: number): string {
  if (bytes >= 1024 ** 3) return `${(bytes / 1024 ** 3).toFixed(2)} GB`;
  if (bytes >= 1024 ** 2) return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
  if (bytes >= 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${bytes} B`;
}

/** Locale-friendly date for history rows (slice 2, IM-2.5). */
function formatHistoryDate(iso: string, language: AppLanguage): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString(language, {
    year: "numeric", month: "short", day: "2-digit",
    hour: "2-digit", minute: "2-digit",
  });
}

/** mm:ss elapsed counter for the live analysis/monitoring view. */
function formatElapsed(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m}:${s.toString().padStart(2, "0")}`;
}

/** Catalogue key for import-job states (server enum, kept honest). */
function historyStateKey(state: ImportJob["state"]): MessageKey {
  switch (state) {
    case "pending": return "importer.state.pending";
    case "intaking": return "importer.state.intaking";
    case "analyzing": return "importer.state.analyzing";
    case "review": return "importer.state.review";
    case "approved": return "importer.state.approved";
    case "executing": return "importer.state.executing";
    case "completed": return "importer.state.completed";
    case "cancelled": return "importer.state.cancelled";
    case "failed": return "importer.state.failed";
    case "rolled_back": return "importer.state.rolledBack";
  }
}

function historyStateVariant(state: ImportJob["state"]): "default" | "info" | "warning" | "success" | "error" {
  switch (state) {
    case "completed":
    case "approved":
      return "success";
    case "failed":
    case "rolled_back":
      return "error";
    case "cancelled":
      return "warning";
    case "review":
    case "executing":
    case "analyzing":
    case "intaking":
      return "info";
    case "pending":
    default:
      return "default";
  }
}

/** Catalogue key + badge variant for a candidate's frontmatter enrichment state. */
function frontmatterStateBadge(
  state: FrontmatterState,
): { labelKey: MessageKey; variant: "default" | "success" | "warning" } {
  switch (state) {
    case "generated":
      return { labelKey: "importer.frontmatter.generated", variant: "success" };
    case "fallback":
      return { labelKey: "importer.frontmatter.fallback", variant: "warning" };
    case "manual":
    default:
      return { labelKey: "importer.frontmatter.manual", variant: "default" };
  }
}

/** Unresolved reference-style media spans (``![][key]`` without definition). */
function unresolvedMedia(candidate: ImportCandidate): MediaDiagnostic[] {
  return candidate.media_diagnostics.filter((d) => d.status === "unresolved");
}

/**
 * Opción A — a history row is manually deletable only when it is terminal
 * (audit/debug kept by default but removable on demand) or an empty review.
 * A ``review`` with candidates is pending approval and is never deletable;
 * ``file_count`` mirrors the candidate count for a review job.
 */
function canDeleteHistoryJob(entry: ImportJob): boolean {
  return (
    entry.state === "completed" ||
    entry.state === "failed" ||
    entry.state === "rolled_back" ||
    (entry.state === "review" && entry.file_count === 0)
  );
}

/** System/transversal folders and hidden segments are never importable (W10/UI2). */
function isExcludedSourcePath(relative: string): boolean {
  const parts = relative.split("/").filter(Boolean);
  return parts.some(
    (part) =>
      part.startsWith(".") ||
      (IMPORT_SYSTEM_DIRS as readonly string[]).includes(part),
  );
}

/** Map a thrown error to honest, actionable copy for the importer flow. */
function importErrorMessage(err: unknown, t: TFunction): string {
  if (err instanceof ApiError) {
    if (err.status === 401) {
      return t("importer.error.sessionExpired");
    }
    if (err.status === 0) {
      return t("importer.error.connect");
    }
    return getErrorMessage(err.status, err.detail) ?? t("importer.error.generic");
  }
  return err instanceof Error ? err.message : t("importer.error.generic");
}

/** Editor link for an executed target like `lore/ciudades/X.md`. */
function editorPathForTarget(mundo: string, target: string): string {
  const segments = target.split("/");
  const section = segments[0];
  if (section && (VALID_SECTIONS as readonly string[]).includes(section)) {
    const rest = segments
      .slice(1)
      .map((s) => encodeURIComponent(s))
      .join("/");
    return `/wiki/${encodeURIComponent(mundo)}/${section}/${rest}`;
  }
  return `/wiki/${encodeURIComponent(mundo)}`;
}

/** Typed folder-picker attributes (webkitdirectory is not in stock types). */
type FolderInputAttrs = React.InputHTMLAttributes<HTMLInputElement> & {
  webkitdirectory?: string;
  directory?: string;
};

/**
 * Phase checklist for the slow analysis step (Windows-10-installer style).
 *
 * The previous progress bar was misleading: it jumped to ~80% once the parallel
 * chunks finished, then sat frozen on "ficha 60 de 60" while the doc-wide
 * last-filter recovery ran (it never updated the counter). A checklist with
 * discrete phases + a ficha counter reads as real progress instead. The stage
 * comes straight from the server's `progress_stage` (the funnel emits
 * "Consultando asistente — ficha X de Y" per chunk and "Recuperando fichas
 * pendientes" when the last filter starts).
 */
function Checklist({
  stage,
}: {
  stage: string;
  pct: number | null;
}) {
  const { t } = useAppLanguage();
  const consulting = stage.includes("Consultando asistente");
  const recovering = stage.includes("Recuperando fichas pendientes");
  const fichaMatch = stage.match(/ficha (\d+) de (\d+)/);
  // Sub-step the assistant is on inside "Consultando asistente" (the server
  // emits "resumiendo fichas" / "generando metadatos y relaciones").
  const substep = stage.includes("generando metadatos")
    ? t("importer.checklist.generating")
    : stage.includes("resumiendo") || (consulting && !fichaMatch)
      ? t("importer.checklist.summarizing")
      : undefined;
  const consultDetail = [
    substep,
    fichaMatch
      ? t("importer.checklist.fichaProgress", { index: fichaMatch[1], total: fichaMatch[2] })
      : undefined,
  ]
    .filter(Boolean)
    .join(" · ");
  const steps = [
    { id: "analyze", label: t("importer.checklist.analyzing"), done: true, current: false, detail: undefined as string | undefined },
    {
      id: "consult",
      label: t("importer.checklist.consulting"),
      done: recovering,
      current: consulting && !recovering,
      detail: consultDetail || undefined,
    },
    {
      id: "recover",
      label: t("importer.checklist.recovering"),
      done: false,
      current: recovering,
      detail: recovering ? t("importer.checklist.lastFilter") : undefined,
    },
  ];

  return (
    <ul className="mt-4 space-y-2" role="status" aria-live="polite">
      {steps.map((s) => (
        <li key={s.id} className="flex items-center gap-2 text-small">
          <span
            aria-hidden
            className={cn(
              "flex h-4 w-4 shrink-0 items-center justify-center",
              s.done ? "text-status-success" : s.current ? "text-action" : "text-muted",
            )}
          >
            {s.done ? (
              <Icon name="check" size={14} />
            ) : s.current ? (
              <Spinner size="sm" />
            ) : (
              <span className="block h-1.5 w-1.5 rounded-full bg-muted/50" />
            )}
          </span>
          <span className={cn(s.current ? "text-primary" : "text-muted")}>
            {s.label}
            {s.detail && <span className="ml-1 text-muted">· {s.detail}</span>}
          </span>
        </li>
      ))}
    </ul>
  );
}

export default function WorldImporter() {
  const navigate = useNavigate();
  const { language, t } = useAppLanguage();
  const { mundo } = useParams<{ mundo: string }>();
  const { worlds, isLoading: worldsLoading } = useWorlds();

  const [step, setStep] = useState<Step>("select");
  const [sourceKind, setSourceKind] = useState<ImportSourceKind>("loose");
  const [sources, setSources] = useState<SelectedSource[]>([]);
  const [excludedCount, setExcludedCount] = useState(0);
  const [precheckError, setPrecheckError] = useState<string | null>(null);

  const [job, setJob] = useState<ImportJob | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [analyzing, setAnalyzing] = useState(false);
  const [importing, setImporting] = useState(false);
  const [phaseMessage, setPhaseMessage] = useState("");
  const [streamProgress, setStreamProgress] = useState<{
    fileIndex: number;
    fileCount: number;
    streamed: number;
    total: number;
  } | null>(null);
  /** Server-owned analysis progress (stage + honest coarse percent). */
  const [analysisProgress, setAnalysisProgress] = useState<{
    stage: string;
    pct: number | null;
  } | null>(null);
  /** True while monitoring a job whose analyze POST timed out/lost connection. */
  const [monitoringAfterTimeout, setMonitoringAfterTimeout] = useState(false);
  /** Elapsed seconds since the analysis step started (monitoring UX). */
  const [elapsedSec, setElapsedSec] = useState(0);

  const [candidates, setCandidates] = useState<ImportCandidate[]>([]);
  // The review digest is never displayed; the approval response carries the
  // digest bound to execution (approval.digest).
  const [approval, setApproval] = useState<ImportApprovalResponse | null>(null);
  const [selectedGroups, setSelectedGroups] = useState<Set<string>>(new Set());
  const [outcomes, setOutcomes] = useState<ImportExecutionOutcome[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [resumeNotice, setResumeNotice] = useState<string | null>(null);
  const [restoring, setRestoring] = useState(true);
  // True when the recovered job is stuck in "intaking" — the file is already
  // on the server spool, so the user can skip re-selection and go straight to
  // analyze. Cleared on resetAll or when the user picks new files.
  const [resumeIntaking, setResumeIntaking] = useState(false);
  // Classifier (BLOQUE 1 piece 1): author-chosen sections of the resumed job
  // (relative_path → section). Overlaid on top of the heuristic suggestion
  // when the author re-selects the same sources after a resume, so the
  // dropdowns re-populate exactly as they were persisted server-side.
  const [persistedSections, setPersistedSections] = useState<
    Record<string, string>
  >({});

  // Enrichment (Hermes summaries/type/relationships) ALWAYS runs — it
  // produces the indexable OKF metadata the graph needs. There is no UI
  // opt-out: a checkbox the user could uncheck by accident would silently
  // strip fichas of type/relationships. (The API still honors an explicit
  // ``enrich: false`` for future power-user surfaces.)
  const [enrichmentStatus, setEnrichmentStatus] =
    useState<EnrichmentStatus>("disabled");
  /** Per-suggestion review state, indexed by suggestion id. */
  const [suggestionDecisions, setSuggestionDecisions] = useState<
    Map<string, "approved" | "rejected">
  >(new Map());
  /** Set of suggestion IDs the user has actually approved (used by execute). */
  const [approvedSuggestionIds, setApprovedSuggestionIds] = useState<string[]>(
    [],
  );
  /** True while a decisions POST is in flight (per-suggestion button disables). */
  const [decidingSuggestionId, setDecidingSuggestionId] = useState<string | null>(
    null,
  );

  // --- history (slice 2, IM-2.5) ----------------------------------------
  // Server-owned, principal-scoped history surfaced via GET /api/{m}/imports.
  // The server is authoritative; outage keeps the last good page and shows a
  // stale-banner so we never promote cached data as fresh.
  const [history, setHistory] = useState<ImportJob[]>([]);
  const [historyCursor, setHistoryCursor] = useState<string | null>(null);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyOutage, setHistoryOutage] = useState(false);

  // Opción A — manual reaping of terminal jobs. The target is held in state
  // until the ConfirmDialog is confirmed; a pending delete disables the dialog.
  const [deleteTarget, setDeleteTarget] = useState<ImportJob | null>(null);
  const [deleting, setDeleting] = useState(false);

  const fileInputRef = useRef<HTMLInputElement>(null);
  const headingRef = useRef<HTMLHeadingElement>(null);

  const worldExists = worlds.some((w) => w.name === mundo);

  // --- persisted job recovery (cancel/resume across reloads) ------------

  const persistJob = useCallback(
    (id: string, kind: ImportSourceKind, sections?: Record<string, string>) => {
      if (!mundo) return;
      try {
        sessionStorage.setItem(
          storageKey(mundo),
          JSON.stringify({ jobId: id, sourceKind: kind, sections }),
        );
      } catch {
        // storage unavailable — the flow continues without reload recovery
      }
    },
    [mundo],
  );

  const clearPersistedJob = useCallback(() => {
    if (!mundo) return;
    try {
      sessionStorage.removeItem(storageKey(mundo));
    } catch {
      // ignore
    }
  }, [mundo]);

  /**
   * Monitor a job whose analysis is still processing on the server.
   *
   * Shared by two paths: (1) reload/recovery of a job found in
   * ``pending``/``analyzing``, and (2) the analyze POST that timed out or
   * lost connection. Both poll GET until the job leaves the processing
   * states, render the server-owned stage/percentage, and land on review
   * (or a terminal error) without asking the user to reselect sources.
   */
  const monitorJob = useCallback(
    async (id: string, message: string) => {
      if (!mundo) return;
      setAnalyzing(true);
      setMonitoringAfterTimeout(true);
      setPhaseMessage(message);
      try {
        const terminal = await waitForJobTerminal(mundo, id, (job) => {
          setAnalysisProgress({
            stage: job.progress_stage || "Analizando",
            pct: job.progress_pct ?? null,
          });
        });
        setJob(terminal);
        if (terminal.state === "failed") {
          setStep("result");
          setError(
            terminal.error || t("importer.error.analysisFailed"),
          );
          return;
        }
        const review = await getImportReview(mundo, id);
        setCandidates(review.candidates);
        setJob(review.job);
        setEnrichmentStatus(review.enrichment_status ?? "disabled");
        setResumeIntaking(false);
        setStep("review");
      } catch (monitorErr) {
        setError(importErrorMessage(monitorErr, t));
        setPhaseMessage("");
        setStep("result");
      } finally {
        setAnalyzing(false);
        setMonitoringAfterTimeout(false);
      }
    },
    [mundo, t],
  );

  /**
   * Mirror live analysis progress from the server while the blocking ``analyze``
   * POST is in flight.
   *
   * The analyze endpoint is a long synchronous POST that only returns when the
   * analysis is terminal, but the server writes ``progress_stage`` /
   * ``progress_pct`` to the store as each phase completes. Without this loop the
   * Web App shows only a static spinner and then flashes a <1s progress bar from
   * the terminal job right before review. This poller reads the server-owned
   * progress during the POST and stops when the caller's ``finally`` runs. The
   * POST stays the authority for the terminal state; poll failures are ignored,
   * never treated as a server failure.
   */
  const startLiveProgressPoll = useCallback(
    (mundo: string, jobId: string): (() => void) => {
      let stopped = false;
      const poll = async () => {
        while (!stopped) {
          try {
            const { job: live } = await getImportJob(mundo, jobId);
            setAnalysisProgress({
              stage: live.progress_stage || "Analizando",
              pct: live.progress_pct ?? null,
            });
            if (
              live.state !== "pending" &&
              live.state !== "intaking" &&
              live.state !== "analyzing"
            ) {
              // Terminal — the POST is about to resolve; stop polling.
              break;
            }
          } catch {
            // Transient poll failure — the POST is the source of truth.
          }
          await new Promise((resolve) => setTimeout(resolve, 1_500));
        }
      };
      void poll();
      return () => {
        stopped = true;
      };
    },
    [],
  );

  /**
   * Drive the page into a known job's UI state from a server-confirmed job.
   * Shared between sessionStorage recovery and the "open from history"
   * handler so both paths go through the same branching on
   * ``ImportJob.state``. The server is the authority — if the job vanished
   * (404) the caller is responsible for clearing the local pointer.
   */
  const restoreJobState = useCallback(
    async (existing: ImportJob) => {
      if (!mundo) return;
      setJobId(existing.job_id);
      setSourceKind(existing.source_kind);
      setJob(existing);
      setResumeNotice(null);
      // Classifier (BLOQUE 1 piece 1): re-populate the dropdowns from the
      // job's persisted sections when the author re-selects the same files.
      setPersistedSections(existing.sections ?? {});
      if (existing.state === "review" || existing.state === "approved") {
        try {
          const review = await getImportReview(mundo, existing.job_id);
          setCandidates(review.candidates);
          setStep("review");
        } catch (err) {
          setError(importErrorMessage(err, t));
          setStep("result");
        }
      } else if (existing.state === "intaking") {
        // File is already on the server spool — the user can continue
        // analysis directly without re-selecting files.
        setStep("select");
        setResumeIntaking(true);
        setResumeNotice(
          t("importer.notice.intaking"),
        );
      } else if (existing.state === "pending" || existing.state === "analyzing") {
        // The server is still processing this job — monitor it live instead
        // of asking the user to reselect sources.
        setResumeIntaking(false);
        setStep("analyzing");
        void monitorJob(existing.job_id, t("importer.error.monitoringResume"));
      } else if (existing.state === "executing") {
        setResumeIntaking(false);
        setStep("select");
        setResumeNotice(
          t("importer.notice.interrupted"),
        );
      } else {
        // Terminal: completed / failed / cancelled / rolled_back.
        setOutcomes([]);
        setStep("result");
        // Terminal jobs must not keep prompting recovery on every reload.
        clearPersistedJob();
      }
    },
    [mundo, clearPersistedJob, monitorJob, t],
  );

  useEffect(() => {
    if (!mundo || worldsLoading) {
      return;
    }
    if (!worldExists) {
      setRestoring(false);
      return;
    }
    let stored: {
      jobId: string;
      sourceKind: ImportSourceKind;
      sections?: Record<string, string>;
    } | null = null;
    try {
      stored = JSON.parse(sessionStorage.getItem(storageKey(mundo)) ?? "null");
    } catch {
      stored = null;
    }
    if (!stored?.jobId) {
      setRestoring(false);
      return;
    }
    // Classifier (BLOQUE 1 piece 1): seed the dropdowns from the persisted
    // sections even before the server round-trip (restoreJobState re-applies
    // the authoritative job.sections once the fetch resolves).
    setPersistedSections(stored.sections ?? {});
    let cancelled = false;
    (async () => {
      try {
        const { job: existing } = await getImportJob(mundo, stored!.jobId);
        if (cancelled) return;
        await restoreJobState(existing);
      } catch (err) {
        // 404: the server no longer knows this job (deleted, expired, or
        // a different session cleared it). Drop the local pointer so we do
        // not keep retrying on every navigation.
        if (err instanceof ApiError && err.status === 404) {
          clearPersistedJob();
          setError(t("importer.error.savedJobGone"));
        }
        // Other failures (network / 5xx): leave sessionStorage intact so
        // the user can retry on the next mount.
      } finally {
        if (!cancelled) setRestoring(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [mundo, worldsLoading, worldExists, restoreJobState, clearPersistedJob, t]);

  // --- history loader (slice 2, IM-2.5) ----------------------------------
  //
  // The list is principal-scoped on the server. On outage we keep the last
  // successful page in state (the server already filtered it for this user)
  // and surface a "stale" indicator with a retry button — the UI never
  // promotes cached data as fresh.
  const loadHistory = useCallback(
    async (cursor: string | null = null) => {
      if (!mundo) return;
      setHistoryLoading(true);
      try {
        const page = await listImportJobs(mundo, { limit: 20, cursor });
        setHistory((prev) =>
          cursor ? [...prev, ...page.jobs] : page.jobs,
        );
        setHistoryCursor(page.next_cursor);
        setHistoryOutage(false);
      } catch {
        // Outage: keep the previous page in state so the user can still
        // browse what they last saw — but flag it as stale so we never
        // pretend cached data is authoritative.
        setHistoryOutage(true);
      } finally {
        setHistoryLoading(false);
      }
    },
    [mundo],
  );

  useEffect(() => {
    if (!mundo || worldsLoading || !worldExists) return;
    void loadHistory(null);
  }, [mundo, worldsLoading, worldExists, loadHistory]);

  /** Resume a job surfaced from the history list (slice 2, IM-2.5). */
  const handleOpenFromHistory = useCallback(
    async (entry: ImportJob) => {
      if (!mundo) return;
      persistJob(entry.job_id, entry.source_kind, entry.sections);
      await restoreJobState(entry);
    },
    [mundo, persistJob, restoreJobState],
  );

  /** Opción A — confirm-gated manual delete of a terminal job. */
  const handleDeleteJob = useCallback(
    async (entry: ImportJob) => {
      if (!mundo) return;
      setDeleting(true);
      setError(null);
      try {
        await deleteImportJob(mundo, entry.job_id);
        setDeleteTarget(null);
        // If the deleted job was the one being viewed, drop the local pointer
        // and return to a fresh selection; otherwise just refresh the history.
        if (jobId === entry.job_id) {
          clearPersistedJob();
          setJob(null);
          setJobId(null);
          setStep("select");
        }
        await loadHistory(null);
      } catch (err) {
        setError(importErrorMessage(err, t));
        setDeleteTarget(null);
      } finally {
        setDeleting(false);
      }
    },
    [mundo, jobId, loadHistory, clearPersistedJob, t],
  );

  // --- focus management: the step heading receives focus on transitions ---
  useEffect(() => {
    headingRef.current?.focus();
  }, [step]);

  // --- analysis elapsed timer (monitoring UX) -----------------------------
  useEffect(() => {
    if (step !== "analyzing") {
      setElapsedSec(0);
      return;
    }
    const id = window.setInterval(() => {
      setElapsedSec((s) => s + 1);
    }, 1000);
    return () => window.clearInterval(id);
  }, [step]);

  const resetAll = useCallback(() => {
    setStep("select");
    setSources([]);
    setExcludedCount(0);
    setPrecheckError(null);
    setJob(null);
    setJobId(null);
    setCandidates([]);
    setApproval(null);
    setSelectedGroups(new Set());
    setOutcomes([]);
    setError(null);
    setResumeNotice(null);
    setPhaseMessage("");
    setStreamProgress(null);
    setAnalysisProgress(null);
    setMonitoringAfterTimeout(false);
    setElapsedSec(0);
    setAnalyzing(false);
    setImporting(false);
    setEnrichmentStatus("disabled");
    setSuggestionDecisions(new Map());
    setApprovedSuggestionIds([]);
    setDecidingSuggestionId(null);
    setResumeIntaking(false);
    setPersistedSections({});
    clearPersistedJob();
  }, [clearPersistedJob]);

  // --- source selection ---------------------------------------------------

  const handleSourceKind = (kind: ImportSourceKind) => {
    setSourceKind(kind);
    setSources([]);
    setExcludedCount(0);
    setPrecheckError(null);
    setError(null);
    if (fileInputRef.current) fileInputRef.current.value = "";
  };

  const handleFilesChange = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const list = Array.from(event.target.files ?? []);
    if (list.length === 0) return;
    // User picked new files — the resume-intaking shortcut no longer applies.
    setResumeIntaking(false);
    const selected: SelectedSource[] = [];
    let excluded = 0;
    for (const file of list) {
      const webkitRelative = (file as File & { webkitRelativePath?: string })
        .webkitRelativePath;
      const relative =
        sourceKind === "folder" && webkitRelative
          ? webkitRelative
          : file.name;
      if (isExcludedSourcePath(relative)) {
        excluded += 1;
        continue;
      }
      // Classifier (BLOQUE 1 piece 1): start from the persisted section of a
      // resumed job (relative paths match exactly) or the neutral default;
      // the content heuristic upgrades the value right after.
      const section =
        persistedSections[relative] && CLASSIFIER_SECTIONS.includes(
          persistedSections[relative] as ClassifierSection,
        )
          ? persistedSections[relative]
          : "lore";
      selected.push({ file, relative, size: file.size, section });
    }
    setExcludedCount(excluded);
    setSources(selected);
    setApproval(null);
    setSelectedGroups(new Set());
    // Mirror the server bounds for honest pre-flight; the server enforces.
    const aggregate = selected.reduce((sum, s) => sum + s.size, 0);
    const oversized = selected.find((s) => s.size > IMPORT_MAX_FILE_BYTES);
    if (oversized) {
      setPrecheckError(
        t("importer.precheck.fileTooLarge", { name: oversized.relative }),
      );
    } else if (aggregate > IMPORT_MAX_JOB_BYTES) {
      setPrecheckError(
        t("importer.precheck.jobTooLarge"),
      );
    } else {
      setPrecheckError(null);
    }
    // Reset the input value so re-selecting the same files fires change again.
    event.target.value = "";
    // Classifier (BLOQUE 1 piece 1): advisory heuristic pre-fill — read the
    // head of each file and upgrade the section when the author has not
    // explicitly chosen one for that file yet. Persisted sections of a
    // resumed job win over the heuristic (D2: the author's prior decision is
    // final); an in-flight manual override also keeps its value.
    for (const s of selected) {
      const head = await readFileHead(s.file, SUGGESTION_SCAN_BYTES);
      setSources((prev) =>
        prev.map((p) =>
          p.relative === s.relative && !persistedSections[p.relative] && p.section === "lore"
            ? { ...p, section: suggestDocumentSection(head) }
            : p,
        ),
      );
    }
  };

  const openPicker = () => fileInputRef.current?.click();

  // --- classifier (BLOQUE 1 piece 1) --------------------------------------

  /** Author override: the author's explicit choice is final (D2) — the
   *  heuristic suggestion is discarded for that file. */
  const handleSectionChange = (relative: string, section: string) => {
    setSources((prev) =>
      prev.map((s) => (s.relative === relative ? { ...s, section } : s)),
    );
  };

  // --- analyze (read-only) ------------------------------------------------

  const handleAnalyze = async () => {
    // Resume-intaking: the file is already on the server spool, so skip
    // create + stream and go straight to analyze.
    const isResumeIntaking = resumeIntaking && jobId && sources.length === 0;
    if (!mundo || precheckError) return;
    if (!isResumeIntaking && sources.length === 0) return;
    setAnalyzing(true);
    setError(null);
    setResumeNotice(null);
    setPhaseMessage(t("importer.phase.preparing"));
    setStep("analyzing");
    setStreamProgress(null);
    setAnalysisProgress(null);
    setMonitoringAfterTimeout(false);
    // Slice 2 — reset advisory state for a fresh analyze. Suggestions live
    // on the candidate row, so a re-analyze supersedes the prior list.
    setEnrichmentStatus("disabled");
    setSuggestionDecisions(new Map());
    setApprovedSuggestionIds([]);
    setDecidingSuggestionId(null);
    let activeJobId: string | null = null;
    let stopLiveProgress: (() => void) | null = null;
    try {
      if (isResumeIntaking) {
        // File already uploaded — skip create + stream, go to analyze.
        activeJobId = jobId!;
        setPhaseMessage(
          t("importer.phase.analyzingReadOnly"),
        );
      } else {
        // Classifier (BLOQUE 1 piece 1): thread the author-chosen sections
        // (relative_path → section) into the create-job request; the server
        // validates them and persists them on the job for resume.
        const sections: Record<string, string> = {};
        for (const s of sources) {
          if (s.section) sections[s.relative] = s.section;
        }
        const { job: created } = await createImportJob(mundo, {
          source_kind: sourceKind,
          files: sources.map((s) => s.relative),
          sections,
        });
        activeJobId = created.job_id;
        setJobId(created.job_id);
        setJob(created);
        persistJob(created.job_id, sourceKind, sections);

        // Stream every file as durable chunks (idempotent at same offsets).
        const count = sources.length;
        for (let i = 0; i < count; i += 1) {
          const source = sources[i];
          setPhaseMessage(
            t("importer.phase.uploading", { relative: source.relative, index: i + 1, count }),
          );
          await streamImportFile(mundo, created.job_id, source.file, source.relative, (streamed, total) => {
            setStreamProgress({ fileIndex: i, fileCount: count, streamed, total });
          });
        }
        setStreamProgress(null);
        setPhaseMessage(
          t("importer.phase.analyzingReadOnly"),
        );
      }
      // Enrichment always runs (the graph needs the resulting metadata); the
      // flag is explicit for clarity and to honor a future ``enrich: false``.
      // Mirror live server progress while the long POST runs — the analyze
      // endpoint only returns at terminal, but the store carries each phase.
      stopLiveProgress = startLiveProgressPoll(mundo, activeJobId);
      const analysis = await analyzeImportJob(mundo, activeJobId, {
        enrich: true,
        // Vision (per-image content analysis) is a deliberate UX decision:
        // not exposed to the author and never requested for dense lore import.
        // Image PLACEMENT still works (DOCX position contract) — this only
        // skips the expensive image-content pass, which the backend also
        // disables by default (DEMIURGOS_IMPORT_VISION).
        vision: false,
      });
      setJob(analysis.job);
      setAnalysisProgress({
        stage: analysis.job.progress_stage || "Analizando",
        pct: analysis.job.progress_pct ?? null,
      });
      // Slice 2 — server-attributed enrichment status is batch-level; the
      // fail-open contract guarantees non-blocking even when the gateway
      // is unavailable (status === "error").
      if (analysis.enrichment_status) {
        setEnrichmentStatus(analysis.enrichment_status);
      }
      if (analysis.job.state === "failed") {
        setStep("result");
        setError(
          analysis.job.error || t("importer.error.analysisFailed"),
        );
        return;
      }
      const review = await getImportReview(mundo, activeJobId);
      setCandidates(review.candidates);
      setJob(review.job);
      // Review surfaces a server-rolled-up status; prefer it if the analyze
      // response was missing it (legacy callers or race with the lease).
      setEnrichmentStatus(review.enrichment_status ?? analysis.enrichment_status ?? "disabled");
      setResumeIntaking(false);
      setStep("review");
    } catch (err) {
      // A timeout/connection drop on the long synchronous analyze does NOT
      // mean the job failed — the server keeps working and reports
      // ``analyzing``. Monitor the same job by polling instead of declaring
      // a false server outage.
      stopLiveProgress?.();
      if (activeJobId) {
        await monitorJob(
          activeJobId,
          t("importer.error.connectionLostAnalyzing"),
        );
      } else {
        setError(importErrorMessage(err, t));
        setPhaseMessage("");
        setStep("result");
      }
    } finally {
      stopLiveProgress?.();
      setAnalyzing(false);
    }
  };

  const handleRetryAnalyze = async () => {
    // Intake retry re-streams from 0 (idempotent); cancelled/failed jobs
    // reopen review via resume. The server decides what is allowed.
    if (!mundo || !jobId) return;
    setError(null);
    if (job?.state === "cancelled" || job?.state === "failed") {
      try {
        const { job: resumed } = await resumeImportJob(mundo, jobId);
        setJob(resumed);
        if (resumed.state === "review") {
          const review = await getImportReview(mundo, jobId);
          setCandidates(review.candidates);
          setStep("review");
        } else {
          setStep("select");
          setResumeNotice(
            t("importer.notice.reopened"),
          );
        }
      } catch (err) {
        setError(importErrorMessage(err, t));
      }
      return;
    }
    if (sources.length === 0) {
      if (job?.state === "intaking") {
        // File already on the server spool — skip re-selection and
        // call analyze directly.
        setAnalyzing(true);
        setPhaseMessage(t("importer.phase.analyzingShort"));
        setStep("analyzing");
        const stopLiveProgress = startLiveProgressPoll(mundo, jobId);
        try {
          const analysis = await analyzeImportJob(mundo, jobId, {
            enrich: true,
            // Vision never requested (UX decision: not exposed to the author).
            vision: false,
          });
          setJob(analysis.job);
          if (analysis.enrichment_status) {
            setEnrichmentStatus(analysis.enrichment_status);
          }
          if (analysis.job.state === "failed") {
            setStep("result");
            setError(
              analysis.job.error || t("importer.error.analysisFailed"),
            );
            return;
          }
          const review = await getImportReview(mundo, jobId);
          setCandidates(review.candidates);
          setJob(review.job);
          setEnrichmentStatus(review.enrichment_status ?? analysis.enrichment_status ?? "disabled");
          setResumeIntaking(false);
          setStep("review");
        } catch (err) {
          setError(importErrorMessage(err, t));
          setPhaseMessage("");
          setStep("result");
        } finally {
          stopLiveProgress();
          setAnalyzing(false);
        }
        return;
      }
      setStep("select");
      setResumeNotice(
        t("importer.notice.reselect"),
      );
      return;
    }
    await handleAnalyze();
  };

  const handleCancel = async () => {
    if (!mundo || !jobId) return;
    setError(null);
    try {
      const { job: cancelled } = await cancelImportJob(mundo, jobId);
      setJob(cancelled);
      setStep("result");
    } catch (err) {
      setError(importErrorMessage(err, t));
    }
  };

  // --- grouped approval + gated execution ---------------------------------

  const groups = useMemo(() => {
    const fichas: ImportCandidate[] = [];
    const revisar: ImportCandidate[] = [];
    const rejected: ImportCandidate[] = [];
    for (const c of candidates) {
      if (c.status === "rejected") {
        rejected.push(c);
        continue;
      }
      const needsReview =
        c.status === "conflict" ||
        c.okf_issues.length > 0 ||
        c.images.some((i) => i.placement_status === "ambiguous");
      (needsReview ? revisar : fichas).push(c);
    }
    const imagePlacements = candidates
      .flatMap((c) => c.images)
      .filter(
        (i) =>
          i.placement_status !== "ambiguous" && i.placement_status !== "skip",
      );

    const result: ApprovalGroup[] = [
      {
        id: "fichas",
        label: t("importer.group.fichas.label"),
        description: t("importer.group.fichas.desc"),
        count: fichas.length,
      },
      {
        id: "imagenes",
        label: t("importer.group.images.label"),
        description: t("importer.group.images.desc"),
        count: imagePlacements.length,
      },
    ];
    // Candidates needing review count once — ambiguous image placements are
    // part of their candidate's review, never double-counted.
    const reviewCount = revisar.length;
    if (reviewCount > 0) {
      result.push({
        id: "revisar",
        label: t("importer.group.review.label"),
        description: t("importer.group.review.desc"),
        count: reviewCount,
        requiresReview: true,
      });
    }
    return { groups: result, rejected };
  }, [candidates, t]);

  const selectedGroupIds = [...selectedGroups];
  const canApprove = selectedGroupIds.length > 0 && !approval;
  const canImport = approval !== null && !importing;

  const toggleGroup = (id: string) => {
    setSelectedGroups((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
    setApproval(null);
  };

  const handleApprove = async () => {
    if (!mundo || !jobId || selectedGroupIds.length === 0) return;
    setError(null);
    try {
      // Slice 2 — bind the approval to the suggestion IDs the reviewer
      // actually approved (defaults to empty = no enrichment). The server
      // re-validates each ID's review_state and digest before issuing the
      // single-use token; stale IDs surface as a 409 here.
      const granted = await approveImportGroups(
        mundo,
        jobId,
        selectedGroupIds,
        approvedSuggestionIds,
      );
      setApproval(granted);
    } catch (err) {
      setError(importErrorMessage(err, t));
      // The diagnosis may have changed: re-read the review so the user
      // decides on current facts.
      try {
        const review = await getImportReview(mundo, jobId);
        setCandidates(review.candidates);
        } catch {
        // keep the current view; the error banner explains what happened
      }
    }
  };

  /**
   * Slice 2 — toggle one suggestion's review_state via the decisions
   * endpoint. Failures revert the local state so the UI never lies about
   * what the server accepted; we also re-read the review so the candidate
   * row reflects server-truth on the next render.
   */
  const handleSuggestionDecision = async (
    candidateId: string,
    suggestionId: string,
    decision: "approve" | "reject",
  ) => {
    if (!mundo || !jobId) return;
    const priorDecision = suggestionDecisions.get(suggestionId) ?? null;
    setError(null);
    setDecidingSuggestionId(suggestionId);
    // Optimistic local state: reflect the user's choice immediately so the
    // UI stays responsive. We re-read the row on failure to reconcile.
    setSuggestionDecisions((prev) => {
      const next = new Map(prev);
      if (decision === "reject") {
        next.set(suggestionId, "rejected");
      } else {
        next.set(suggestionId, "approved");
      }
      return next;
    });
    setApprovedSuggestionIds((prev) => {
      const without = prev.filter((id) => id !== suggestionId);
      return decision === "approve" ? [...without, suggestionId] : without;
    });
    try {
      await postReviewDecisions(mundo, jobId, [
        { suggestion_id: suggestionId, decision },
      ]);
      // Refresh the row so the server's review_state is reflected (and any
      // sibling suggestion decisions stay in sync).
      try {
        const review = await getImportReview(mundo, jobId);
        setCandidates(review.candidates);
        setEnrichmentStatus(review.enrichment_status ?? enrichmentStatus);
      } catch {
        // network outage — keep the optimistic state, the next reload
        // will reconcile from the server
      }
    } catch (err) {
      // Revert optimistic state so the UI never claims a server failure
      // succeeded.
      setSuggestionDecisions((prev) => {
        const next = new Map(prev);
        if (priorDecision === null) {
          next.delete(suggestionId);
        } else {
          next.set(suggestionId, priorDecision);
        }
        return next;
      });
      setApprovedSuggestionIds((prev) => {
        if (decision !== "approve") return prev;
        // Remove the freshly-added ID; prior rejections don't matter here
        // because we only added an "approved" entry optimistically.
        return prev.filter((id) => id !== suggestionId);
      });
      setError(importErrorMessage(err, t));
    } finally {
      setDecidingSuggestionId(null);
    }
    // candidateId is reserved for future row-scoped updates (e.g., bulk
    // approve-all-on-this-candidate); the current single-suggestion path
    // only needs suggestionId.
    void candidateId;
  };

  const handleExecute = async () => {
    if (!mundo || !jobId || !approval) return;
    setImporting(true);
    setError(null);
    setPhaseMessage(t("importer.phase.importing"));
    // The step stays "review" — the importing progress panel renders there.
    try {
      // PR3+ — ``approvedSuggestionIds`` carries BOTH text and vision
      // suggestion IDs (both families write into the same array via
      // handleSuggestionDecision), so approved vision images are bound to the
      // token and reach execute in the same request.
      const result = await executeImport(
        mundo,
        jobId,
        approval.digest,
        approval.token,
        approvedSuggestionIds,
      );
      setJob(result.job);
      setOutcomes(result.outcomes);
      setStep("result");
    } catch (err) {
      // Uncertain failure: ask the server what actually happened.
      let state = job?.state;
      try {
        const { job: current } = await getImportJob(mundo, jobId);
        state = current.state;
        setJob(current);
      } catch {
        // network is gone; keep the previous state
      }
      if (state === "completed") {
        // The server persisted the import even though the response was lost.
        // Report success honestly — never a false failure.
        setStep("result");
        return;
      }
      setApproval(null);
      setError(importErrorMessage(err, t));
      setStep("review");
      try {
        const review = await getImportReview(mundo, jobId);
        setCandidates(review.candidates);
        } catch {
        // keep current review data
      }
    } finally {
      setImporting(false);
    }
  };

  const handleResume = async () => {
    if (!mundo || !jobId) return;
    setError(null);
    try {
      const { job: resumed } = await resumeImportJob(mundo, jobId);
      setJob(resumed);
      if (resumed.state === "review") {
        const review = await getImportReview(mundo, jobId);
        setCandidates(review.candidates);
          setStep("review");
      } else {
        setStep("select");
        setResumeNotice(
          t("importer.notice.reselect"),
        );
      }
    } catch (err) {
      setError(importErrorMessage(err, t));
    }
  };

  const handleRollback = async () => {
    if (!mundo || !jobId) return;
    setError(null);
    try {
      const { job: rolledBack } = await rollbackImportJob(mundo, jobId);
      setJob(rolledBack);
      setStep("result");
    } catch (err) {
      setError(importErrorMessage(err, t));
    }
  };

  const handleChangeSources = async () => {
    if (mundo && jobId) {
      try {
        await cancelImportJob(mundo, jobId);
      } catch {
        // terminal jobs are already closed; proceed to a fresh selection
      }
    }
    resetAll();
  };

  // --- render -------------------------------------------------------------

  const headingText =
    step === "select"
      ? t("importer.heading.select")
      : step === "analyzing"
        ? t("importer.heading.analyzing")
        : step === "review"
          ? t("importer.heading.review")
          : t("importer.heading.result");

  const folderAttrs: FolderInputAttrs = { webkitdirectory: "", directory: "" };

  return (
    <WikiHomeLayout>
      <div className="col-span-full">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h1
            ref={headingRef}
            tabIndex={-1}
            className="font-heading text-h3 text-primary focus:outline-none"
          >
            {headingText}
          </h1>
          {mundo && (
            <Badge variant="info">
              {t("importer.worldBadge", { mundo })}
            </Badge>
          )}
        </div>

        {/* Preservation-first messaging — shown from the start */}
        <div className="mt-3 rounded-lg border border-action/40 bg-action/10 px-4 py-3 text-small text-primary">
          <span className="font-medium">{t("importer.preservation.title")}</span>{" "}
          {t("importer.preservation.body")}
        </div>

        {error && (
          <div className="mt-4">
            <ErrorBanner message={error} onRetry={() => setError(null)} />
          </div>
        )}
      </div>

      {worldsLoading && (
        <div className="col-span-full flex items-center justify-center py-24">
          <Spinner size="lg" />
        </div>
      )}

      {!worldsLoading && mundo && !worldExists && (
        <div className="col-span-full">
          <EmptyState
            icon="error"
            message={t("importer.worldMissing")}
            actionLabel={t("importer.goHome")}
            onAction={() => navigate("/wiki")}
          />
        </div>
      )}

      {!worldsLoading && restoring && worldExists && (
        <div className="col-span-full flex items-center justify-center py-24">
          <Spinner size="lg" />
        </div>
      )}

      {!worldsLoading && !restoring && mundo && worldExists && step === "select" && (
        <div className="col-span-full">
          {resumeNotice && (
            <div
              className="mb-4 rounded-lg border border-action/40 bg-action/10 px-4 py-3 text-small text-primary"
              role="status"
            >
              <Icon name="lightbulb" size={16} />
              <span className="ml-2">{resumeNotice}</span>
            </div>
          )}

          {/* History (slice 2, IM-2.5): principal-scoped, newest first. The
              server is authoritative; during outage we keep the last good
              page and surface a stale indicator rather than promoting cached
              data as fresh. */}
          <section
            aria-labelledby="import-history-title"
            className="mt-4 rounded-lg border border-edge bg-surface-raised p-4"
            data-testid="import-history"
          >
            <header className="flex flex-wrap items-center justify-between gap-2">
              <h2
                id="import-history-title"
                className="font-heading text-body text-primary"
              >
                {t("importer.history.title")}
              </h2>
              {historyOutage && (
                <span
                  className="flex items-center gap-2 text-small text-muted"
                  role="status"
                  aria-live="polite"
                  data-testid="history-outage"
                >
                  {t("importer.history.stale")}
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => void loadHistory(null)}
                    disabled={historyLoading}
                  >
                    <Icon name="refresh" size={14} />
                    {t("importer.retry")}
                  </Button>
                </span>
              )}
            </header>

            {historyLoading && history.length === 0 && (
              <div className="mt-3 flex items-center gap-2 text-small text-muted">
                <Spinner size="sm" />
                <span>{t("importer.history.loading")}</span>
              </div>
            )}

            {!historyLoading && history.length === 0 && !historyOutage && (
              <p
                className="mt-3 text-small text-muted"
                data-testid="history-empty"
              >
                {t("importer.history.empty")}
              </p>
            )}

            {history.length > 0 && (
              <ul
                className="mt-3 flex flex-col gap-2"
                data-testid="history-list"
              >
                {history.map((entry) => (
                  <li
                    key={entry.job_id}
                    className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-edge bg-surface px-3 py-2"
                  >
                    <div className="min-w-0 flex-1">
                      <p className="text-small font-medium text-primary">
                        {formatHistoryDate(entry.created_at, language)}{" "}
                        <Badge
                          variant={historyStateVariant(entry.state)}
                          className="ml-1"
                        >
                          {t(historyStateKey(entry.state))}
                        </Badge>
                      </p>
                      <p className="mt-0.5 text-xs text-muted">
                        {entry.source_kind} · {entry.file_count}{" "}
                        {t(entry.file_count === 1 ? "importer.history.candidateOne" : "importer.history.candidateMany")}
                      </p>
                    </div>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => void handleOpenFromHistory(entry)}
                      data-testid={`history-open-${entry.job_id}`}
                    >
                      <Icon name="corner-up-right" size={14} />
                      {t("importer.history.open")}
                    </Button>
                    {canDeleteHistoryJob(entry) && (
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => setDeleteTarget(entry)}
                        data-testid={`history-delete-${entry.job_id}`}
                        aria-label={t("importer.history.deleteAria", { date: formatHistoryDate(entry.created_at, language) })}
                      >
                        <Icon name="trash" size={14} />
                        {t("importer.history.delete")}
                      </Button>
                    )}
                  </li>
                ))}
              </ul>
            )}

            {historyCursor && (
              <div className="mt-3">
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => void loadHistory(historyCursor)}
                  disabled={historyLoading}
                  data-testid="history-load-more"
                >
                  {historyLoading ? t("importer.history.loadingShort") : t("importer.history.loadMore")}
                </Button>
              </div>
            )}
          </section>

          <fieldset className="mt-4 rounded-lg border border-edge bg-surface-raised p-4">
            <legend className="px-2 text-small font-medium text-muted">
              {t("importer.sourceType")}
            </legend>
            <div className="flex flex-wrap gap-2">
              {(
                [
                  { kind: "folder", label: t("importer.source.folder"), hint: t("importer.source.folderHint") },
                  { kind: "loose", label: t("importer.source.loose"), hint: t("importer.source.looseHint") },
                  { kind: "zip", label: t("importer.source.zip"), hint: t("importer.source.zipHint") },
                ] as { kind: ImportSourceKind; label: string; hint: string }[]
              ).map((option) => (
                <button
                  key={option.kind}
                  type="button"
                  aria-pressed={sourceKind === option.kind}
                  onClick={() => handleSourceKind(option.kind)}
                  className={cn(
                    "flex flex-col gap-0.5 rounded-lg border px-4 py-2 text-left text-small transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-action/50",
                    sourceKind === option.kind
                      ? "border-action bg-action/10 text-primary"
                      : "border-edge bg-surface text-muted hover:border-action/40",
                  )}
                >
                  <span className="font-medium">{option.label}</span>
                  <span className="text-xs">{option.hint}</span>
                </button>
              ))}
            </div>
          </fieldset>

          <div className="mt-4">
            <Button
              variant="secondary"
              onClick={openPicker}
              disabled={analyzing}
            >
              <Icon name="upload" size={16} />
              {sourceKind === "folder"
                ? t("importer.selectFolder")
                : sourceKind === "zip"
                  ? t("importer.selectZip")
                  : t("importer.selectFiles")}
            </Button>
            <input
              ref={fileInputRef}
              type="file"
              className="sr-only"
              multiple={sourceKind !== "zip"}
              accept={sourceKind === "zip" ? ".zip" : undefined}
              {...(sourceKind === "folder" ? folderAttrs : {})}
              onChange={handleFilesChange}
              aria-label={t("importer.sourcesAria")}
            />
          </div>

          {excludedCount > 0 && (
            <p className="mt-3 text-small text-muted">
              {t(excludedCount === 1 ? "importer.excluded.one" : "importer.excluded.many", { count: excludedCount })}
            </p>
          )}

          {precheckError && (
            <p className="mt-3 text-small text-status-error" role="alert">
              {precheckError}
            </p>
          )}

          {sources.length > 0 && (
            <ul className="mt-4 max-h-64 divide-y divide-edge overflow-y-auto rounded-lg border border-edge bg-surface">
              {sources.map((s) => (
                <li
                  key={s.relative}
                  className="flex items-center justify-between gap-3 px-3 py-2 text-small text-primary"
                >
                  <span className="min-w-0 truncate" title={s.relative}>
                    {s.relative}
                  </span>
                  <span className="flex shrink-0 items-center gap-3">
                    {/* Classifier (BLOQUE 1 piece 1): per-file section
                        choice. Pre-filled by the heuristic (or the persisted
                        job sections on resume); the author may override —
                        the choice is final (D2). */}
                    <select
                      value={s.section}
                      onChange={(e) => handleSectionChange(s.relative, e.target.value)}
                      aria-label={t("importer.sectionOf", { relative: s.relative })}
                      className="rounded border border-edge bg-surface px-1.5 py-0.5 text-xs text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-action/50"
                    >
                      {CLASSIFIER_SECTIONS.map((opt) => (
                        <option key={opt} value={opt}>
                          {t(sectionKey(opt))}
                        </option>
                      ))}
                    </select>
                    <span className="text-xs text-muted">
                      {formatBytes(s.size)}
                    </span>
                  </span>
                </li>
              ))}
            </ul>
          )}

          <div className="mt-5 flex flex-wrap items-center gap-3">
            <Button
              variant="secondary"
              onClick={handleAnalyze}
              disabled={(!resumeIntaking && sources.length === 0) || Boolean(precheckError) || analyzing}
              data-testid={resumeIntaking ? "resume-analyze-btn" : undefined}
            >
              <Icon name={resumeIntaking ? "corner-up-right" : "search"} size={16} />
              {resumeIntaking ? t("importer.continueAnalysis") : t("importer.analyzeReadOnly")}
            </Button>
            {sources.length > 0 && (
              <span className="text-small text-muted">
                {t("importer.filesSummary", {
                  count: sources.length,
                  noun: t(sources.length === 1 ? "importer.fileOne" : "importer.fileMany"),
                  size: formatBytes(sources.reduce((sum, s) => sum + s.size, 0)),
                })}
              </span>
            )}
          </div>
        </div>
      )}

      {!worldsLoading && !restoring && mundo && worldExists && step === "analyzing" && (
        <div className="col-span-full">
          <div className="rounded-lg border border-edge bg-surface-raised p-6">
            <div className="flex items-center gap-3">
              <Spinner size="md" />
              <div role="status" aria-live="polite">
                <p className="text-body text-primary">{phaseMessage}</p>
                {streamProgress && (
                  <p className="mt-1 text-small text-muted">
                    {t("importer.streamSummary", {
                      streamed: formatBytes(streamProgress.streamed),
                      total: formatBytes(streamProgress.total),
                      index: streamProgress.fileIndex + 1,
                      count: streamProgress.fileCount,
                    })}
                  </p>
                )}
                {analysisProgress && !streamProgress && (
                  <>
                    <p className="mt-1 text-small text-muted">
                      {t("importer.stage", { stage: analysisProgress.stage })}
                    </p>
                    <p className="mt-1 text-small text-muted">
                      {monitoringAfterTimeout
                        ? t("importer.reconnecting")
                        : t("importer.elapsed", { elapsed: formatElapsed(elapsedSec) })}
                    </p>
                  </>
                )}
              </div>
            </div>
            {streamProgress && streamProgress.total > 0 && (
              <div
                className="mt-4 h-1.5 w-full overflow-hidden rounded-full bg-surface-raised"
                role="progressbar"
                aria-valuemin={0}
                aria-valuemax={streamProgress.total}
                aria-valuenow={streamProgress.streamed}
                aria-label={t("importer.uploadProgressAria")}
              >
                <div
                  className="h-full bg-action transition-all"
                  style={{
                    width: `${Math.round(
                      (streamProgress.streamed / streamProgress.total) * 100,
                    )}%`,
                  }}
                />
              </div>
            )}
            {analysisProgress && !streamProgress && (
              <Checklist
                stage={analysisProgress.stage}
                pct={analysisProgress.pct}
              />
            )}
            <div className="mt-5">
              <Button variant="ghost" onClick={handleCancel}>
                <Icon name="stop" size={16} />
                {t("importer.cancelAnalysis")}
              </Button>
            </div>
          </div>
        </div>
      )}

      {!worldsLoading && !restoring && mundo && worldExists && step === "review" && (
        <div className="col-span-full">
          <p className="text-body text-muted">
            {t("importer.review.intro")}
          </p>

          {/* Importador-auto-frontmatter (Phase 4) — on-screen H1-H5 authoring
              guide. Explains how headings map to roots/folders/fichas and how
              empty scaffolding is preserved, so the author sees the mapping
              and empty-section behavior before approving. */}
          <details
            className="mt-4 rounded-lg border border-edge bg-surface-raised"
            data-testid="authoring-guide"
          >
            <summary className="flex cursor-pointer items-center justify-between gap-2 px-4 py-3 text-small font-medium text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-action/50 [&::-webkit-details-marker]:hidden">
              <span>{t("importer.guide.summary")}</span>
              <Icon
                name="chevron-down"
                size={14}
                className="transition-transform group-open:rotate-180"
              />
            </summary>
            <div className="border-t border-edge px-4 py-3 text-xs text-muted">
              <p className="text-primary">
                {t("importer.guide.intro")}
              </p>
              <ul className="mt-2 list-disc space-y-1 pl-4">
                <li>
                  <span className="text-primary">H1</span> {t("importer.guide.h1Body")}
                </li>
                <li>
                  <span className="text-primary">H2–H5</span> {t("importer.guide.h2Body")}
                </li>
                <li>
                  <span className="text-primary">{t("importer.guide.plainLabel")}</span>{" "}
                  {t("importer.guide.plainBody")}
                </li>
                <li>
                  <span className="text-primary">{t("importer.guide.noHeadingsLabel")}</span>{" "}
                  {t("importer.guide.noHeadingsBody")}
                </li>
              </ul>
            </div>
          </details>

          {/* Slice 2 — enrichment status banner. Mirrors the server-attributed
              state so reviewers never see a different answer than the audit
              log. "disabled" hides the banner entirely to keep the legacy
              copy clean. */}
          <EnrichmentStatusBanner status={enrichmentStatus} />

          {/* Impact summary */}
          <div className="mt-4 grid grid-cols-1 gap-3 tablet:grid-cols-3">
            <SummaryTile
              label={t("importer.summary.candidates")}
              value={String(candidates.length)}
            />
            <SummaryTile
              label={t("importer.summary.images")}
              value={String(
                candidates.flatMap((c) => c.images).filter((i) => i.placement_status !== "skip").length,
              )}
            />
            <SummaryTile
              label={t("importer.summary.needDecision")}
              value={String(groups.groups.find((g) => g.id === "revisar")?.count ?? 0)}
            />
          </div>

          {candidates.length === 0 && (
            <div className="mt-6">
              <EmptyState
                icon="empty"
                message={t("importer.empty.noContent")}
              />
              <div className="mt-4 flex flex-wrap gap-2">
                <Button variant="secondary" onClick={handleChangeSources}>
                  <Icon name="chevron-left" size={16} />
                  {t("importer.changeSources")}
                </Button>
                {job && (
                  <Button
                    variant="ghost"
                    onClick={() => setDeleteTarget(job)}
                    data-testid="review-delete-job"
                  >
                    <Icon name="trash" size={16} />
                    {t("importer.deleteJob")}
                  </Button>
                )}
              </div>
            </div>
          )}

          {/* Grouped approval */}
          {candidates.length > 0 && (
            <>
              <fieldset className="mt-6 rounded-lg border border-edge bg-surface-raised p-4">
                <legend className="px-2 text-small font-medium text-muted">
                  {t("importer.groups.legend")}
                </legend>
                <div className="flex flex-col gap-3">
                  {groups.groups.map((group) => (
                    <label
                      key={group.id}
                      className={cn(
                        "flex cursor-pointer items-start gap-3 rounded-lg border p-3 transition-colors focus-within:ring-2 focus-within:ring-action/50",
                        group.requiresReview
                          ? "border-action/40 bg-action/5"
                          : "border-edge bg-surface",
                      )}
                    >
                      <input
                        type="checkbox"
                        className="mt-0.5 h-4 w-4 accent-action"
                        checked={selectedGroups.has(group.id)}
                        onChange={() => toggleGroup(group.id)}
                        aria-describedby={`group-${group.id}-desc`}
                      />
                      <span>
                        <span className="block text-small font-medium text-primary">
                          {group.label} ({group.count})
                          {group.requiresReview && (
                            <Badge variant="warning" className="ml-2">
                              {t("importer.group.reviewBadge")}
                            </Badge>
                          )}
                        </span>
                        <span
                          id={`group-${group.id}-desc`}
                          className="block text-xs text-muted"
                        >
                          {group.description}
                        </span>
                      </span>
                    </label>
                  ))}
                  {groups.rejected.length > 0 && (
                    <p className="text-small text-muted">
                      {t(groups.rejected.length === 1 ? "importer.group.rejected.one" : "importer.group.rejected.many", { count: groups.rejected.length })}
                    </p>
                  )}
                </div>
              </fieldset>

              {/* Candidate detail review (expandable) */}
              <h2 className="mt-6 font-heading text-h4 text-primary">
                {t("importer.candidates.title")}
              </h2>
              <div className="mt-2 flex flex-col gap-3">
                {candidates.map((candidate) => (
                  <CandidateCard
                    key={candidate.candidate_id}
                    candidate={candidate}
                    mundo={mundo}
                    suggestionDecisions={suggestionDecisions}
                    onSuggestionDecision={handleSuggestionDecision}
                    decidingSuggestionId={decidingSuggestionId}
                  />
                ))}
              </div>

              {/* Approval + execution gate */}
              <div className="mt-6 rounded-lg border border-edge bg-surface-raised p-4">
                {!approval ? (
                  <>
                    <p className="text-small text-muted">
                      {t("importer.approval.bound")}
                    </p>
                    {approvedSuggestionIds.length > 0 && (
                      <p
                        className="mt-2 text-small text-primary"
                        data-testid="approved-suggestions-summary"
                      >
                        <Icon name="lightbulb" size={14} />
                        <span className="ml-2">
                          {t(approvedSuggestionIds.length === 1 ? "importer.approval.suggestions.one" : "importer.approval.suggestions.many", { count: approvedSuggestionIds.length })}
                        </span>
                      </p>
                    )}
                    <div className="mt-3">
                      <Button
                        variant="secondary"
                        onClick={handleApprove}
                        disabled={!canApprove}
                      >
                        {t("importer.approval.approveGroups")}
                      </Button>
                    </div>
                  </>
                ) : (
                  <>
                    <p className="text-small text-primary" role="status">
                      <Icon name="check" size={16} />
                      <span className="ml-2">
                        {t(selectedGroupIds.length === 1 ? "importer.approval.approved.one" : "importer.approval.approved.many", { count: selectedGroupIds.length })}
                      </span>
                    </p>
                    <p className="mt-2 text-small text-muted">
                      {t("importer.approval.writeWarning")}
                    </p>
                    <div className="mt-3 flex flex-wrap gap-2">
                      <Button
                        variant="primary"
                        onClick={handleExecute}
                        disabled={!canImport}
                        aria-describedby="import-write-warning"
                      >
                        <Icon name="save" size={16} />
                        {t("importer.approval.import")}
                      </Button>
                      <Button
                        variant="ghost"
                        onClick={() => setApproval(null)}
                        disabled={importing}
                      >
                        {t("importer.approval.changeSelection")}
                      </Button>
                    </div>
                    <p
                      id="import-write-warning"
                      className="mt-2 text-xs text-muted"
                    >
                      {t("importer.approval.permanent")}
                    </p>
                  </>
                )}
              </div>

              <div className="mt-4">
                <Button variant="ghost" onClick={handleChangeSources}>
                  <Icon name="chevron-left" size={16} />
                  {t("importer.changeSources")}
                </Button>
              </div>
            </>
          )}

          {importing && (
            <div className="mt-4 rounded-lg border border-edge bg-surface-raised p-4" role="status" aria-live="polite">
              <div className="flex items-center gap-3">
                <Spinner size="md" />
                <span className="text-body text-primary">
                  {phaseMessage}
                </span>
              </div>
            </div>
          )}
        </div>
      )}

      {!worldsLoading && !restoring && mundo && worldExists && step === "result" && (
        <ResultPanel
          job={job}
          outcomes={outcomes}
          mundo={mundo}
          onResume={handleResume}
          onRetryAnalyze={handleRetryAnalyze}
          onRollback={handleRollback}
          onNewImport={resetAll}
          onNavigateEditor={(target) =>
            navigate(editorPathForTarget(mundo, target))
          }
        />
      )}

      {deleteTarget && (
        <ConfirmDialog
          title={t("importer.delete.title")}
          message={t("importer.delete.message", { id: deleteTarget.job_id })}
          confirmLabel={t("importer.delete.confirm")}
          confirmVariant="danger"
          isBusy={deleting}
          onConfirm={() => void handleDeleteJob(deleteTarget)}
          onClose={() => setDeleteTarget(null)}
        />
      )}
    </WikiHomeLayout>
  );
}

// ---------------------------------------------------------------------------
// Small presentational pieces
// ---------------------------------------------------------------------------

function SummaryTile({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-edge bg-surface-raised p-4">
      <p className="text-xs uppercase tracking-wide text-muted">
        {label}
      </p>
      <p className="mt-1 font-heading text-h4 text-primary">{value}</p>
    </div>
  );
}

function CandidateCard({
  candidate,
  mundo,
  suggestionDecisions,
  onSuggestionDecision,
  decidingSuggestionId,
}: {
  candidate: ImportCandidate;
  mundo: string;
  suggestionDecisions: Map<string, "approved" | "rejected">;
  onSuggestionDecision: (
    candidateId: string,
    suggestionId: string,
    decision: "approve" | "reject",
  ) => void;
  decidingSuggestionId: string | null;
}) {
  const { t } = useAppLanguage();
  const ambiguousImages = candidate.images.filter(
    (i) => i.placement_status === "ambiguous",
  );
  const hasIssues = candidate.okf_issues.length > 0;
  const suggestions = candidate.enrichment_json ?? [];
  // PR3+ — vision suggestions ride in the same enrichment payload with
  // ``__type__: "vision"``. They render in their own card family (verdict +
  // per-image approval) below; the text family keeps classification and
  // relationship cards.
  const visionSuggestions = suggestions.filter(
    (s): s is VisionSuggestion & { __type__: "vision" } =>
      s.__type__ === "vision",
  );
  const textSuggestions = suggestions.filter(
    (s): s is Exclude<ImportSuggestion, VisionSuggestion & { __type__: "vision" }> =>
      s.__type__ !== "vision",
  );
  // Importador-auto-frontmatter (Phase 4) — analyzed metadata for the ficha.
  const fmBadge = candidate.frontmatter
    ? frontmatterStateBadge(candidate.frontmatter.state)
    : null;
  const unresolvedMediaSpans = unresolvedMedia(candidate);
  const resolvedMediaCount =
    candidate.media_diagnostics.length - unresolvedMediaSpans.length;
  // Canonical identity: the ficha's stable ``::``-qualified identity. Prefer
  // the display title for the human label; fall back to the identity itself.
  const fichaTitle =
    candidate.display_title || candidate.normalized_identity;

  return (
    <details className="group rounded-lg border border-edge bg-surface-raised">
      <summary className="flex cursor-pointer flex-wrap items-center justify-between gap-2 px-4 py-3 text-small font-medium text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-action/50 [&::-webkit-details-marker]:hidden">
        <span className="min-w-0 truncate">
          {fichaTitle}
          <span className="ml-2 text-xs font-normal text-muted">
            {candidate.provenance.source_path}
          </span>
        </span>
        <span className="flex items-center gap-2">
          {fmBadge && (
            <span
              data-testid={`frontmatter-state-${candidate.candidate_id}`}
            >
              <Badge variant={fmBadge.variant}>{t(fmBadge.labelKey)}</Badge>
            </span>
          )}
          {hasIssues && <Badge variant="warning">{t("importer.candidate.validation")}</Badge>}
          {ambiguousImages.length > 0 && (
            <Badge variant="warning">{t("importer.candidate.ambiguous")}</Badge>
          )}
          {unresolvedMediaSpans.length > 0 && (
            <span data-testid={`media-warning-${candidate.candidate_id}`}>
              <Badge variant="warning">
                {t("importer.candidate.unresolvedMedia", { count: unresolvedMediaSpans.length })}
              </Badge>
            </span>
          )}
          {candidate.images.length > 0 && candidate.images.length - ambiguousImages.length > 0 && (
            <Badge variant="info">{t("importer.candidate.imagesCount", { count: candidate.images.length })}</Badge>
          )}
          {suggestions.length > 0 && (
            <Badge variant="info">{t(suggestions.length === 1 ? "importer.candidate.suggestions.one" : "importer.candidate.suggestions.many", { count: suggestions.length })}</Badge>
          )}
          <Icon name="chevron-down" size={14} className="transition-transform group-open:rotate-180" />
        </span>
      </summary>
      <div className="border-t border-edge px-4 py-3">
        <dl className="grid grid-cols-1 gap-x-6 gap-y-1 text-small tablet:grid-cols-2">
          <div>
            <dt className="text-xs text-muted">{t("importer.candidate.origin")}</dt>
            <dd className="text-primary">{candidate.provenance.source_path}</dd>
          </div>
          {candidate.canonical_id && (
            <div data-testid={`canonical-id-${candidate.candidate_id}`}>
              <dt className="text-xs text-muted">{t("importer.candidate.canonicalId")}</dt>
              <dd className="break-words font-mono text-primary">
                {candidate.canonical_id}
              </dd>
            </div>
          )}
          {candidate.provenance.heading_path && (
            <div>
              <dt className="text-xs text-muted">{t("importer.candidate.originSection")}</dt>
              <dd className="text-primary">
                {candidate.provenance.heading_path}
              </dd>
            </div>
          )}
          {candidate.provenance.nearby_text_anchor && (
            <div>
              <dt className="text-xs text-muted">{t("importer.candidate.nearbyContext")}</dt>
              <dd className="truncate text-muted" title={candidate.provenance.nearby_text_anchor}>
                {candidate.provenance.nearby_text_anchor}
              </dd>
            </div>
          )}
          <div>
            <dt className="text-xs text-muted">{t("importer.candidate.size")}</dt>
            <dd className="text-primary">{formatBytes(candidate.size_bytes)}</dd>
          </div>
        </dl>

        {candidate.content_preview && (
          <div className="mt-3">
            <p className="text-xs text-muted">{t("importer.candidate.preview")}</p>
            <pre className="mt-1 max-h-40 overflow-y-auto whitespace-pre-wrap rounded-md border border-edge bg-surface p-3 text-xs text-muted">
              {candidate.content_preview}
            </pre>
          </div>
        )}

        {/* Importador-auto-frontmatter (Phase 4) — reviewed frontmatter, dense
            summary, and isolated media diagnostics. The frontmatter is the
            analysis output the author approves; the summary is the Step 2
            dense text; unresolved ``![][key]`` spans surface as non-blocking
            warnings (excluded from the gallery, never failing the ficha). */}
        {candidate.summary && (
          <div className="mt-3" data-testid={`summary-${candidate.candidate_id}`}>
            <p className="text-xs text-muted">{t("importer.candidate.summary")}</p>
            <p className="mt-1 text-xs text-primary">{candidate.summary}</p>
          </div>
        )}

        {candidate.frontmatter && (
          <div
            className="mt-3 rounded-md border border-edge bg-surface p-3"
            data-testid={`frontmatter-${candidate.candidate_id}`}
          >
            <p className="text-xs text-muted">{t("importer.candidate.frontmatter")}</p>
            <dl className="mt-2 grid grid-cols-1 gap-x-6 gap-y-1 text-small tablet:grid-cols-2">
              <div>
                <dt className="text-xs text-muted">{t("importer.candidate.title")}</dt>
                <dd className="text-primary">{candidate.frontmatter.title}</dd>
              </div>
              <div>
                <dt className="text-xs text-muted">{t("importer.candidate.type")}</dt>
                <dd className="text-primary">
                  {candidate.frontmatter.type || "—"}
                </dd>
              </div>
              {candidate.frontmatter.description && (
                <div className="tablet:col-span-2">
                  <dt className="text-xs text-muted">{t("importer.candidate.description")}</dt>
                  <dd className="text-primary">
                    {candidate.frontmatter.description}
                  </dd>
                </div>
              )}
              {candidate.frontmatter.relaciones.length > 0 && (
                <div className="tablet:col-span-2">
                  <dt className="text-xs text-muted">{t("importer.candidate.relations")}</dt>
                  <dd className="flex flex-wrap gap-1">
                    {candidate.frontmatter.relaciones.map((rel) => (
                      <span
                        key={rel}
                        className="rounded-full border border-edge bg-surface-raised px-2 py-0.5 font-mono text-xs text-primary"
                      >
                        {rel}
                      </span>
                    ))}
                  </dd>
                </div>
              )}
            </dl>
          </div>
        )}

        {candidate.media_diagnostics.length > 0 && (
          <div className="mt-3" data-testid={`media-diagnostics-${candidate.candidate_id}`}>
            <p className="text-xs text-muted">
              {t("importer.candidate.referencedImages")}{" "}
              {resolvedMediaCount > 0 && (
                <span className="text-status-success">
                  · {t(resolvedMediaCount === 1 ? "importer.candidate.resolved.one" : "importer.candidate.resolved.many", { count: resolvedMediaCount })}
                </span>
              )}
              {unresolvedMediaSpans.length > 0 && (
                <span className="text-action">
                  {" "}
                  · {t(unresolvedMediaSpans.length === 1 ? "importer.candidate.unresolvedCount.one" : "importer.candidate.unresolvedCount.many", { count: unresolvedMediaSpans.length })}
                </span>
              )}
            </p>
            <ul className="mt-2 flex flex-col gap-2">
              {candidate.media_diagnostics.map((diag) => (
                <li
                  key={diag.image_key}
                  className="rounded-md border border-edge bg-surface px-3 py-2"
                >
                  <span className="font-mono text-xs text-primary">
                    {diag.reference}
                  </span>
                  {diag.status === "unresolved" && (
                    <span className="ml-2 text-xs text-action">
                      {t("importer.candidate.noDefinition")}
                    </span>
                  )}
                  {diag.status === "resolved" && (
                    <span className="ml-2 text-xs text-status-success">
                      {diag.target_path}
                    </span>
                  )}
                </li>
              ))}
            </ul>
          </div>
        )}

        {hasIssues && (
          <div className="mt-3 rounded-md border border-action/40 bg-action/5 p-3">
            <p className="text-xs font-medium text-action">
              {t("importer.candidate.okfPending")}
            </p>
            <ul className="mt-1 list-disc pl-4 text-xs text-muted">
              {candidate.okf_issues.map((issue, index) => (
                <li key={index}>
                  {typeof issue.message === "string"
                    ? issue.message
                    : JSON.stringify(issue)}
                </li>
              ))}
            </ul>
          </div>
        )}

        {candidate.images.length > 0 && (
          <div className="mt-3">
            <p className="text-xs text-muted">
              {t("importer.candidate.imagesIntro")}
            </p>
            <ul className="mt-2 flex flex-col gap-2">
              {candidate.images.map((placement) => (
                <ImagePlacementRow
                  key={placement.gallery_asset_id}
                  placement={placement}
                  mundo={mundo}
                />
              ))}
            </ul>
          </div>
        )}

        {/* Slice 2 — advisory enrichment suggestions. Each card is an
            independent decision; visual distinction (border + badge) keeps
            suggested fields separate from the deterministic diagnosis. */}
        {textSuggestions.length > 0 && (
          <div className="mt-3" data-testid={`suggestions-${candidate.candidate_id}`}>
            <p className="text-xs text-muted">
              {t("importer.candidate.textSuggestionsIntro")}
            </p>
            <ul className="mt-2 flex flex-col gap-2">
              {textSuggestions.map((suggestion) => (
                <SuggestionCard
                  key={suggestion.id}
                  candidateId={candidate.candidate_id}
                  suggestion={suggestion}
                  decision={
                    suggestionDecisions.get(suggestion.id) ?? null
                  }
                  busy={decidingSuggestionId === suggestion.id}
                  onDecision={onSuggestionDecision}
                />
              ))}
            </ul>
          </div>
        )}

        {/* PR3+ — vision suggestions (media review). Advisory like the text
            family, but they approve/reject the IMAGE: approved originals are
            registered in the gallery at execute and the description becomes
            the markdown alt-text. Uses the same decisions endpoint + ID
            commitment as text suggestions. */}
        {visionSuggestions.length > 0 && (
          <div
            className="mt-3"
            data-testid={`vision-suggestions-${candidate.candidate_id}`}
          >
            <p className="text-xs text-muted">
              {t("importer.candidate.visionSuggestionsIntro")}
            </p>
            <ul className="mt-2 flex flex-col gap-2">
              {visionSuggestions.map((suggestion) => (
                <VisionSuggestionCard
                  key={suggestion.id}
                  candidateId={candidate.candidate_id}
                  suggestion={suggestion}
                  decision={suggestionDecisions.get(suggestion.id) ?? null}
                  busy={decidingSuggestionId === suggestion.id}
                  onDecision={onSuggestionDecision}
                />
              ))}
            </ul>
          </div>
        )}
      </div>
    </details>
  );
}

/** Slice 2 — visually distinct enrichment status banner. */
function EnrichmentStatusBanner({ status }: { status: EnrichmentStatus }) {
  const { t } = useAppLanguage();
  if (status === "disabled") return null;
  if (status === "ok") {
    return (
      <div
        className="mt-4 rounded-lg border border-status-success/40 bg-status-success/10 px-4 py-3 text-small text-primary"
        role="status"
        aria-live="polite"
        data-testid="enrichment-banner"
        data-enrichment-status="ok"
      >
        <Icon name="lightbulb" size={16} />
        <span className="ml-2 font-medium">
          {t("importer.enrich.ok.title")}
        </span>{" "}
        {t("importer.enrich.ok.body")}
      </div>
    );
  }
  if (status === "no_suggestions") {
    return (
      <div
        className="mt-4 rounded-lg border border-edge bg-surface px-4 py-3 text-small text-muted"
        role="status"
        aria-live="polite"
        data-testid="enrichment-banner"
        data-enrichment-status="no_suggestions"
      >
        <Icon name="lightbulb" size={16} />
        <span className="ml-2">{t("importer.enrich.none")}</span>
      </div>
    );
  }
  // error: gateway unavailable / timeout / malformed. Fail-open: analyze
  // already succeeded; the banner exists so reviewers know enrichment was
  // attempted but produced nothing.
  return (
    <div
      className="mt-4 rounded-lg border border-action/40 bg-action/5 px-4 py-3 text-small text-primary"
      role="status"
      aria-live="polite"
      data-testid="enrichment-banner"
      data-enrichment-status="error"
    >
      <Icon name="error" size={16} />
      <span className="ml-2 font-medium">
        {t("importer.enrich.error.title")}
      </span>{" "}
      {t("importer.enrich.error.body")}
    </div>
  );
}

/**
 * Human-readable target label for a relationship suggestion.
 *
 * Prefer the readable ``target_name`` over the internal ``target_candidate_id``
 * (a hex id that means nothing to a reviewer). Fall back to the id only when
 * the name is missing/blank, and to "?" when both are absent.
 */
function relationshipTargetLabel(rel: RelationshipSuggestion): string {
  const name = rel.target_name?.trim();
  if (name) return name;
  const id = rel.target_candidate_id?.trim();
  if (id) return id;
  return "?";
}

/**
 * Slice 2 — one advisory suggestion card. Visual distinction:
 * ``border-status-success/40 bg-status-success/5`` for classification, ``border-edge bg-surface``
 * for relationship. Approved/rejected states are persisted via the
 * decisions endpoint and reflected here from server truth.
 */
function SuggestionCard({
  candidateId,
  suggestion,
  decision,
  busy,
  onDecision,
}: {
  candidateId: string;
  suggestion: ImportSuggestion;
  decision: "approved" | "rejected" | null;
  busy: boolean;
  onDecision: (
    candidateId: string,
    suggestionId: string,
    decision: "approve" | "reject",
  ) => void;
}) {
  const { t } = useAppLanguage();
  const isClassification = suggestion.__type__ === "classification";
  const cls = isClassification ? (suggestion as ClassificationSuggestion) : null;
  const rel = !isClassification ? (suggestion as RelationshipSuggestion) : null;
  const confidencePct = Math.round(
    (isClassification ? cls!.confidence : rel!.confidence) * 100,
  );
  const providerLabel =
    (isClassification ? cls!.provenance : rel!.provenance)?.provider ??
    t("importer.provider.assistant");
  const modelLabel =
    (isClassification ? cls!.provenance : rel!.provenance)?.model ?? "";

  return (
    <li
      className={cn(
        "flex flex-col gap-2 rounded-md border p-3",
        isClassification
          ? "border-status-success/40 bg-status-success/5"
          : "border-edge bg-surface",
        decision === "approved" && "ring-1 ring-status-success/40",
        decision === "rejected" && "opacity-70",
      )}
      data-testid={`suggestion-${suggestion.id}`}
      data-suggestion-state={decision ?? "pending"}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant={isClassification ? "info" : "default"}>
            {isClassification ? t("importer.suggestion.kind.classification") : t("importer.suggestion.kind.relationship")}
          </Badge>
          <span className="text-small font-medium text-primary">
            {isClassification
              ? t("importer.suggestion.type", { type: cls!.type || t("importer.suggestion.noType") })
              : `${rel!.relationship_type} → ${relationshipTargetLabel(rel!)}`}
          </span>
          {isClassification && cls!.tags.length > 0 && (
            <span className="flex flex-wrap gap-1">
              {cls!.tags.map((tag) => (
                <Badge key={tag} variant="default">
                  #{tag}
                </Badge>
              ))}
            </span>
          )}
        </div>
        <span className="text-xs text-muted" title={t("importer.suggestion.confidenceTitle")}>
          {t("importer.suggestion.confidence", { pct: confidencePct })}
        </span>
      </div>
      {(isClassification ? cls!.evidence : rel!.evidence) && (
        isClassification ? (
          <p className="text-xs text-muted">{cls!.evidence}</p>
        ) : (
          <p className="text-sm font-medium text-primary">{rel!.evidence}</p>
        )
      )}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="text-xs text-muted">
          {t("importer.suggestion.origin", { provider: providerLabel })}
          {modelLabel && ` · ${modelLabel}`}
        </span>
        <div className="flex gap-2">
          <Button
            variant={decision === "approved" ? "primary" : "secondary"}
            size="sm"
            disabled={busy || decision === "approved"}
            onClick={() => onDecision(candidateId, suggestion.id, "approve")}
            aria-label={t("importer.suggestion.approveAria", { id: suggestion.id })}
            data-testid={`suggestion-approve-${suggestion.id}`}
          >
            <Icon name="check" size={14} />
            {t("importer.suggestion.approve")}
          </Button>
          <Button
            variant={decision === "rejected" ? "primary" : "ghost"}
            size="sm"
            disabled={busy || decision === "rejected"}
            onClick={() => onDecision(candidateId, suggestion.id, "reject")}
            aria-label={t("importer.suggestion.rejectAria", { id: suggestion.id })}
            data-testid={`suggestion-reject-${suggestion.id}`}
          >
            <Icon name="close" size={14} />
            {t("importer.suggestion.reject")}
          </Button>
        </div>
      </div>
      {decision === "rejected" && (
        <p className="text-xs text-muted">
          {t("importer.suggestion.rejected")}
        </p>
      )}
    </li>
  );
}

function ImagePlacementRow({
  placement,
  mundo,
}: {
  placement: ImportImagePlacement;
  mundo: string;
}) {
  const { t } = useAppLanguage();
  const ambiguous = placement.placement_status === "ambiguous";
  const markdown = `![${placement.alt_text || t("importer.image.altFallback")}](${placement.relative_media_path})`;
  const cleanPath = placement.relative_media_path.replace(
    /#(left|right|center|sm|lg)(?:-(sm|lg))?$/i,
    "",
  );

  // PR2 (docx-image-extraction): the DOCX position contract is additive and
  // optional — legacy/markdown placements simply omit these fields.
  const documentOrder = placement.document_order ?? 0;
  const anchorType = placement.anchor_type ?? "";
  const structuralPath = placement.structural_path ?? "";
  const headingPath = placement.heading_path ?? "";
  const contextText = placement.context_text ?? "";
  const warnings = placement.warnings ?? [];
  const anchorLabel =
    anchorType === "inline"
      ? t("importer.image.anchor.inline")
      : anchorType === "anchor"
        ? t("importer.image.anchor.block")
        : "";

  return (
    <li
      className={cn(
        "flex flex-col gap-2 rounded-md border p-3 tablet:flex-row tablet:items-start",
        ambiguous ? "border-action/50 bg-action/5" : "border-edge bg-surface",
      )}
    >
      <div className="shrink-0 overflow-hidden rounded-md border border-edge bg-surface-raised">
        <img
          src={getMediaUrl(mundo, cleanPath)}
          alt={placement.alt_text || placement.relative_media_path}
          className="h-16 w-24 object-cover"
        />
      </div>
      <div className="min-w-0 flex-1">
        <p className="text-xs text-primary">
          {placement.relative_media_path}
          {ambiguous && (
            <Badge variant="warning" className="ml-2">
              {t("importer.image.needsReview")}
            </Badge>
          )}
        </p>
        {(documentOrder > 0 || anchorLabel || structuralPath) && (
          <div className="mt-1 flex flex-wrap items-center gap-1.5 text-xs text-muted">
            {documentOrder > 0 && (
              <span aria-label={t("importer.image.sourceOrderAria", { order: documentOrder })}>
                #{documentOrder}
              </span>
            )}
            {anchorLabel && (
              <Badge variant={anchorType === "inline" ? "info" : "default"}>
                {anchorLabel}
              </Badge>
            )}
            {structuralPath && (
              <code className="rounded bg-surface-raised px-1.5 py-0.5 text-muted">
                {structuralPath}
              </code>
            )}
          </div>
        )}
        {headingPath && (
          <p className="mt-1 text-xs text-muted">
            {t("importer.image.section", { path: headingPath })}
          </p>
        )}
        {contextText && (
          <p className="mt-1 truncate text-xs text-muted" title={contextText}>
            {t("importer.image.context", { text: contextText })}
          </p>
        )}
        <p className="mt-1 text-xs text-muted">
          {placement.target_ficha
            ? t("importer.image.target", { target: placement.target_ficha })
            : t("importer.image.targetPending")}
        </p>
        {warnings.length > 0 && (
          <ul
            className="mt-2 flex flex-col gap-1 rounded-md border border-action/40 bg-action/5 p-2"
            aria-label={t("importer.image.warningsAria")}
          >
            {warnings.map((warning, index) => (
              <li key={index} className="text-xs text-action">
                {warning}
              </li>
            ))}
          </ul>
        )}
        <p className="mt-2 text-xs text-muted">{t("importer.image.markdownResult")}</p>
        <code className="mt-0.5 block overflow-x-auto rounded bg-surface px-2 py-1 text-xs text-muted">
          {markdown}
        </code>
        <div className="mt-2 max-w-sm">
          <MarkdownViewer content={markdown} mundo={mundo} />
        </div>
      </div>
    </li>
  );
}

function ResultPanel({
  job,
  outcomes,
  mundo,
  onResume,
  onRetryAnalyze,
  onRollback,
  onNewImport,
  onNavigateEditor,
}: {
  job: ImportJob | null;
  outcomes: ImportExecutionOutcome[];
  mundo: string;
  onResume: () => void;
  onRetryAnalyze: () => void;
  onRollback: () => void;
  onNewImport: () => void;
  onNavigateEditor: (target: string) => void;
}) {
  const { t } = useAppLanguage();
  if (!job) {
    return (
      <div className="col-span-full">
        <div className="rounded-lg border border-edge bg-surface-raised p-6">
          <p className="text-body text-muted">
            {t("importer.result.noState")}
          </p>
          <div className="mt-4">
            <Button variant="secondary" onClick={onNewImport}>
              {t("importer.result.newImport")}
            </Button>
          </div>
        </div>
      </div>
    );
  }

  const state = job.state;
  const success = state === "completed";
  const cancelled = state === "cancelled";
  const failed = state === "failed";
  const rolledBack = state === "rolled_back";

  const summary = outcomes.reduce(
    (acc, o) => {
      if (o.written && o.action === "add") acc.added += 1;
      else if (o.written && o.action === "replace") acc.replaced += 1;
      else if (o.action === "keep") acc.kept += 1;
      else if (o.action === "skip") acc.skipped += 1;
      else if (o.action === "review") acc.needsReview += 1;
      if (!o.written && o.action !== "keep" && o.action !== "skip") {
        acc.errors += 1;
      }
      return acc;
    },
    { added: 0, replaced: 0, kept: 0, skipped: 0, needsReview: 0, errors: 0 },
  );
  const papeleraEntries = outcomes.filter((o) => o.papelera_entry);

  return (
    <div className="col-span-full">
      <div
        className={cn(
          "rounded-lg border p-6",
          success ? "border-status-success/40 bg-status-success/10" : "border-edge bg-surface-raised",
        )}
      >
        <h2 className="font-heading text-h4 text-primary">
          {success && t("importer.result.completed")}
          {cancelled && t("importer.result.cancelled")}
          {failed && t("importer.result.failed")}
          {rolledBack && t("importer.result.rolledBack")}
          {!success && !cancelled && !failed && !rolledBack && t("importer.result.intermediate")}
        </h2>

        {success && (
          <div className="mt-3" role="status" aria-live="polite">
            <p className="text-body text-primary">
              {t("importer.result.completedBody", { mundo })}
            </p>
            {outcomes.length > 0 && (
              <ul className="mt-3 flex flex-wrap gap-2 text-small">
                {summary.added > 0 && (
                  <li className="rounded bg-surface px-2 py-1 text-primary">
                    {t("importer.result.added", { count: summary.added })}
                  </li>
                )}
                {summary.replaced > 0 && (
                  <li className="rounded bg-surface px-2 py-1 text-primary">
                    {t("importer.result.replaced", { count: summary.replaced })}
                  </li>
                )}
                {summary.kept > 0 && (
                  <li className="rounded bg-surface px-2 py-1 text-muted">
                    {t("importer.result.kept", { count: summary.kept })}
                  </li>
                )}
                {summary.skipped > 0 && (
                  <li className="rounded bg-surface px-2 py-1 text-muted">
                    {t("importer.result.skipped", { count: summary.skipped })}
                  </li>
                )}
              </ul>
            )}
            {papeleraEntries.length > 0 && (
              <p className="mt-3 text-small text-muted">
                {t("importer.result.trashNotice")}
              </p>
            )}
          </div>
        )}

        {cancelled && (
          <p className="mt-3 text-body text-muted" role="status">
            {t("importer.result.cancelledBody")}
          </p>
        )}

        {failed && (
          <div className="mt-3">
            <p className="text-body text-muted">
              {job.error || t("importer.error.analysisOrImportFailed")}
            </p>
          </div>
        )}

        {rolledBack && (
          <p className="mt-3 text-body text-muted" role="status">
            {t("importer.result.rolledBackBody")}
          </p>
        )}

        {!success && !cancelled && !failed && !rolledBack && (
          <p className="mt-3 text-body text-muted">
            {t("importer.result.intermediateBody", { state })}
          </p>
        )}
      </div>

      {outcomes.length > 0 && (
        <div className="mt-4">
          <h3 className="font-heading text-h4 text-primary">
            {t("importer.result.perItem")}
          </h3>
          <ul className="mt-2 flex flex-col gap-2">
            {outcomes.map((outcome) => (
              <li
                key={outcome.candidate_id}
                className="rounded-lg border border-edge bg-surface-raised px-4 py-3 text-small text-primary"
              >
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="min-w-0 truncate">
                    {outcome.target || outcome.candidate_id}
                  </span>
                  <span className="flex items-center gap-2">
                    <Badge
                      variant={
                        outcome.written || outcome.action === "keep" || outcome.action === "skip"
                          ? "info"
                          : "warning"
                      }
                    >
                      {outcome.action}
                    </Badge>
                    {outcome.papelera_entry && (
                      <Badge variant="info">{t("importer.result.trashBadge")}</Badge>
                    )}
                  </span>
                </div>
                {outcome.detail && (
                  <p className="mt-1 text-xs text-muted">
                    {outcome.detail}
                  </p>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}

      {summary.errors > 0 && (
        <div className="mt-4 rounded-lg border border-action/40 bg-action/5 p-4" role="alert">
          <p className="text-small text-primary">
            {t(summary.errors === 1 ? "importer.result.errors.one" : "importer.result.errors.many", { count: summary.errors })}
          </p>
        </div>
      )}

      <div className="mt-5 flex flex-wrap gap-2">
        {success && outcomes.filter((o) => o.written).length > 0 && (
          <Button
            variant="secondary"
            onClick={() => {
              const firstTarget = outcomes.find((o) => o.written && o.target)?.target;
              if (firstTarget) onNavigateEditor(firstTarget);
            }}
          >
            <Icon name="corner-up-right" size={16} />
            {t("importer.result.goEditor")}
          </Button>
        )}
        {cancelled && (
          <Button variant="secondary" onClick={onResume}>
            <Icon name="corner-up-right" size={16} />
            {t("importer.result.resumeReview")}
          </Button>
        )}
        {failed && (
          <Button variant="secondary" onClick={onRetryAnalyze}>
            <Icon name="corner-up-right" size={16} />
            {t("importer.retry")}
          </Button>
        )}
        {(success || rolledBack) && (
          <Button variant="ghost" onClick={onRollback} disabled={rolledBack}>
            <Icon name="history" size={16} />
            {rolledBack ? t("importer.result.alreadyRolledBack") : t("importer.result.rollback")}
          </Button>
        )}
        <Button variant="ghost" onClick={onNewImport}>
          {t("importer.result.newImport")}
        </Button>
      </div>
    </div>
  );
}