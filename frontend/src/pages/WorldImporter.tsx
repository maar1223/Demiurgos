import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useWorlds } from "@/hooks/useWorlds";
import { Navbar } from "@/components/organisms/Navbar";
import { WikiHomeLayout } from "@/components/templates/WikiHomeLayout";
import { Button } from "@/components/atoms/Button";
import { Icon } from "@/components/atoms/Icon";
import { Badge } from "@/components/atoms/Badge";
import { Spinner } from "@/components/atoms/Spinner";
import { ErrorBanner } from "@/components/organisms/ErrorBanner";
import { EmptyState } from "@/components/organisms/EmptyState";
import { MarkdownViewer } from "@/components/organisms/MarkdownViewer";
import { getMediaUrl } from "@/api/wiki";
import { ApiError } from "@/api/types";
import type {
  ClassificationSuggestion,
  EnrichmentStatus,
  ImportApprovalResponse,
  ImportCandidate,
  ImportExecutionOutcome,
  ImportImagePlacement,
  ImportJob,
  ImportSuggestion,
  ImportSourceKind,
  RelationshipSuggestion,
} from "@/api/types";
import {
  analyzeImportJob,
  approveImportGroups,
  cancelImportJob,
  createImportJob,
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
} from "@/api/importer";
import { VALID_SECTIONS } from "@/lib/constants";
import { getErrorMessage } from "@/lib/utils";
import { cn } from "@/lib/utils";

// ---------------------------------------------------------------------------
// World Importer — accessible, preservation-first import workflow (slice 3).
//
// Flow: select sources → analyze (read-only) → review + grouped approval →
// gated import → result. Write actions stay disabled until an explicit
// approval binds the reviewed diagnosis; the server is the authority for
// every state and the UI never implies success early.
// ---------------------------------------------------------------------------

type Step = "select" | "analyzing" | "review" | "result";

interface SelectedSource {
  file: File;
  relative: string;
  size: number;
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
function formatHistoryDate(iso: string): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString("es", {
    year: "numeric", month: "short", day: "2-digit",
    hour: "2-digit", minute: "2-digit",
  });
}

/** UI copy for import-job states (server enum, kept honest). */
function historyStateLabel(state: ImportJob["state"]): string {
  switch (state) {
    case "pending": return "pendiente";
    case "intaking": return "subiendo";
    case "analyzing": return "analizando";
    case "review": return "en revisión";
    case "approved": return "aprobado";
    case "executing": return "ejecutando";
    case "completed": return "completado";
    case "cancelled": return "cancelado";
    case "failed": return "falló";
    case "rolled_back": return "revertido";
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
function importErrorMessage(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 401) {
      return "Tu sesión local venció. Iniciá sesión e intentá de nuevo.";
    }
    if (err.status === 0) {
      return "No se pudo conectar al servidor. Verificá que esté corriendo.";
    }
    return getErrorMessage(err.status, err.detail) ?? "Error de importación";
  }
  return err instanceof Error ? err.message : "Error de importación";
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

export default function WorldImporter() {
  const navigate = useNavigate();
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

  const [candidates, setCandidates] = useState<ImportCandidate[]>([]);
  // The review digest is never displayed; the approval response carries the
  // digest bound to execution (approval.digest).
  const [approval, setApproval] = useState<ImportApprovalResponse | null>(null);
  const [selectedGroups, setSelectedGroups] = useState<Set<string>>(new Set());
  const [outcomes, setOutcomes] = useState<ImportExecutionOutcome[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [resumeNotice, setResumeNotice] = useState<string | null>(null);
  const [restoring, setRestoring] = useState(true);

  // Slice 2 — optional Hermes advisory enrichment. The toggle lives on the
  // select step; analyze carries the opt-in flag. Suggestions are
  // NON-AUTHORITATIVE: the reviewer toggles each one via the decisions
  // endpoint; approved IDs are bound to the approval token.
  const [enrichEnabled, setEnrichEnabled] = useState(false);
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

  const fileInputRef = useRef<HTMLInputElement>(null);
  const headingRef = useRef<HTMLHeadingElement>(null);

  const worldExists = worlds.some((w) => w.name === mundo);

  // --- persisted job recovery (cancel/resume across reloads) ------------

  const persistJob = useCallback(
    (id: string, kind: ImportSourceKind) => {
      if (!mundo) return;
      try {
        sessionStorage.setItem(
          storageKey(mundo),
          JSON.stringify({ jobId: id, sourceKind: kind }),
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
      if (existing.state === "review" || existing.state === "approved") {
        try {
          const review = await getImportReview(mundo, existing.job_id);
          setCandidates(review.candidates);
          setStep("review");
        } catch (err) {
          setError(importErrorMessage(err));
          setStep("result");
        }
      } else if (
        existing.state === "pending" ||
        existing.state === "intaking" ||
        existing.state === "analyzing" ||
        existing.state === "executing"
      ) {
        setStep("select");
        setResumeNotice(
          "Hay una importación interrumpida. Seleccioná las mismas fuentes y continuá: los archivos ya subidos se retoman sin duplicarse.",
        );
      } else {
        // Terminal: completed / failed / cancelled / rolled_back.
        setOutcomes([]);
        setStep("result");
        // Terminal jobs must not keep prompting recovery on every reload.
        clearPersistedJob();
      }
    },
    [mundo, clearPersistedJob],
  );

  useEffect(() => {
    if (!mundo || worldsLoading) {
      return;
    }
    if (!worldExists) {
      setRestoring(false);
      return;
    }
    let stored: { jobId: string; sourceKind: ImportSourceKind } | null = null;
    try {
      stored = JSON.parse(sessionStorage.getItem(storageKey(mundo)) ?? "null");
    } catch {
      stored = null;
    }
    if (!stored?.jobId) {
      setRestoring(false);
      return;
    }
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
          setError("La importación guardada ya no existe en el servidor.");
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
  }, [mundo, worldsLoading, worldExists, restoreJobState, clearPersistedJob]);

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
      persistJob(entry.job_id, entry.source_kind);
      await restoreJobState(entry);
    },
    [mundo, persistJob, restoreJobState],
  );

  // --- focus management: the step heading receives focus on transitions ---
  useEffect(() => {
    headingRef.current?.focus();
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
    setAnalyzing(false);
    setImporting(false);
    setEnrichmentStatus("disabled");
    setSuggestionDecisions(new Map());
    setApprovedSuggestionIds([]);
    setDecidingSuggestionId(null);
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

  const handleFilesChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    const list = Array.from(event.target.files ?? []);
    if (list.length === 0) return;
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
      selected.push({ file, relative, size: file.size });
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
        `"${oversized.relative}" supera el límite de 500 MB por archivo.`,
      );
    } else if (aggregate > IMPORT_MAX_JOB_BYTES) {
      setPrecheckError(
        "La selección supera el límite de 5 GB por importación.",
      );
    } else {
      setPrecheckError(null);
    }
    // Reset the input value so re-selecting the same files fires change again.
    event.target.value = "";
  };

  const openPicker = () => fileInputRef.current?.click();

  // --- analyze (read-only) ------------------------------------------------

  const handleAnalyze = async () => {
    if (!mundo || sources.length === 0 || precheckError) return;
    setAnalyzing(true);
    setError(null);
    setResumeNotice(null);
    setPhaseMessage("Preparando análisis…");
    setStep("analyzing");
    setStreamProgress(null);
    // Slice 2 — reset advisory state for a fresh analyze. Suggestions live
    // on the candidate row, so a re-analyze supersedes the prior list.
    setEnrichmentStatus("disabled");
    setSuggestionDecisions(new Map());
    setApprovedSuggestionIds([]);
    setDecidingSuggestionId(null);
    try {
      const { job: created } = await createImportJob(mundo, {
        source_kind: sourceKind,
        files: sources.map((s) => s.relative),
      });
      setJobId(created.job_id);
      setJob(created);
      persistJob(created.job_id, sourceKind);

      // Stream every file as durable chunks (idempotent at same offsets).
      const count = sources.length;
      for (let i = 0; i < count; i += 1) {
        const source = sources[i];
        setPhaseMessage(
          `Subiendo ${source.relative} (${i + 1} de ${count})…`,
        );
        await streamImportFile(mundo, created.job_id, source.file, source.relative, (streamed, total) => {
          setStreamProgress({ fileIndex: i, fileCount: count, streamed, total });
        });
      }
      setStreamProgress(null);
      setPhaseMessage(
        enrichEnabled
          ? "Analizando contenido y consultando asistente (solo lectura)…"
          : "Analizando contenido (solo lectura)…",
      );
      // Slice 2 — opt-in is a single boolean; absent body preserves the
      // legacy deterministic analyze contract (no Hermes call). The server
      // also treats the absent body as the default ``enrich: false``.
      const analysis = enrichEnabled
        ? await analyzeImportJob(mundo, created.job_id, { enrich: true })
        : await analyzeImportJob(mundo, created.job_id);
      setJob(analysis.job);
      // Slice 2 — server-attributed enrichment status is batch-level; the
      // fail-open contract guarantees non-blocking even when the gateway
      // is unavailable (status === "error").
      if (analysis.enrichment_status) {
        setEnrichmentStatus(analysis.enrichment_status);
      }
      if (analysis.job.state === "failed") {
        setStep("result");
        setError(
          analysis.job.error || "El análisis falló y la importación quedó bloqueada.",
        );
        return;
      }
      const review = await getImportReview(mundo, created.job_id);
      setCandidates(review.candidates);
      setJob(review.job);
      // Review surfaces a server-rolled-up status; prefer it if the analyze
      // response was missing it (legacy callers or race with the lease).
      setEnrichmentStatus(review.enrichment_status ?? analysis.enrichment_status ?? "disabled");
      setStep("review");
    } catch (err) {
      setError(importErrorMessage(err));
      setPhaseMessage("");
      setStep("result");
    } finally {
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
            "La importación se reabrió. Seleccioná las fuentes y continuá.",
          );
        }
      } catch (err) {
        setError(importErrorMessage(err));
      }
      return;
    }
    if (sources.length === 0) {
      setStep("select");
      setResumeNotice(
        "Seleccioná las mismas fuentes y continuá: los archivos ya subidos se retoman sin duplicarse.",
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
      setError(importErrorMessage(err));
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
        label: "Contenido de fichas",
        description:
          "Se crearán o actualizarán fichas sin reemplazar tu contenido actual.",
        count: fichas.length,
      },
      {
        id: "imagenes",
        label: "Imágenes contextuales",
        description:
          "Se registran en la galería y se insertan en la sección correspondiente.",
        count: imagePlacements.length,
      },
    ];
    // Candidates needing review count once — ambiguous image placements are
    // part of their candidate's review, never double-counted.
    const reviewCount = revisar.length;
    if (reviewCount > 0) {
      result.push({
        id: "revisar",
        label: "Requiere tu decisión",
        description:
          "Ítems con validación o ubicación ambigua. No se importan automáticamente: revisalos y decidí si los incluís.",
        count: reviewCount,
        requiresReview: true,
      });
    }
    return { groups: result, rejected };
  }, [candidates]);

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
      setError(importErrorMessage(err));
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
      setError(importErrorMessage(err));
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
    setPhaseMessage("Importando contenido…");
    // The step stays "review" — the importing progress panel renders there.
    try {
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
      setError(importErrorMessage(err));
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
          "Seleccioná las mismas fuentes y continuá: los archivos ya subidos se retoman sin duplicarse.",
        );
      }
    } catch (err) {
      setError(importErrorMessage(err));
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
      setError(importErrorMessage(err));
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
      ? "Importar contenido"
      : step === "analyzing"
        ? "Analizando fuentes"
        : step === "review"
          ? "Revisión e aprobación"
          : "Resultado de la importación";

  const folderAttrs: FolderInputAttrs = { webkitdirectory: "", directory: "" };

  return (
    <WikiHomeLayout header={<Navbar worlds={worlds} currentWorld={mundo} />}>
      <div className="col-span-full">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h1
            ref={headingRef}
            tabIndex={-1}
            className="font-heading text-h3 text-pergamino focus:outline-none"
          >
            {headingText}
          </h1>
          {mundo && (
            <Badge variant="info">
              Mundo: {mundo}
            </Badge>
          )}
        </div>

        {/* Preservation-first messaging — shown from the start */}
        <div className="mt-3 rounded-lg border border-musgo/40 bg-musgo/10 px-4 py-3 text-small text-pergamino">
          <span className="font-medium">Tu contenido actual nunca se reemplaza sin tu aprobación explícita.</span>{" "}
          Las fichas editadas se conservan; se agregan solo las imágenes y
          referencias faltantes. Los reemplazos autorizados guardan la versión
          anterior 30 días en la papelera.
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
            message="No existe un mundo con ese nombre."
            actionLabel="Ir al inicio"
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
              className="mb-4 rounded-lg border border-llamita/40 bg-llamita/10 px-4 py-3 text-small text-pergamino"
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
            className="mt-4 rounded-lg border border-filio bg-madero p-4"
            data-testid="import-history"
          >
            <header className="flex flex-wrap items-center justify-between gap-2">
              <h2
                id="import-history-title"
                className="font-heading text-body text-pergamino"
              >
                Importaciones previas
              </h2>
              {historyOutage && (
                <span
                  className="flex items-center gap-2 text-small text-tinta-desvaida"
                  role="status"
                  aria-live="polite"
                  data-testid="history-outage"
                >
                  Datos en caché — el servidor no responde.
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => void loadHistory(null)}
                    disabled={historyLoading}
                  >
                    <Icon name="refresh" size={14} />
                    Reintentar
                  </Button>
                </span>
              )}
            </header>

            {historyLoading && history.length === 0 && (
              <div className="mt-3 flex items-center gap-2 text-small text-tinta-desvaida">
                <Spinner size="sm" />
                <span>Cargando historial…</span>
              </div>
            )}

            {!historyLoading && history.length === 0 && !historyOutage && (
              <p
                className="mt-3 text-small text-tinta-desvaida"
                data-testid="history-empty"
              >
                No hay importaciones previas en este mundo.
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
                    className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-filio bg-cripta px-3 py-2"
                  >
                    <div className="min-w-0 flex-1">
                      <p className="text-small font-medium text-pergamino">
                        {formatHistoryDate(entry.created_at)}{" "}
                        <Badge
                          variant={historyStateVariant(entry.state)}
                          className="ml-1"
                        >
                          {historyStateLabel(entry.state)}
                        </Badge>
                      </p>
                      <p className="mt-0.5 text-xs text-tinta-desvaida">
                        {entry.source_kind} · {entry.file_count}{" "}
                        {entry.file_count === 1 ? "candidato" : "candidatos"}
                      </p>
                    </div>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => void handleOpenFromHistory(entry)}
                      data-testid={`history-open-${entry.job_id}`}
                    >
                      <Icon name="corner-up-right" size={14} />
                      Abrir
                    </Button>
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
                  {historyLoading ? "Cargando…" : "Cargar más"}
                </Button>
              </div>
            )}
          </section>

          <fieldset className="mt-4 rounded-lg border border-filio bg-madero p-4">
            <legend className="px-2 text-small font-medium text-tinta-desvaida">
              Tipo de fuente
            </legend>
            <div className="flex flex-wrap gap-2">
              {(
                [
                  { kind: "folder", label: "Carpeta", hint: "Todo su contenido" },
                  { kind: "loose", label: "Archivos", hint: "Selección múltiple" },
                  { kind: "zip", label: "Paquete .zip", hint: "Opcional" },
                ] as { kind: ImportSourceKind; label: string; hint: string }[]
              ).map((option) => (
                <button
                  key={option.kind}
                  type="button"
                  aria-pressed={sourceKind === option.kind}
                  onClick={() => handleSourceKind(option.kind)}
                  className={cn(
                    "flex flex-col gap-0.5 rounded-lg border px-4 py-2 text-left text-small transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-llamita/50",
                    sourceKind === option.kind
                      ? "border-llamita bg-llamita/10 text-pergamino"
                      : "border-filio bg-cripta text-tinta-desvaida hover:border-llamita/40",
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
                ? "Seleccionar carpeta"
                : sourceKind === "zip"
                  ? "Seleccionar paquete .zip"
                  : "Seleccionar archivos"}
            </Button>
            <input
              ref={fileInputRef}
              type="file"
              className="sr-only"
              multiple={sourceKind !== "zip"}
              accept={sourceKind === "zip" ? ".zip" : undefined}
              {...(sourceKind === "folder" ? folderAttrs : {})}
              onChange={handleFilesChange}
              aria-label="Selección de fuentes"
            />
          </div>

          {excludedCount > 0 && (
            <p className="mt-3 text-small text-tinta-desvaida">
              {excludedCount}{" "}
              {excludedCount === 1 ? "archivo" : "archivos"} de carpetas del
              sistema u ocultas se excluyeron (no son contenido importable).
            </p>
          )}

          {precheckError && (
            <p className="mt-3 text-small text-sangre" role="alert">
              {precheckError}
            </p>
          )}

          {sources.length > 0 && (
            <ul className="mt-4 max-h-64 divide-y divide-filio overflow-y-auto rounded-lg border border-filio bg-cripta">
              {sources.map((s) => (
                <li
                  key={s.relative}
                  className="flex items-center justify-between gap-3 px-3 py-2 text-small text-pergamino"
                >
                  <span className="min-w-0 truncate" title={s.relative}>
                    {s.relative}
                  </span>
                  <span className="shrink-0 text-xs text-tinta-desvaida">
                    {formatBytes(s.size)}
                  </span>
                </li>
              ))}
            </ul>
          )}

          <div className="mt-5 flex flex-wrap items-center gap-3">
            <Button
              variant="secondary"
              onClick={handleAnalyze}
              disabled={sources.length === 0 || Boolean(precheckError) || analyzing}
            >
              <Icon name="search" size={16} />
              Analizar (solo lectura)
            </Button>
            {sources.length > 0 && (
              <span className="text-small text-tinta-desvaida">
                {sources.length}{" "}
                {sources.length === 1 ? "archivo" : "archivos"} ·{" "}
                {formatBytes(sources.reduce((sum, s) => sum + s.size, 0))}
              </span>
            )}
          </div>

          {/* Slice 2 — optional Hermes advisory enrichment opt-in. The
              reviewer stays in control: suggestions never mutate the
              deterministic diagnosis and only materialize on a gated
              execute when the author approves them. */}
          <label
            className="mt-4 flex cursor-pointer items-start gap-3 rounded-lg border border-filio bg-cripta p-3 focus-within:ring-2 focus-within:ring-llamita/50"
            data-testid="enrich-toggle"
          >
            <input
              type="checkbox"
              className="mt-0.5 h-4 w-4 accent-llamita"
              checked={enrichEnabled}
              onChange={(e) => setEnrichEnabled(e.target.checked)}
              aria-describedby="enrich-toggle-desc"
            />
            <span>
              <span className="block text-small font-medium text-pergamino">
                Pedirle al asistente sugerencias de clasificación y relaciones
              </span>
              <span
                id="enrich-toggle-desc"
                className="block text-xs text-tinta-desvaida"
              >
                Opcional. Las sugerencias son orientativas y requieren tu
                aprobación individual antes de aplicarse. Si el asistente no
                responde, el análisis sigue siendo válido y se omite el
                enriquecimiento.
              </span>
            </span>
          </label>
        </div>
      )}

      {!worldsLoading && !restoring && mundo && worldExists && step === "analyzing" && (
        <div className="col-span-full">
          <div className="rounded-lg border border-filio bg-madero p-6">
            <div className="flex items-center gap-3">
              <Spinner size="md" />
              <div role="status" aria-live="polite">
                <p className="text-body text-pergamino">{phaseMessage}</p>
                {streamProgress && (
                  <p className="mt-1 text-small text-tinta-desvaida">
                    {formatBytes(streamProgress.streamed)} de{" "}
                    {formatBytes(streamProgress.total)} · archivo{" "}
                    {streamProgress.fileIndex + 1} de{" "}
                    {streamProgress.fileCount}
                  </p>
                )}
              </div>
            </div>
            {streamProgress && streamProgress.total > 0 && (
              <div
                className="mt-4 h-1.5 w-full overflow-hidden rounded-full bg-filio"
                role="progressbar"
                aria-valuemin={0}
                aria-valuemax={streamProgress.total}
                aria-valuenow={streamProgress.streamed}
                aria-label="Progreso de subida"
              >
                <div
                  className="h-full bg-llamita transition-all"
                  style={{
                    width: `${Math.round(
                      (streamProgress.streamed / streamProgress.total) * 100,
                    )}%`,
                  }}
                />
              </div>
            )}
            <div className="mt-5">
              <Button variant="ghost" onClick={handleCancel}>
                <Icon name="stop" size={16} />
                Cancelar análisis
              </Button>
            </div>
          </div>
        </div>
      )}

      {!worldsLoading && !restoring && mundo && worldExists && step === "review" && (
        <div className="col-span-full">
          <p className="text-body text-tinta-desvaida">
            El análisis es de solo lectura. Elegí qué aprobar y luego confirmá
            la importación: escribir es una acción explícita y separada.
          </p>

          {/* Slice 2 — enrichment status banner. Mirrors the server-attributed
              state so reviewers never see a different answer than the audit
              log. "disabled" hides the banner entirely to keep the legacy
              copy clean. */}
          <EnrichmentStatusBanner status={enrichmentStatus} />

          {/* Impact summary */}
          <div className="mt-4 grid grid-cols-1 gap-3 tablet:grid-cols-3">
            <SummaryTile
              label="Candidatos"
              value={String(candidates.length)}
            />
            <SummaryTile
              label="Imágenes contextuales"
              value={String(
                candidates.flatMap((c) => c.images).filter((i) => i.placement_status !== "skip").length,
              )}
            />
            <SummaryTile
              label="Requieren decisión"
              value={String(groups.groups.find((g) => g.id === "revisar")?.count ?? 0)}
            />
          </div>

          {candidates.length === 0 && (
            <div className="mt-6">
              <EmptyState
                icon="empty"
                message="El análisis no encontró contenido analizable en las fuentes seleccionadas."
              />
              <div className="mt-4">
                <Button variant="secondary" onClick={handleChangeSources}>
                  <Icon name="chevron-left" size={16} />
                  Cambiar fuentes
                </Button>
              </div>
            </div>
          )}

          {/* Grouped approval */}
          {candidates.length > 0 && (
            <>
              <fieldset className="mt-6 rounded-lg border border-filio bg-madero p-4">
                <legend className="px-2 text-small font-medium text-tinta-desvaida">
                  Grupos de aprobación
                </legend>
                <div className="flex flex-col gap-3">
                  {groups.groups.map((group) => (
                    <label
                      key={group.id}
                      className={cn(
                        "flex cursor-pointer items-start gap-3 rounded-lg border p-3 transition-colors focus-within:ring-2 focus-within:ring-llamita/50",
                        group.requiresReview
                          ? "border-llamita/40 bg-llamita/5"
                          : "border-filio bg-cripta",
                      )}
                    >
                      <input
                        type="checkbox"
                        className="mt-0.5 h-4 w-4 accent-llamita"
                        checked={selectedGroups.has(group.id)}
                        onChange={() => toggleGroup(group.id)}
                        aria-describedby={`group-${group.id}-desc`}
                      />
                      <span>
                        <span className="block text-small font-medium text-pergamino">
                          {group.label} ({group.count})
                          {group.requiresReview && (
                            <Badge variant="warning" className="ml-2">
                              revisión
                            </Badge>
                          )}
                        </span>
                        <span
                          id={`group-${group.id}-desc`}
                          className="block text-xs text-tinta-desvaida"
                        >
                          {group.description}
                        </span>
                      </span>
                    </label>
                  ))}
                  {groups.rejected.length > 0 && (
                    <p className="text-small text-tinta-desvaida">
                      {groups.rejected.length}{" "}
                      {groups.rejected.length === 1
                        ? "candidato descartado"
                        : "candidatos descartados"}{" "}
                      por validación — no se pueden aprobar.
                    </p>
                  )}
                </div>
              </fieldset>

              {/* Candidate detail review (expandable) */}
              <h2 className="mt-6 font-heading text-h4 text-pergamino">
                Detalle de candidatos
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
              <div className="mt-6 rounded-lg border border-filio bg-madero p-4">
                {!approval ? (
                  <>
                    <p className="text-small text-tinta-desvaida">
                      La aprobación se liga al diagnóstico completo revisado.
                      Cualquier cambio en las fuentes la invalida.
                    </p>
                    {approvedSuggestionIds.length > 0 && (
                      <p
                        className="mt-2 text-small text-pergamino"
                        data-testid="approved-suggestions-summary"
                      >
                        <Icon name="lightbulb" size={14} />
                        <span className="ml-2">
                          {approvedSuggestionIds.length}{" "}
                          sugerencia{approvedSuggestionIds.length === 1 ? "" : "s"}{" "}
                          aprobada{approvedSuggestionIds.length === 1 ? "" : "s"} se
                          aplicarán al importar.
                        </span>
                      </p>
                    )}
                    <div className="mt-3">
                      <Button
                        variant="secondary"
                        onClick={handleApprove}
                        disabled={!canApprove}
                      >
                        Aprobar grupos seleccionados
                      </Button>
                    </div>
                  </>
                ) : (
                  <>
                    <p className="text-small text-pergamino" role="status">
                      <Icon name="check" size={16} />
                      <span className="ml-2">
                        Aprobaste {selectedGroupIds.length}{" "}
                        {selectedGroupIds.length === 1 ? "grupo" : "grupos"}.
                      </span>
                    </p>
                    <p className="mt-2 text-small text-tinta-desvaida">
                      La importación escribirá en tu mundo. Las versiones
                      anteriores de fichas reemplazadas quedan en la papelera
                      30 días.
                    </p>
                    <div className="mt-3 flex flex-wrap gap-2">
                      <Button
                        variant="primary"
                        onClick={handleExecute}
                        disabled={!canImport}
                        aria-describedby="import-write-warning"
                      >
                        <Icon name="save" size={16} />
                        Importar
                      </Button>
                      <Button
                        variant="ghost"
                        onClick={() => setApproval(null)}
                        disabled={importing}
                      >
                        Cambiar selección
                      </Button>
                    </div>
                    <p
                      id="import-write-warning"
                      className="mt-2 text-xs text-tinta-desvaida"
                    >
                      Esta acción es permanente: crea o actualiza fichas en tu
                      mundo y registra imágenes en la galería.
                    </p>
                  </>
                )}
              </div>

              <div className="mt-4">
                <Button variant="ghost" onClick={handleChangeSources}>
                  <Icon name="chevron-left" size={16} />
                  Cambiar fuentes
                </Button>
              </div>
            </>
          )}

          {importing && (
            <div className="mt-4 rounded-lg border border-filio bg-madero p-4" role="status" aria-live="polite">
              <div className="flex items-center gap-3">
                <Spinner size="md" />
                <span className="text-body text-pergamino">
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
    </WikiHomeLayout>
  );
}

// ---------------------------------------------------------------------------
// Small presentational pieces
// ---------------------------------------------------------------------------

function SummaryTile({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-filio bg-madero p-4">
      <p className="text-xs uppercase tracking-wide text-tinta-desvaida">
        {label}
      </p>
      <p className="mt-1 font-heading text-h4 text-pergamino">{value}</p>
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
  const ambiguousImages = candidate.images.filter(
    (i) => i.placement_status === "ambiguous",
  );
  const hasIssues = candidate.okf_issues.length > 0;
  const suggestions = candidate.enrichment_json ?? [];

  return (
    <details className="group rounded-lg border border-filio bg-madero">
      <summary className="flex cursor-pointer flex-wrap items-center justify-between gap-2 px-4 py-3 text-small font-medium text-pergamino focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-llamita/50 [&::-webkit-details-marker]:hidden">
        <span className="min-w-0 truncate">
          {candidate.normalized_identity}
          <span className="ml-2 text-xs font-normal text-tinta-desvaida">
            {candidate.provenance.source_path}
          </span>
        </span>
        <span className="flex items-center gap-2">
          {hasIssues && <Badge variant="warning">validación</Badge>}
          {ambiguousImages.length > 0 && (
            <Badge variant="warning">ubicación ambigua</Badge>
          )}
          {candidate.images.length > 0 && candidate.images.length - ambiguousImages.length > 0 && (
            <Badge variant="info">{candidate.images.length} img</Badge>
          )}
          {suggestions.length > 0 && (
            <Badge variant="info">{suggestions.length} sugerencia{suggestions.length === 1 ? "" : "s"}</Badge>
          )}
          <Icon name="chevron-down" size={14} className="transition-transform group-open:rotate-180" />
        </span>
      </summary>
      <div className="border-t border-filio px-4 py-3">
        <dl className="grid grid-cols-1 gap-x-6 gap-y-1 text-small tablet:grid-cols-2">
          <div>
            <dt className="text-xs text-tinta-desvaida">Origen</dt>
            <dd className="text-pergamino">{candidate.provenance.source_path}</dd>
          </div>
          {candidate.provenance.heading_path && (
            <div>
              <dt className="text-xs text-tinta-desvaida">Sección de origen</dt>
              <dd className="text-pergamino">
                {candidate.provenance.heading_path}
              </dd>
            </div>
          )}
          {candidate.provenance.nearby_text_anchor && (
            <div>
              <dt className="text-xs text-tinta-desvaida">Contexto cercano</dt>
              <dd className="truncate text-tinta-desvaida" title={candidate.provenance.nearby_text_anchor}>
                {candidate.provenance.nearby_text_anchor}
              </dd>
            </div>
          )}
          <div>
            <dt className="text-xs text-tinta-desvaida">Tamaño</dt>
            <dd className="text-pergamino">{formatBytes(candidate.size_bytes)}</dd>
          </div>
        </dl>

        {candidate.content_preview && (
          <div className="mt-3">
            <p className="text-xs text-tinta-desvaida">Vista previa</p>
            <pre className="mt-1 max-h-40 overflow-y-auto whitespace-pre-wrap rounded-md border border-filio bg-cripta p-3 text-xs text-tinta-desvaida">
              {candidate.content_preview}
            </pre>
          </div>
        )}

        {hasIssues && (
          <div className="mt-3 rounded-md border border-llamita/40 bg-llamita/5 p-3">
            <p className="text-xs font-medium text-llamita">
              Validación OKF pendiente
            </p>
            <ul className="mt-1 list-disc pl-4 text-xs text-tinta-desvaida">
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
            <p className="text-xs text-tinta-desvaida">
              Imágenes contextuales — se insertan en la sección correspondiente,
              en orden de origen, sin reordenar lo existente.
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
        {suggestions.length > 0 && (
          <div className="mt-3" data-testid={`suggestions-${candidate.candidate_id}`}>
            <p className="text-xs text-tinta-desvaida">
              Sugerencias del asistente — son orientativas. Aprobá o rechazá
              cada una antes de importar.
            </p>
            <ul className="mt-2 flex flex-col gap-2">
              {suggestions.map((suggestion) => (
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
      </div>
    </details>
  );
}

/** Slice 2 — visually distinct enrichment status banner. */
function EnrichmentStatusBanner({ status }: { status: EnrichmentStatus }) {
  if (status === "disabled") return null;
  if (status === "ok") {
    return (
      <div
        className="mt-4 rounded-lg border border-musgo/40 bg-musgo/10 px-4 py-3 text-small text-pergamino"
        role="status"
        aria-live="polite"
        data-testid="enrichment-banner"
        data-enrichment-status="ok"
      >
        <Icon name="lightbulb" size={16} />
        <span className="ml-2 font-medium">
          Asistente: sugerencias listas para revisar.
        </span>{" "}
        Cada sugerencia requiere tu aprobación antes de aplicarse.
      </div>
    );
  }
  if (status === "no_suggestions") {
    return (
      <div
        className="mt-4 rounded-lg border border-filio bg-cripta px-4 py-3 text-small text-tinta-desvaida"
        role="status"
        aria-live="polite"
        data-testid="enrichment-banner"
        data-enrichment-status="no_suggestions"
      >
        <Icon name="lightbulb" size={16} />
        <span className="ml-2">
          El asistente respondió pero no produjo sugerencias aplicables.
          La importación sigue siendo válida sin cambios.
        </span>
      </div>
    );
  }
  // error: gateway unavailable / timeout / malformed. Fail-open: analyze
  // already succeeded; the banner exists so reviewers know enrichment was
  // attempted but produced nothing.
  return (
    <div
      className="mt-4 rounded-lg border border-llamita/40 bg-llamita/5 px-4 py-3 text-small text-pergamino"
      role="status"
      aria-live="polite"
      data-testid="enrichment-banner"
      data-enrichment-status="error"
    >
      <Icon name="error" size={16} />
      <span className="ml-2 font-medium">
        El asistente no respondió.
      </span>{" "}
      El análisis sigue siendo válido: se omitió el enriquecimiento para no
      bloquear la importación.
    </div>
  );
}

/**
 * Slice 2 — one advisory suggestion card. Visual distinction:
 * ``border-musgo/40 bg-musgo/5`` for classification, ``border-filio bg-cripta``
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
  const isClassification = suggestion.__type__ === "classification";
  const cls = isClassification ? (suggestion as ClassificationSuggestion) : null;
  const rel = !isClassification ? (suggestion as RelationshipSuggestion) : null;
  const confidencePct = Math.round(
    (isClassification ? cls!.confidence : rel!.confidence) * 100,
  );
  const providerLabel =
    (isClassification ? cls!.provenance : rel!.provenance)?.provider ??
    "asistente";
  const modelLabel =
    (isClassification ? cls!.provenance : rel!.provenance)?.model ?? "";

  return (
    <li
      className={cn(
        "flex flex-col gap-2 rounded-md border p-3",
        isClassification
          ? "border-musgo/40 bg-musgo/5"
          : "border-filio bg-cripta",
        decision === "approved" && "ring-1 ring-musgo/40",
        decision === "rejected" && "opacity-70",
      )}
      data-testid={`suggestion-${suggestion.id}`}
      data-suggestion-state={decision ?? "pending"}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant={isClassification ? "info" : "default"}>
            {isClassification ? "clasificación" : "relación"}
          </Badge>
          <span className="text-small font-medium text-pergamino">
            {isClassification
              ? `tipo: ${cls!.type || "(sin tipo)"}`
              : `${rel!.relationship_type} → ${
                  rel!.target_candidate_id ?? rel!.target_name ?? "?"
                }`}
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
        <span className="text-xs text-tinta-desvaida" title="confianza del asistente">
          confianza {confidencePct}%
        </span>
      </div>
      {(isClassification ? cls!.evidence : rel!.evidence) && (
        <p className="text-xs text-tinta-desvaida">
          {(isClassification ? cls!.evidence : rel!.evidence)}
        </p>
      )}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="text-xs text-tinta-desvaida">
          Origen: {providerLabel}
          {modelLabel && ` · ${modelLabel}`}
        </span>
        <div className="flex gap-2">
          <Button
            variant={decision === "approved" ? "primary" : "secondary"}
            size="sm"
            disabled={busy || decision === "approved"}
            onClick={() => onDecision(candidateId, suggestion.id, "approve")}
            aria-label={`Aprobar sugerencia ${suggestion.id}`}
            data-testid={`suggestion-approve-${suggestion.id}`}
          >
            <Icon name="check" size={14} />
            Aprobar
          </Button>
          <Button
            variant={decision === "rejected" ? "primary" : "ghost"}
            size="sm"
            disabled={busy || decision === "rejected"}
            onClick={() => onDecision(candidateId, suggestion.id, "reject")}
            aria-label={`Rechazar sugerencia ${suggestion.id}`}
            data-testid={`suggestion-reject-${suggestion.id}`}
          >
            <Icon name="close" size={14} />
            Rechazar
          </Button>
        </div>
      </div>
      {decision === "rejected" && (
        <p className="text-xs text-tinta-desvaida">
          Sugerencia rechazada — no se aplicará al importar.
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
  const ambiguous = placement.placement_status === "ambiguous";
  const markdown = `![${placement.alt_text || "imagen"}](${placement.relative_media_path})`;
  const cleanPath = placement.relative_media_path.replace(
    /#(left|right|center|sm|lg)(?:-(sm|lg))?$/i,
    "",
  );

  return (
    <li
      className={cn(
        "flex flex-col gap-2 rounded-md border p-3 tablet:flex-row tablet:items-start",
        ambiguous ? "border-llamita/50 bg-llamita/5" : "border-filio bg-cripta",
      )}
    >
      <div className="shrink-0 overflow-hidden rounded-md border border-filio bg-madero">
        <img
          src={getMediaUrl(mundo, cleanPath)}
          alt={placement.alt_text || placement.relative_media_path}
          className="h-16 w-24 object-cover"
        />
      </div>
      <div className="min-w-0 flex-1">
        <p className="text-xs text-pergamino">
          {placement.relative_media_path}
          {ambiguous && (
            <Badge variant="warning" className="ml-2">
              requiere revisión
            </Badge>
          )}
        </p>
        <p className="mt-1 text-xs text-tinta-desvaida">
          {placement.target_ficha
            ? `Ficha destino: ${placement.target_ficha}`
            : "Ficha destino: por confirmar"}
        </p>
        <p className="mt-2 text-xs text-tinta-desvaida">Markdown resultante</p>
        <code className="mt-0.5 block overflow-x-auto rounded bg-cripta px-2 py-1 text-xs text-tinta-desvaida">
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
  if (!job) {
    return (
      <div className="col-span-full">
        <div className="rounded-lg border border-filio bg-madero p-6">
          <p className="text-body text-tinta-desvaida">
            La importación no se pudo completar y no hay un estado recuperable.
          </p>
          <div className="mt-4">
            <Button variant="secondary" onClick={onNewImport}>
              Nueva importación
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
          success ? "border-musgo/40 bg-musgo/10" : "border-filio bg-madero",
        )}
      >
        <h2 className="font-heading text-h4 text-pergamino">
          {success && "Importación completada"}
          {cancelled && "Importación cancelada"}
          {failed && "La importación no se completó"}
          {rolledBack && "Importación revertida"}
          {!success && !cancelled && !failed && !rolledBack && "Estado intermedio"}
        </h2>

        {success && (
          <div className="mt-3" role="status" aria-live="polite">
            <p className="text-body text-pergamino">
              El contenido aprobado se importó a {mundo}.
            </p>
            {outcomes.length > 0 && (
              <ul className="mt-3 flex flex-wrap gap-2 text-small">
                {summary.added > 0 && (
                  <li className="rounded bg-cripta px-2 py-1 text-pergamino">
                    {summary.added} fichas creadas
                  </li>
                )}
                {summary.replaced > 0 && (
                  <li className="rounded bg-cripta px-2 py-1 text-pergamino">
                    {summary.replaced} reemplazadas
                  </li>
                )}
                {summary.kept > 0 && (
                  <li className="rounded bg-cripta px-2 py-1 text-tinta-desvaida">
                    {summary.kept} sin cambios
                  </li>
                )}
                {summary.skipped > 0 && (
                  <li className="rounded bg-cripta px-2 py-1 text-tinta-desvaida">
                    {summary.skipped} omitidas (ya presentes)
                  </li>
                )}
              </ul>
            )}
            {papeleraEntries.length > 0 && (
              <p className="mt-3 text-small text-tinta-desvaida">
                Versiones anteriores guardadas en la papelera (30 días).
              </p>
            )}
          </div>
        )}

        {cancelled && (
          <p className="mt-3 text-body text-tinta-desvaida" role="status">
            El análisis se canceló en un límite seguro: nada se escribió en tu
            mundo. Podés reanudar la revisión cuando quieras.
          </p>
        )}

        {failed && (
          <div className="mt-3">
            <p className="text-body text-tinta-desvaida">
              {job.error || "El análisis o la importación falló y quedó bloqueada."}
            </p>
          </div>
        )}

        {rolledBack && (
          <p className="mt-3 text-body text-tinta-desvaida" role="status">
            La importación quedó marcada como revertida; el registro y la
            auditoría se conservan.
          </p>
        )}

        {!success && !cancelled && !failed && !rolledBack && (
          <p className="mt-3 text-body text-tinta-desvaida">
            La importación quedó en estado {state}. Reanudala para continuar.
          </p>
        )}
      </div>

      {outcomes.length > 0 && (
        <div className="mt-4">
          <h3 className="font-heading text-h4 text-pergamino">
            Resultado por ítem
          </h3>
          <ul className="mt-2 flex flex-col gap-2">
            {outcomes.map((outcome) => (
              <li
                key={outcome.candidate_id}
                className="rounded-lg border border-filio bg-madero px-4 py-3 text-small text-pergamino"
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
                      <Badge variant="info">papelera</Badge>
                    )}
                  </span>
                </div>
                {outcome.detail && (
                  <p className="mt-1 text-xs text-tinta-desvaida">
                    {outcome.detail}
                  </p>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}

      {summary.errors > 0 && (
        <div className="mt-4 rounded-lg border border-llamita/40 bg-llamita/5 p-4" role="alert">
          <p className="text-small text-pergamino">
            {summary.errors} ítem{summary.errors === 1 ? "" : "s"} requieren
            revisión o fallaron. Revisá el detalle por ítem y decidí el
            siguiente paso.
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
            Ir al editor
          </Button>
        )}
        {cancelled && (
          <Button variant="secondary" onClick={onResume}>
            <Icon name="corner-up-right" size={16} />
            Reanudar revisión
          </Button>
        )}
        {failed && (
          <Button variant="secondary" onClick={onRetryAnalyze}>
            <Icon name="corner-up-right" size={16} />
            Reintentar
          </Button>
        )}
        {(success || rolledBack) && (
          <Button variant="ghost" onClick={onRollback} disabled={rolledBack}>
            <Icon name="history" size={16} />
            {rolledBack ? "Ya revertida" : "Revertir importación"}
          </Button>
        )}
        <Button variant="ghost" onClick={onNewImport}>
          Nueva importación
        </Button>
      </div>
    </div>
  );
}