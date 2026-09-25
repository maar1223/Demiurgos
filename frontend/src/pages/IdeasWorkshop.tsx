import { useCallback, useEffect, useMemo, useState } from "react";
import useSWR from "swr";
import { EditorLayout } from "@/components/templates/EditorLayout";
import { TabBar, type SidebarTab } from "@/components/molecules/TabBar";
import { AIAssistantSidebar } from "@/components/organisms/AIAssistantSidebar";
import { MarkdownViewer } from "@/components/organisms/MarkdownViewer";
import { ExportPdfDialog } from "@/components/organisms/ExportPdfDialog";
import { Icon } from "@/components/atoms/Icon";
import { Spinner } from "@/components/atoms/Spinner";
import { useWorlds } from "@/hooks/useWorlds";
import { downloadBlob } from "@/lib/downloadBlob";
import {
  attachIdeaMedia,
  confirmCapture,
  createIdea,
  deleteIdea,
  discardCapture,
  exportIdeaDocx,
  getIdea,
  getIdeaVersions,
  listIdeas,
  listPendingCaptures,
  materializeIdea,
  updateIdea,
  type IdeaDetail,
  type IdeaListFilters,
  type IdeaSource,
  type IdeaStatus,
  type IdeaSummary,
  type IdeaType,
  type IdeaVersionsResponse,
  type PendingCapture,
  type DiscardedMaterializeRelation,
  type IdeaMaterializePreviewResult,
  type MaterializeCollision,
  type MaterializeSection,
  type ProposedMaterializeRelation,
  IDEA_TYPES,
  MATERIALIZE_SECTIONS,
  previewMaterialize,
} from "@/api/ideas";
import { getErrorMessage } from "@/lib/utils";
import type { ApiError, FileNode, SuccessResponse } from "@/api/types";
import { createFileConfirmed, requestConfirmation } from "@/api/wiki";
import { useFileTree } from "@/hooks/useFileTree";
import { useAppLanguage } from "@/hooks/useAppLanguage";
import type { MessageKey } from "@/i18n/messages";

const TYPE_LABELS: Record<IdeaType, MessageKey> = {
  personaje: "ideas.type.personaje",
  relacion: "ideas.type.relacion",
  ambientacion: "ideas.type.ambientacion",
  trama: "ideas.type.trama",
  concepto: "ideas.type.concepto",
  sin_clasificar: "ideas.type.sinClasificar",
};

const SOURCE_LABELS: Record<IdeaSource, MessageKey> = {
  telegram: "ideas.source.telegram",
  manual: "ideas.source.manual",
  assistant: "ideas.source.assistant",
};

const STATUS_LABELS: Record<IdeaStatus, MessageKey> = {
  fresh: "ideas.status.fresh",
  used: "ideas.status.used",
};

const SECTION_LABELS: Record<MaterializeSection, MessageKey> = {
  lore: "section.lore",
  personajes: "section.personajes",
  referencias: "section.referencias",
};

/**
 * R-IM-01/AD7: the idea type suggests the ficha section. `personaje` and
 * `relacion` map to `personajes`; everything else defaults to `lore`.
 * The author can always override the preselection in the picker.
 */
function suggestSectionFor(type: IdeaType): MaterializeSection {
  return type === "personaje" || type === "relacion" ? "personajes" : "lore";
}

/** Read-only folder tree picker (AD7) — renders `FileNode` dirs, nested. */
function FolderTree({
  nodes,
  selected,
  onSelect,
}: {
  nodes: FileNode[];
  selected: string;
  onSelect: (path: string) => void;
}) {
  return (
    <ul className="space-y-0.5">
      {nodes.filter((n) => n.is_dir).map((dir) => (
        <FolderTreeBranch
          key={dir.path}
          node={dir}
          selected={selected}
          onSelect={onSelect}
        />
      ))}
    </ul>
  );
}

function FolderTreeBranch({
  node,
  selected,
  onSelect,
}: {
  node: FileNode;
  selected: string;
  onSelect: (path: string) => void;
}) {
  const childDirs = (node.children ?? []).filter((c) => c.is_dir);
  return (
    <li>
      <button
        type="button"
        onClick={() => onSelect(node.path)}
        aria-pressed={selected === node.path}
        className="flex w-full items-center gap-1.5 rounded-md px-2 py-1 text-left text-xs text-primary transition-colors hover:bg-surface-hover aria-pressed:bg-action/15 aria-pressed:text-action"
      >
        <Icon name="folder" size={12} className="shrink-0 opacity-70" />
        <span className="min-w-0 truncate">{node.name}</span>
      </button>
      {childDirs.length > 0 && (
        <ul className="ml-3 border-l border-edge pl-2">
          {childDirs.map((child) => (
            <FolderTreeBranch
              key={child.path}
              node={child}
              selected={selected}
              onSelect={onSelect}
            />
          ))}
        </ul>
      )}
    </li>
  );
}

/**
 * Read-only preview dialog for a materialize draft (AD8). Renders the
 * server-owned ficha content via MarkdownViewer plus the proposed and
 * discarded relations. A 409 collision opens the same dialog in collision
 * mode: no draft exists, only the `suggested_slug` hint. Nothing here is
 * editable — the ficha becomes editable after creation.
 */
function MaterializePreviewDialog({
  preview,
  collision,
  confirming,
  onConfirm,
  onClose,
}: {
  preview: IdeaMaterializePreviewResult | null;
  collision: MaterializeCollision | null;
  confirming: boolean;
  onConfirm: () => void;
  onClose: () => void;
}) {
  const { t } = useAppLanguage();
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-surface/80 backdrop-blur-sm"
      onClick={(e) => {
        if (e.target === e.currentTarget && !confirming) onClose();
      }}
    >
      <div
        className="mx-4 flex max-h-[85vh] w-full max-w-2xl flex-col rounded-xl border border-edge bg-surface-raised shadow-2xl"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label={t("ideas.preview.title")}
      >
        {/* Header */}
        <div className="flex items-center justify-between border-b border-edge px-6 py-4">
          <h2 className="font-heading text-h4 text-primary">
            {t("ideas.preview.title")}
          </h2>
          <button
            type="button"
            onClick={onClose}
            disabled={confirming}
            className="rounded-md p-1 text-icon-muted transition-colors hover:bg-surface-hover hover:text-primary disabled:opacity-50"
            aria-label={t("ideas.preview.close")}
          >
            <Icon name="close" size={20} />
          </button>
        </div>

        {/* Body */}
        <div className="min-h-0 flex-1 overflow-y-auto px-6 py-4">
          {collision && !preview ? (
            <div className="rounded-lg border border-status-error/30 bg-status-error/10 px-4 py-3 text-xs text-status-error">
              <p className="font-medium">{t("ideas.preview.collisionTitle")}</p>
              <p className="mt-1">
                {t("ideas.preview.targetLabel")}{" "}
                <span className="font-mono">{collision.target}</span>
              </p>
              <p className="mt-1">
                {t("ideas.preview.suggestedSlug")}{" "}
                <span className="font-mono">{collision.suggested_slug}</span>{" "}
                (→{" "}
                <span className="font-mono">{collision.suggested_target}</span>)
              </p>
            </div>
          ) : preview ? (
            <div className="space-y-4">
              <p className="text-xs text-muted">
                {t("ideas.preview.targetLabel")}{" "}
                <span className="font-mono">{preview.target.path}</span>
              </p>
              <MarkdownViewer
                content={preview.content}
                mundo={preview.target.world}
                imageFit="contain"
              />
              <section aria-label={t("ideas.preview.proposedRelations")}>
                <h3 className="mb-1 text-body font-medium text-primary">
                  {t("ideas.preview.proposedRelations")}
                </h3>
                {preview.proposed_relations.length === 0 ? (
                  <p className="text-xs text-muted">{t("ideas.preview.none")}</p>
                ) : (
                  <ul className="space-y-1">
                    {preview.proposed_relations.map(
                      (rel: ProposedMaterializeRelation) => (
                        <li
                          key={rel.target_id}
                          className="flex items-baseline gap-2 rounded-md bg-surface px-2.5 py-1.5 text-xs"
                        >
                          <span className="shrink-0 font-medium text-primary">
                            {rel.rel_type}
                          </span>
                          <span
                            className="min-w-0 truncate text-muted"
                            title={rel.target_id}
                          >
                            {rel.title || rel.target_id}
                          </span>
                        </li>
                      ),
                    )}
                  </ul>
                )}
              </section>
              <section aria-label={t("ideas.preview.discardedRelations")}>
                <h3 className="mb-1 text-body font-medium text-primary">
                  {t("ideas.preview.discardedRelations")}
                </h3>
                {preview.discarded_relations.length === 0 ? (
                  <p className="text-xs text-muted">{t("ideas.preview.none")}</p>
                ) : (
                  <ul className="space-y-1">
                    {preview.discarded_relations.map(
                      (rel: DiscardedMaterializeRelation) => (
                        <li
                          key={`${rel.target_id}-${rel.reason}`}
                          className="flex items-baseline gap-2 rounded-md bg-surface px-2.5 py-1.5 text-xs text-status-error"
                        >
                          <span className="shrink-0 font-medium">
                            {rel.target_id}
                          </span>
                          <span className="text-muted">{rel.reason}</span>
                        </li>
                      ),
                    )}
                  </ul>
                )}
              </section>
            </div>
          ) : null}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-2 border-t border-edge px-6 py-4">
          <button
            type="button"
            onClick={onClose}
            disabled={confirming}
            className="rounded-md border border-edge px-3 py-1.5 text-xs text-muted transition-colors hover:border-action/40 hover:text-primary disabled:opacity-50"
          >
            {t("ideas.preview.close")}
          </button>
          {preview && !collision && (
            <button
              type="button"
              onClick={onConfirm}
              disabled={confirming}
              className="rounded-md bg-action px-3 py-1.5 text-xs font-medium text-action-text transition-colors hover:bg-action-hover disabled:cursor-not-allowed disabled:opacity-50"
            >
              {confirming ? t("ideas.preview.creating") : t("ideas.preview.create")}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

/**
 * IdeasWorkshop — the global Taller de Ideas (`/ideas`).
 *
 * World-agnostic two-panel page mirroring the wiki editor: the left panel
 * (EditorLayout sidebar) holds the filterable idea list plus the manual
 * create form; the main area shows the selected idea detail with the
 * materialize ("usar en el mundo") and reclassify actions; the right panel
 * hosts the AI assistant in null-mundo context (`ideas-global` session).
 * Functional-first: no visual polish beyond the shared design tokens.
 */
export default function IdeasWorkshop() {
  const { worlds } = useWorlds();
  const { t } = useAppLanguage();

  // ── Filters ──────────────────────────────────────────────────────────────
  const [typeFilter, setTypeFilter] = useState<"" | IdeaType>("");
  const [statusFilter, setStatusFilter] = useState<"" | IdeaStatus>("");
  const [sourceFilter, setSourceFilter] = useState<"" | IdeaSource>("");

  // ── Search & sort (client-side) ──────────────────────────────────────────
  type IdeaSortKey = "recent" | "oldest" | "name" | "type" | "status";
  const [searchQuery, setSearchQuery] = useState("");
  const [debouncedQuery, setDebouncedQuery] = useState("");
  const [sortKey, setSortKey] = useState<IdeaSortKey>("recent");
  const [sortOrder, setSortOrder] = useState<"asc" | "desc">("desc"); // name/type/status; recent/oldest ignore

  // ~250ms debounce so the client-side filter only runs once typing settles.
  useEffect(() => {
    const timer = window.setTimeout(() => setDebouncedQuery(searchQuery), 250);
    return () => window.clearTimeout(timer);
  }, [searchQuery]);

  // ── Selection & panels ───────────────────────────────────────────────────
  const [selectedSlug, setSelectedSlug] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [sidebarTab, setSidebarTab] = useState<SidebarTab>("asistente");
  const [materializeFor, setMaterializeFor] = useState<string | null>(null);

  // ── Feedback ─────────────────────────────────────────────────────────────
  const [actionError, setActionError] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);

  const filters: IdeaListFilters = {
    type: typeFilter || undefined,
    status: statusFilter || undefined,
    source: sourceFilter || undefined,
  };

  // ── Data (SWR mirrors the wiki page pattern) ─────────────────────────────
  const listKey = [
    "ideas",
    typeFilter,
    statusFilter,
    sourceFilter,
  ];
  const {
    data: listData,
    error: listError,
    isLoading: listLoading,
    mutate: mutateList,
  } = useSWR(listKey, () => listIdeas(filters), {
    revalidateOnFocus: true,
    revalidateOnReconnect: true,
    errorRetryCount: 2,
  });

  const {
    data: detail,
    error: detailError,
    isLoading: detailLoading,
    mutate: mutateDetail,
  } = useSWR<IdeaDetail | null>(
    selectedSlug ? ["idea", selectedSlug] : null,
    () => getIdea(selectedSlug as string),
    { revalidateOnFocus: true },
  );

  // Version history for the selected idea (R-10). Refreshed after any
  // PATCH so a new archive appears as soon as it's created.
  const {
    data: versionsData,
    error: versionsError,
    mutate: mutateVersions,
  } = useSWR<IdeaVersionsResponse | null>(
    selectedSlug ? ["idea-versions", selectedSlug] : null,
    () => getIdeaVersions(selectedSlug as string),
    { revalidateOnFocus: true },
  );

  const archivedVersions = versionsData?.versions ?? [];

  const ideas = listData?.ideas ?? [];
  const selectedIdea = detail ?? null;

  // Client-side search (title + slug + tags) and sort over the fetched list.
  const filteredIdeas = useMemo(() => {
    const q = debouncedQuery.trim().toLowerCase();
    let list = ideas;
    if (q) {
      list = list.filter((i) =>
        (i.title || i.slug).toLowerCase().includes(q) ||
        i.slug.toLowerCase().includes(q) ||
        i.tags.some((t) => t.toLowerCase().includes(q)),
      );
    }
    const sorted = [...list];
    const getRecent = (i: IdeaSummary) => {
      const upd = i.updated_at || i.timestamp;
      const created = i.timestamp;
      // latest of the two
      return upd > created ? upd : created;
    };
    switch (sortKey) {
      case "recent":
        sorted.sort((a, b) => getRecent(b).localeCompare(getRecent(a)));
        break;
      case "oldest":
        sorted.sort((a, b) => a.timestamp.localeCompare(b.timestamp));
        break;
      case "name": {
        const cmp = (a: IdeaSummary, b: IdeaSummary) =>
          (a.title || a.slug).localeCompare(b.title || b.slug, "es");
        sorted.sort(sortOrder === "asc" ? cmp : (a, b) => cmp(b, a));
        break;
      }
      case "type": {
        const cmp = (a: IdeaSummary, b: IdeaSummary) =>
          TYPE_LABELS[a.type].localeCompare(TYPE_LABELS[b.type], "es");
        sorted.sort(sortOrder === "asc" ? cmp : (a, b) => cmp(b, a));
        break;
      }
      case "status": {
        const cmp = (a: IdeaSummary, b: IdeaSummary) =>
          STATUS_LABELS[a.status].localeCompare(STATUS_LABELS[b.status], "es");
        sorted.sort(sortOrder === "asc" ? cmp : (a, b) => cmp(b, a));
        break;
      }
    }
    return sorted;
  }, [ideas, debouncedQuery, sortKey, sortOrder]);

  // ── Pending captures ("Ideas por confirmar", R-8) ───────────────────────
  // SWR keyed on the pending queue: the counter badge and the review panel
  // share one fetch, and every confirm/discard mutates it so both update.
  // (The action handlers live below, after notifyError/showToast, which they
  // depend on.)
  const {
    data: pendingData,
    mutate: mutatePending,
  } = useSWR("idea-capture-pending", () => listPendingCaptures(), {
    revalidateOnFocus: true,
    revalidateOnReconnect: true,
    errorRetryCount: 2,
  });
  const pendingCount = pendingData?.count ?? 0;
  const pendingCaptures = pendingData?.captures ?? [];

  const [actingCaptureId, setActingCaptureId] = useState<string | null>(null);

  const notifyError = useCallback((err: unknown) => {
    const apiError = err as ApiError;
    setActionError(getErrorMessage(apiError.status, apiError.detail));
  }, []);

  const showToast = useCallback((message: string) => {
    setToast(message);
    window.setTimeout(() => setToast(null), 2500);
  }, []);

  // ── Pending capture actions (Guardar como idea / Descartar, S-8.2/S-8.3) ─
  const handleConfirmPending = useCallback(async (captureId: string) => {
    setActingCaptureId(captureId);
    setActionError(null);
    try {
      await confirmCapture(captureId);
      await mutatePending();
      showToast(t("ideas.toast.savedPending"));
    } catch (err) {
      notifyError(err);
    } finally {
      setActingCaptureId(null);
    }
  }, [mutatePending, notifyError, showToast, t]);

  const handleDiscardPending = useCallback(async (captureId: string) => {
    setActingCaptureId(captureId);
    setActionError(null);
    try {
      await discardCapture(captureId);
      await mutatePending();
      showToast(t("ideas.toast.discarded"));
    } catch (err) {
      notifyError(err);
    } finally {
      setActingCaptureId(null);
    }
  }, [mutatePending, notifyError, showToast, t]);

  // ── Create ───────────────────────────────────────────────────────────────
  const [createSlug, setCreateSlug] = useState("");
  const [createType, setCreateType] = useState<IdeaType>("sin_clasificar");
  const [createTitle, setCreateTitle] = useState("");
  const [createTags, setCreateTags] = useState("");
  const [createBody, setCreateBody] = useState("");
  const [creating, setCreating] = useState(false);

  const resetCreateForm = useCallback(() => {
    setCreateSlug("");
    setCreateType("sin_clasificar");
    setCreateTitle("");
    setCreateTags("");
    setCreateBody("");
    setShowCreate(false);
  }, []);

  const handleCreate = useCallback(async () => {
    const slug = createSlug.trim();
    const body = createBody.trim();
    if (!slug || !body) {
      setActionError(t("ideas.error.slugBody"));
      return;
    }
    setCreating(true);
    setActionError(null);
    try {
      const created = await createIdea({
        slug,
        type: createType,
        body,
        tags: createTags
          .split(",")
          .map((tag) => tag.trim())
          .filter(Boolean),
        ...(createTitle.trim() ? { title: createTitle.trim() } : {}),
      });
      await mutateList();
      resetCreateForm();
      setSelectedSlug(created.slug);
      showToast(t("ideas.toast.created", { title: created.title || created.slug }));
    } catch (err) {
      notifyError(err);
    } finally {
      setCreating(false);
    }
  }, [createBody, createSlug, createTags, createTitle, createType, mutateList, notifyError, resetCreateForm, showToast, t]);

  // ── Reclassify (type correction) ────────────────────────────────────────
  const [reclassifyType, setReclassifyType] = useState<IdeaType>("sin_clasificar");
  const [reclassifying, setReclassifying] = useState(false);

  const openDetail = useCallback((slug: string) => {
    setSelectedSlug(slug);
    setMaterializeFor(null);
  }, []);

  // Keep the reclassify select in sync with the loaded idea type.
  useEffect(() => {
    if (selectedIdea) setReclassifyType(selectedIdea.type);
  }, [selectedIdea?.slug]); // eslint-disable-line react-hooks/exhaustive-deps

  const handleReclassify = useCallback(async () => {
    if (!selectedSlug || reclassifyType === selectedIdea?.type) return;
    setReclassifying(true);
    setActionError(null);
    try {
      await updateIdea(selectedSlug, { type: reclassifyType });
      await mutateDetail();
      await mutateList();
      await mutateVersions();
      showToast(t("ideas.toast.reclassified", { type: t(TYPE_LABELS[reclassifyType]) }));
    } catch (err) {
      notifyError(err);
    } finally {
      setReclassifying(false);
    }
  }, [selectedSlug, reclassifyType, selectedIdea?.type, mutateDetail, mutateList, mutateVersions, notifyError, showToast, t]);

  // ── Edit title ──────────────────────────────────────────────────────────
  const [editTitle, setEditTitle] = useState("");
  const [savingTitle, setSavingTitle] = useState(false);

  // Keep the title input in sync with the loaded idea (reclassify pattern).
  useEffect(() => {
    if (selectedIdea) setEditTitle(selectedIdea.title ?? "");
  }, [selectedIdea?.slug]); // eslint-disable-line react-hooks/exhaustive-deps

  const handleEditTitle = useCallback(async () => {
    if (!selectedSlug || editTitle.trim() === (selectedIdea?.title ?? "")) return;
    setSavingTitle(true);
    setActionError(null);
    try {
      await updateIdea(selectedSlug, { title: editTitle.trim() });
      await mutateDetail();
      await mutateList();
      await mutateVersions();
      showToast(t("ideas.toast.titleSaved", { title: editTitle.trim() }));
    } catch (err) {
      notifyError(err);
    } finally {
      setSavingTitle(false);
    }
  }, [selectedSlug, editTitle, selectedIdea?.title, mutateDetail, mutateList, mutateVersions, notifyError, showToast, t]);

  // ── Export (PDF / DOCX) ──────────────────────────────────────────────────
  /** "PDF" target — opens ExportPdfDialog with the idea body. `mundo=""` by
   *  design: the idea's absolute /api/ideas/... image URLs pass through
   *  MarkdownImage untouched. */
  const [pdfTarget, setPdfTarget] = useState<{
    content: string;
    fileName: string;
  } | null>(null);

  const handleExportIdeaPdf = useCallback(() => {
    if (!selectedIdea) return;
    setPdfTarget({ content: selectedIdea.body, fileName: selectedIdea.slug });
  }, [selectedIdea]);

  /** "DOCX" — fetch the idea through the export endpoint and download the
   *  returned blob ({slug}.docx, mirroring the backend filename). Failures
   *  surface as the inline action error; no file is downloaded. */
  const handleExportIdeaDocx = useCallback(async () => {
    if (!selectedSlug) return;
    setActionError(null);
    try {
      const blob = await exportIdeaDocx(selectedSlug);
      downloadBlob(blob, `${selectedSlug}.docx`);
    } catch (err) {
      notifyError(err);
    }
  }, [selectedSlug, notifyError]);

  // ── Attach image ("adjuntar imagen", POST /api/ideas/{slug}/media) ─────
  const [attachingMedia, setAttachingMedia] = useState(false);

  const handleAttachMedia = useCallback(
    async (event: React.ChangeEvent<HTMLInputElement>) => {
      const input = event.target;
      const file = input.files?.[0];
      if (!file || !selectedSlug) return;
      setAttachingMedia(true);
      setActionError(null);
      try {
        await attachIdeaMedia(selectedSlug, file);
        await mutateDetail();
        await mutateList();
        await mutateVersions();
        showToast(t("ideas.toast.imageAttached"));
      } catch (err) {
        notifyError(err);
      } finally {
        setAttachingMedia(false);
        input.value = "";
      }
    },
    [selectedSlug, mutateDetail, mutateList, mutateVersions, notifyError, showToast, t],
  );

  // ── Materialize ("usar en el mundo") ─────────────────────────────────────
  const [materializeWorld, setMaterializeWorld] = useState("");
  const [materializeSection, setMaterializeSection] =
    useState<MaterializeSection>("lore");
  const [materializeFolder, setMaterializeFolder] = useState("");
  const [materializeTitleHint, setMaterializeTitleHint] = useState("");
  const [preview, setPreview] = useState<IdeaMaterializePreviewResult | null>(null);
  const [collision, setCollision] = useState<MaterializeCollision | null>(null);
  const [previewing, setPreviewing] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [markingUsed, setMarkingUsed] = useState(false);

  // Folder tree for the selected world + section (AD7). Null key while no
  // world is chosen, so the hook stays idle until a world is picked.
  const { nodes: folderNodes, isLoading: folderLoading } = useFileTree(
    materializeWorld || undefined,
    materializeSection,
  );

  const openMaterialize = useCallback(() => {
    if (!selectedIdea) return;
    setActionError(null);
    setPreview(null);
    setCollision(null);
    setMaterializeFor(selectedIdea.slug);
    setMaterializeWorld("");
    setMaterializeSection(suggestSectionFor(selectedIdea.type));
    setMaterializeFolder("");
    setMaterializeTitleHint("");
  }, [selectedIdea]);

  const closeMaterialize = useCallback(() => {
    setMaterializeFor(null);
    setMaterializeWorld("");
    setMaterializeSection("lore");
    setMaterializeFolder("");
    setMaterializeTitleHint("");
    setPreview(null);
    setCollision(null);
  }, []);

  // "Previsualizar" — POST /materialize-preview. Read-only: the dialog only
  // shows the server-owned draft; nothing is edited in-dialog (AD8). A 409
  // collision arrives as an error carrying `collision` at the top level; the
  // dialog then shows the suggested slug instead of a draft.
  const handlePreview = useCallback(async () => {
    if (!materializeFor || !materializeWorld) {
      setActionError(t("ideas.materialize.error.selectWorldPreview"));
      return;
    }
    setPreviewing(true);
    setActionError(null);
    setCollision(null);
    try {
      const result = await previewMaterialize(materializeFor, {
        world: materializeWorld,
        section: materializeSection,
        folder: materializeFolder,
        ...(materializeTitleHint.trim()
          ? { title_hint: materializeTitleHint.trim() }
          : {}),
      });
      setPreview(result);
    } catch (err) {
      const apiError = err as ApiError & { collision?: MaterializeCollision };
      if (apiError.collision) {
        setPreview(null);
        setCollision(apiError.collision);
        return;
      }
      notifyError(err);
    } finally {
      setPreviewing(false);
    }
  }, [
    materializeFor,
    materializeWorld,
    materializeSection,
    materializeFolder,
    materializeTitleHint,
    notifyError,
    t,
  ]);

  // Confirm — issue the single-use edit-confirmation token (kind=new,
  // edit_id=proposal_id, proposed_content=content) and create through the
  // gated pipeline; the digest binds the exact previewed content (R-IM-05).
  const handleConfirmPreview = useCallback(async () => {
    if (!preview || !materializeWorld) return;
    setConfirming(true);
    setActionError(null);
    try {
      const { world, section, path } = preview.target;
      const confirmation = await requestConfirmation(world, section, path, {
        edit_id: preview.proposal_id,
        kind: "new",
        proposed_content: preview.content,
      });
      const result = (await createFileConfirmed(world, section, path, {
        content: preview.content,
        edit_id: preview.proposal_id,
        proposed_digest: confirmation.proposed_digest,
        token: confirmation.token,
      })) as SuccessResponse & {
        index_status?: string;
        retryable?: boolean;
        message?: string;
      };
      await mutateDetail();
      await mutateList();
      closeMaterialize();
      showToast(
        result.index_status
          ? t("ideas.materialize.toast.createdIndex", {
              status: result.index_status,
            })
          : t("ideas.materialize.toast.created"),
      );
    } catch (err) {
      notifyError(err);
    } finally {
      setConfirming(false);
    }
  }, [
    preview,
    materializeWorld,
    mutateDetail,
    mutateList,
    closeMaterialize,
    notifyError,
    showToast,
    t,
  ]);

  // Legacy fallback (R-IM-10): mark the idea as used in the world WITHOUT
  // creating a ficha, via the original POST /api/ideas/{slug}/materialize.
  const handleMarkUsedOnly = useCallback(async () => {
    if (!materializeFor || !materializeWorld) {
      setActionError(t("ideas.materialize.error.selectWorldMark"));
      return;
    }
    setMarkingUsed(true);
    setActionError(null);
    try {
      const result = await materializeIdea(materializeFor, materializeWorld);
      await mutateDetail();
      await mutateList();
      closeMaterialize();
      showToast(
        t("ideas.materialize.toast.used", {
          world: materializeWorld,
          usedIn: result.used_in.join(", "),
        }),
      );
    } catch (err) {
      notifyError(err);
    } finally {
      setMarkingUsed(false);
    }
  }, [
    materializeFor,
    materializeWorld,
    mutateDetail,
    mutateList,
    closeMaterialize,
    notifyError,
    showToast,
    t,
  ]);

  // ── Delete ───────────────────────────────────────────────────────────────
  const [deleting, setDeleting] = useState(false);

  const handleDelete = useCallback(async () => {
    if (!selectedSlug) return;
    if (!window.confirm(t("ideas.deleteConfirm", { slug: selectedSlug }))) {
      return;
    }
    setDeleting(true);
    setActionError(null);
    try {
      await deleteIdea(selectedSlug);
      setSelectedSlug(null);
      await mutateList();
      showToast(t("ideas.toast.deleted", { slug: selectedSlug }));
    } catch (err) {
      notifyError(err);
    } finally {
      setDeleting(false);
    }
  }, [selectedSlug, mutateList, notifyError, showToast, t]);

  // ── Left panel: filters + list + create form ─────────────────────────────
  const sidebar = (
    <div className="flex h-full flex-col">
      <div className="border-b border-edge px-4 py-3">
        <div className="flex items-center justify-between gap-2">
          <h2 className="font-heading text-body font-medium text-primary">{t("ideas.title")}</h2>
          <span className="text-xs text-muted">{ideas.length}</span>
        </div>

        {/* S-8.1: pending queue counter (shared SWR key with the panel) */}
        {pendingCount > 0 && (
          <div className="mt-2 rounded-md border border-action/30 bg-action/10 px-2.5 py-1.5 text-xs font-medium text-action">
            {t("ideas.pendingCounter", { count: pendingCount })}
          </div>
        )}

        <button
          type="button"
          onClick={() => {
            setActionError(null);
            setShowCreate((prev) => !prev);
          }}
          className="mt-2 flex w-full items-center justify-center gap-1.5 rounded-md bg-action px-2.5 py-1.5 text-xs font-medium text-action-text transition-colors hover:bg-action-hover"
          aria-label={t("ideas.newIdeaAria")}
        >
          <Icon name="plus" size={13} />
          {t("ideas.newIdea")}
        </button>
      </div>

      {/* S-8.2/S-8.3: web review panel — parked captures with Guardar/Descartar.
          Same SWR key as the counter: after either action, mutatePending()
          re-fetches the queue and the resolved capture leaves the panel. */}
      {pendingCaptures.length > 0 && (
        <div
          role="region"
          aria-label={t("ideas.reviewAria")}
          className="border-b border-edge bg-surface/60 px-4 py-3"
        >
          <h3 className="mb-2 text-xs font-medium text-primary">{t("ideas.pendingHeading")}</h3>
          <ul className="space-y-2">
            {pendingCaptures.map((capture: PendingCapture) => (
              <li
                key={capture.capture_id}
                className="rounded-md border border-edge bg-surface-raised p-2.5"
              >
                <div className="mb-1 flex items-center justify-between gap-2">
                  <span className="truncate text-xs font-medium text-primary">
                    {capture.slug}
                  </span>
                  {capture.event_ts && (
                    <span className="shrink-0 text-[10px] text-muted">
                      {new Date(capture.event_ts).toLocaleString()}
                    </span>
                  )}
                </div>
                <p className="mb-2 line-clamp-2 text-xs text-muted">
                  {capture.raw_text}
                </p>
                <div className="flex gap-2">
                  <button
                    type="button"
                    onClick={() => void handleConfirmPending(capture.capture_id)}
                    disabled={actingCaptureId === capture.capture_id}
                    className="flex-1 rounded-md bg-action px-2 py-1 text-xs font-medium text-action-text transition-colors hover:bg-action-hover disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {t("ideas.saveAsIdea")}
                  </button>
                  <button
                    type="button"
                    onClick={() => void handleDiscardPending(capture.capture_id)}
                    disabled={actingCaptureId === capture.capture_id}
                    className="flex-1 rounded-md border border-status-error/30 px-2 py-1 text-xs text-status-error transition-colors hover:bg-status-error/10 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {t("ideas.discard")}
                  </button>
                </div>
              </li>
            ))}
          </ul>
        </div>
      )}

      {showCreate && (
        <div
          role="group"
          aria-label={t("ideas.createAria")}
          className="border-b border-edge bg-surface/60 px-4 py-3"
        >
          <div className="space-y-2">
            <div>
              <label htmlFor="idea-slug" className="mb-1 block text-xs text-muted">
                {t("ideas.slugLabel")}
              </label>
              <input
                id="idea-slug"
                value={createSlug}
                onChange={(e) => setCreateSlug(e.target.value)}
                placeholder={t("ideas.slugPlaceholder")}
                className="w-full rounded-md border border-edge bg-surface-raised px-2.5 py-1.5 text-xs text-primary placeholder:text-muted focus:border-action focus:outline-none focus:ring-1 focus:ring-action/50"
              />
            </div>
            <div>
              <label htmlFor="idea-type" className="mb-1 block text-xs text-muted">
                {t("ideas.typeLabel")}
              </label>
              <select
                id="idea-type"
                value={createType}
                onChange={(e) => setCreateType(e.target.value as IdeaType)}
                className="w-full rounded-md border border-edge bg-surface-raised px-2.5 py-1.5 text-xs text-primary focus:border-action focus:outline-none focus:ring-1 focus:ring-action/50"
              >
                {IDEA_TYPES.map((type) => (
                  <option key={type} value={type}>
                    {t(TYPE_LABELS[type])}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label htmlFor="idea-title" className="mb-1 block text-xs text-muted">
                {t("ideas.titleLabel")}
              </label>
              <input
                id="idea-title"
                value={createTitle}
                onChange={(e) => setCreateTitle(e.target.value)}
                placeholder={t("ideas.titlePlaceholder")}
                className="w-full rounded-md border border-edge bg-surface-raised px-2.5 py-1.5 text-xs text-primary placeholder:text-muted focus:border-action focus:outline-none focus:ring-1 focus:ring-action/50"
              />
            </div>
            <div>
              <label htmlFor="idea-tags" className="mb-1 block text-xs text-muted">
                {t("ideas.tagsLabel")}
              </label>
              <input
                id="idea-tags"
                value={createTags}
                onChange={(e) => setCreateTags(e.target.value)}
                placeholder={t("ideas.tagsPlaceholder")}
                className="w-full rounded-md border border-edge bg-surface-raised px-2.5 py-1.5 text-xs text-primary placeholder:text-muted focus:border-action focus:outline-none focus:ring-1 focus:ring-action/50"
              />
            </div>
            <div>
              <label htmlFor="idea-body" className="mb-1 block text-xs text-muted">
                {t("ideas.bodyLabel")}
              </label>
              <textarea
                id="idea-body"
                value={createBody}
                onChange={(e) => setCreateBody(e.target.value)}
                rows={4}
                placeholder={t("ideas.bodyPlaceholder")}
                className="w-full resize-none rounded-md border border-edge bg-surface-raised px-2.5 py-1.5 text-xs text-primary placeholder:text-muted focus:border-action focus:outline-none focus:ring-1 focus:ring-action/50"
              />
            </div>
            <div className="flex gap-2">
              <button
                type="button"
                onClick={() => void handleCreate()}
                disabled={creating}
                className="flex-1 rounded-md bg-action px-2.5 py-1.5 text-xs font-medium text-action-text transition-colors hover:bg-action-hover disabled:cursor-not-allowed disabled:opacity-50"
              >
                {creating ? t("ideas.creating") : t("ideas.create")}
              </button>
              <button
                type="button"
                onClick={resetCreateForm}
                disabled={creating}
                className="rounded-md border border-edge px-2.5 py-1.5 text-xs text-muted transition-colors hover:border-action/40 hover:text-primary disabled:opacity-50"
              >
                {t("ideas.cancel")}
              </button>
            </div>
          </div>
        </div>
      )}

      <div className="space-y-1.5 border-b border-edge px-4 py-2.5">
        <div className="relative">
          <Icon
            name="search"
            size={14}
            className="absolute left-2.5 top-1/2 -translate-y-1/2 text-muted"
          />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder={t("ideas.searchPlaceholder")}
            aria-label={t("ideas.searchAria")}
            className="w-full rounded-md border border-edge bg-surface-raised py-1.5 pl-8 pr-3 text-xs text-primary placeholder:text-muted transition-colors focus:border-action focus:outline-none focus:ring-1 focus:ring-action/50"
          />
        </div>
        <div className="grid grid-cols-2 gap-1.5">
          <select
            aria-label={t("ideas.sortAria")}
            value={sortKey}
            onChange={(e) => setSortKey(e.target.value as IdeaSortKey)}
            className="w-full rounded-md border border-edge bg-surface-raised px-1.5 py-1 text-xs text-primary focus:border-action focus:outline-none"
          >
            <option value="recent">{t("ideas.sort.recent")}</option>
            <option value="oldest">{t("ideas.sort.oldest")}</option>
            <option value="name">{t("ideas.sort.name")}</option>
            <option value="type">{t("ideas.sort.type")}</option>
            <option value="status">{t("ideas.sort.status")}</option>
          </select>
          {sortKey === "name" || sortKey === "type" || sortKey === "status" ? (
            <select
              aria-label={t("ideas.sortDirectionAria")}
              value={sortOrder}
              onChange={(e) => setSortOrder(e.target.value as "asc" | "desc")}
              className="w-full rounded-md border border-edge bg-surface-raised px-1.5 py-1 text-xs text-primary focus:border-action focus:outline-none"
            >
              <option value="desc">{t("ideas.sort.desc")}</option>
              <option value="asc">{t("ideas.sort.asc")}</option>
            </select>
          ) : (
            <span className="flex items-center justify-center rounded-md border border-edge bg-surface-raised px-1.5 py-1 text-xs text-muted">
              {sortKey === "recent" ? t("ideas.sort.recentFirst") : t("ideas.sort.oldestFirst")}
            </span>
          )}
        </div>
      </div>

      <div className="grid grid-cols-3 gap-1.5 border-b border-edge px-4 py-2.5" aria-label={t("ideas.filtersAria")}>
        <select
          aria-label={t("ideas.filter.typeAria")}
          value={typeFilter}
          onChange={(e) => setTypeFilter(e.target.value as "" | IdeaType)}
          className="w-full rounded-md border border-edge bg-surface-raised px-1.5 py-1 text-xs text-primary focus:border-action focus:outline-none"
        >
          <option value="">{t("ideas.filter.typeAll")}</option>
          {IDEA_TYPES.map((type) => (
            <option key={type} value={type}>
              {t(TYPE_LABELS[type])}
            </option>
          ))}
        </select>
        <select
          aria-label={t("ideas.filter.statusAria")}
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value as "" | IdeaStatus)}
          className="w-full rounded-md border border-edge bg-surface-raised px-1.5 py-1 text-xs text-primary focus:border-action focus:outline-none"
        >
          <option value="">{t("ideas.filter.statusAll")}</option>
          <option value="fresh">{t(STATUS_LABELS.fresh)}</option>
          <option value="used">{t(STATUS_LABELS.used)}</option>
        </select>
        <select
          aria-label={t("ideas.filter.sourceAria")}
          value={sourceFilter}
          onChange={(e) => setSourceFilter(e.target.value as "" | IdeaSource)}
          className="w-full rounded-md border border-edge bg-surface-raised px-1.5 py-1 text-xs text-primary focus:border-action focus:outline-none"
        >
          <option value="">{t("ideas.filter.sourceAll")}</option>
          <option value="telegram">{t(SOURCE_LABELS.telegram)}</option>
          <option value="manual">{t(SOURCE_LABELS.manual)}</option>
          <option value="assistant">{t(SOURCE_LABELS.assistant)}</option>
        </select>
      </div>

      <div className="flex-1 overflow-y-auto py-2">
        {listLoading ? (
          <div className="flex items-center justify-center py-10" role="status">
            <Spinner size="md" />
          </div>
        ) : listError ? (
          <p className="px-4 py-6 text-center text-xs text-status-error">
            {getErrorMessage((listError as ApiError).status, (listError as ApiError).detail)}
          </p>
        ) : ideas.length === 0 ? (
          <p className="px-4 py-6 text-center text-xs text-muted">
            {t("ideas.empty")}
          </p>
        ) : filteredIdeas.length === 0 ? (
          <p className="px-4 py-6 text-center text-xs text-muted">
            {t("ideas.emptyFiltered")}
          </p>
        ) : (
          <ul aria-label={t("ideas.listAria")} className="space-y-0.5 px-2">
            {filteredIdeas.map((idea: IdeaSummary) => (
              <li key={idea.slug}>
                <button
                  type="button"
                  onClick={() => openDetail(idea.slug)}
                  aria-current={selectedSlug === idea.slug ? "true" : undefined}
                  className={[
                    "flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left transition-colors",
                    selectedSlug === idea.slug
                      ? "bg-action/20 text-action"
                      : "hover:bg-surface-hover",
                  ].join(" ")}
                >
                  <Icon name="lightbulb" size={14} className="shrink-0 opacity-60" />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm font-medium text-primary">{idea.title || idea.slug}</span>
                    <span className="block truncate text-sm text-muted">
                      {t(TYPE_LABELS[idea.type])} · {t(STATUS_LABELS[idea.status])}
                    </span>
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );

  // ── Main panel: detail ───────────────────────────────────────────────────
  const main = (
    <div className="mx-auto max-w-3xl">
      {detailLoading ? (
        <div className="flex items-center justify-center py-24" role="status">
          <Spinner size="lg" />
        </div>
      ) : detailError ? (
        <div className="py-16 text-center">
          <p className="text-body text-status-error">
            {getErrorMessage((detailError as ApiError).status, (detailError as ApiError).detail)}
          </p>
        </div>
      ) : !selectedIdea ? (
        <div className="flex flex-col items-center justify-center gap-3 py-24 text-center">
          <div className="flex h-14 w-14 items-center justify-center rounded-full bg-action/10 text-action">
            <Icon name="lightbulb" size={28} />
          </div>
          <h2 className="font-heading text-h3 text-primary">{t("ideas.detail.title")}</h2>
          <p className="max-w-sm text-body text-muted">
            {t("ideas.detail.empty")}
          </p>
        </div>
      ) : (
        <article aria-label={t("ideas.detail.articleAria", { slug: selectedIdea.slug })}>
          <header className="mb-4 border-b border-edge pb-4">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="font-heading text-h2 text-primary">{selectedIdea.title || selectedIdea.slug}</h2>
              <span className="rounded-full bg-action/10 px-2.5 py-0.5 text-xs text-action">
                {t(TYPE_LABELS[selectedIdea.type])}
              </span>
              <span className="rounded-full bg-surface-raised px-2.5 py-0.5 text-xs text-muted">
                {t(STATUS_LABELS[selectedIdea.status])}
              </span>
              <div className="ml-auto flex items-center gap-2">
                <button
                  type="button"
                  onClick={handleExportIdeaPdf}
                  aria-label={t("ideas.detail.exportPdfAria")}
                  className="rounded-md border border-edge bg-surface px-2.5 py-1 text-xs font-medium text-primary transition-colors hover:border-action/40 hover:text-action"
                >
                  <span className="flex items-center gap-1">
                    <Icon name="file" size={12} />
                    PDF
                  </span>
                </button>
                <button
                  type="button"
                  onClick={() => void handleExportIdeaDocx()}
                  aria-label={t("ideas.detail.exportDocxAria")}
                  className="rounded-md border border-edge bg-surface px-2.5 py-1 text-xs font-medium text-primary transition-colors hover:border-action/40 hover:text-action"
                >
                  <span className="flex items-center gap-1">
                    <Icon name="file" size={12} />
                    DOCX
                  </span>
                </button>
              </div>
            </div>
            <dl className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted">
              <div>
                <dt className="inline">{t("ideas.detail.origin")}</dt>
                <dd className="inline">{t(SOURCE_LABELS[selectedIdea.source])}</dd>
              </div>
              <div>
                <dt className="inline">{t("ideas.detail.created")}</dt>
                <dd className="inline">{new Date(selectedIdea.timestamp).toLocaleString()}</dd>
              </div>
              {selectedIdea.tags.length > 0 && (
                <div>
                  <dt className="inline">{t("ideas.detail.tags")}</dt>
                  <dd className="inline">{selectedIdea.tags.join(", ")}</dd>
                </div>
              )}
              {selectedIdea.used_in.length > 0 && (
                <div>
                  <dt className="inline">{t("ideas.detail.usedIn")}</dt>
                  <dd className="inline">{selectedIdea.used_in.join(", ")}</dd>
                </div>
              )}
            </dl>
          </header>

          {/* Body rendered as GFM markdown (R-1). Frontmatter is stripped
              inside MarkdownViewer (splitFrontmatter); no `mundo` prop by
              design — /api/ideas/media/... embeds pass through MarkdownImage.
              imageFit="contain" keeps exact proportions (no crop) so images
              of any resolution render consistently in the idea bank. */}
          <div className="mb-6">
            <MarkdownViewer content={selectedIdea.body} imageFit="contain" />
          </div>

          {/* Attach image (POST /api/ideas/{slug}/media) — a <label> styled
              as a button opens the hidden file input; the embed is added to
              the body server-side, so only the three SWR keys refresh. */}
          <section aria-label={t("ideas.detail.imageSectionAria")} className="mb-4 rounded-lg border border-edge bg-surface-raised p-4">
            <h3 className="mb-2 text-body font-medium text-primary">{t("ideas.detail.imageHeading")}</h3>
            {selectedIdea.media_path ? (
              <p className="mb-2 text-xs text-muted">
                {t("ideas.detail.hasImage", { name: selectedIdea.media_path.split("/").pop() ?? "" })}
              </p>
            ) : (
              <p className="mb-2 text-xs text-muted">{t("ideas.detail.noImage")}</p>
            )}
            <label className="inline-flex cursor-pointer items-center gap-1.5 rounded-md bg-action px-3 py-1.5 text-xs font-medium text-action-text transition-colors hover:bg-action-hover">
              <Icon name="image" size={13} />
              {attachingMedia
                ? t("ideas.detail.attaching")
                : selectedIdea.media_path
                  ? t("ideas.detail.replaceImage")
                  : t("ideas.detail.attachImage")}
              <input
                type="file"
                accept="image/*"
                className="hidden"
                disabled={attachingMedia}
                onChange={handleAttachMedia}
              />
            </label>
          </section>

          {/* Edit title */}
          <section aria-label={t("ideas.detail.titleSectionAria")} className="mb-4 rounded-lg border border-edge bg-surface-raised p-4">
            <h3 className="mb-2 text-body font-medium text-primary">{t("ideas.detail.titleHeading")}</h3>
            <div className="flex flex-wrap items-center gap-2">
              <input
                id="edit-idea-title"
                value={editTitle}
                onChange={(e) => setEditTitle(e.target.value)}
                placeholder={t("ideas.detail.titlePlaceholder")}
                className="min-w-0 flex-1 rounded-md border border-edge bg-surface px-2.5 py-1.5 text-xs text-primary placeholder:text-muted focus:border-action focus:outline-none focus:ring-1 focus:ring-action/50"
              />
              <button
                type="button"
                onClick={() => void handleEditTitle()}
                disabled={savingTitle || editTitle.trim() === (selectedIdea.title ?? "")}
                className="rounded-md bg-action px-3 py-1.5 text-xs font-medium text-action-text transition-colors hover:bg-action-hover disabled:cursor-not-allowed disabled:opacity-50"
              >
                {savingTitle ? t("ideas.detail.saving") : t("ideas.detail.saveTitle")}
              </button>
            </div>
          </section>

          {/* Reclassify */}
          <section aria-label={t("ideas.detail.reclassifyAria")} className="mb-4 rounded-lg border border-edge bg-surface-raised p-4">
            <h3 className="mb-2 text-body font-medium text-primary">{t("ideas.detail.classification")}</h3>
            <div className="flex flex-wrap items-center gap-2">
              <select
                aria-label={t("ideas.detail.typeAria")}
                value={reclassifyType}
                onChange={(e) => setReclassifyType(e.target.value as IdeaType)}
                className="rounded-md border border-edge bg-surface px-2.5 py-1.5 text-xs text-primary focus:border-action focus:outline-none focus:ring-1 focus:ring-action/50"
              >
                {IDEA_TYPES.map((type) => (
                  <option key={type} value={type}>
                    {t(TYPE_LABELS[type])}
                  </option>
                ))}
              </select>
              <button
                type="button"
                onClick={() => void handleReclassify()}
                disabled={reclassifying || reclassifyType === selectedIdea.type}
                className="rounded-md bg-action px-3 py-1.5 text-xs font-medium text-action-text transition-colors hover:bg-action-hover disabled:cursor-not-allowed disabled:opacity-50"
              >
                {reclassifying ? t("ideas.detail.saving") : t("ideas.detail.saveType")}
              </button>
            </div>
          </section>

          {/* Materialize */}
          <section aria-label={t("ideas.materialize.sectionAria")} className="mb-4 rounded-lg border border-edge bg-surface-raised p-4">
            <h3 className="mb-2 text-body font-medium text-primary">
              {t("ideas.materialize.heading")}
            </h3>
            {materializeFor !== selectedIdea.slug ? (
              <button
                type="button"
                onClick={openMaterialize}
                className="flex items-center gap-1.5 rounded-md border border-edge px-3 py-1.5 text-xs text-muted transition-colors hover:border-action/40 hover:text-primary"
              >
                <Icon name="world" size={13} />
                {t("ideas.materialize.button")}
              </button>
            ) : (
              <div className="space-y-2">
                <div>
                  <label htmlFor="materialize-world" className="mb-1 block text-xs text-muted">
                    {t("ideas.materialize.worldLabel")}
                  </label>
                  <select
                    id="materialize-world"
                    value={materializeWorld}
                    onChange={(e) => setMaterializeWorld(e.target.value)}
                    className="w-full rounded-md border border-edge bg-surface px-2.5 py-1.5 text-xs text-primary focus:border-action focus:outline-none focus:ring-1 focus:ring-action/50"
                  >
                    <option value="">{t("ideas.materialize.worldPlaceholder")}</option>
                    {worlds.map((world) => (
                      <option key={world.name} value={world.name}>
                        {world.name}
                      </option>
                    ))}
                  </select>
                </div>
                <div>
                  <label htmlFor="materialize-section" className="mb-1 block text-xs text-muted">
                    {t("ideas.materialize.sectionLabel")}
                  </label>
                  <select
                    id="materialize-section"
                    value={materializeSection}
                    onChange={(e) => {
                      setMaterializeSection(e.target.value as MaterializeSection);
                      setMaterializeFolder("");
                    }}
                    className="w-full rounded-md border border-edge bg-surface px-2.5 py-1.5 text-xs text-primary focus:border-action focus:outline-none focus:ring-1 focus:ring-action/50"
                  >
                    {MATERIALIZE_SECTIONS.map((section) => (
                      <option key={section} value={section}>
                        {t(SECTION_LABELS[section])}
                      </option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="mb-1 block text-xs text-muted">
                    {t("ideas.materialize.folderLabel")}
                  </label>
                  <div className="max-h-40 overflow-y-auto rounded-md border border-edge bg-surface px-2 py-1.5">
                    <button
                      type="button"
                      onClick={() => setMaterializeFolder("")}
                      aria-pressed={materializeFolder === ""}
                      className="flex w-full items-center gap-1.5 rounded-md px-2 py-1 text-left text-xs text-primary transition-colors hover:bg-surface-hover aria-pressed:bg-action/15 aria-pressed:text-action"
                    >
                      <Icon name="folder" size={12} className="shrink-0 opacity-70" />
                      <span>{t("ideas.materialize.root")}</span>
                    </button>
                    {folderLoading ? (
                      <p className="px-2 py-1 text-xs text-muted">
                        {t("ideas.materialize.loadingFolders")}
                      </p>
                    ) : (
                      <FolderTree
                        nodes={folderNodes}
                        selected={materializeFolder}
                        onSelect={setMaterializeFolder}
                      />
                    )}
                  </div>
                </div>
                <div>
                  <label htmlFor="materialize-title-hint" className="mb-1 block text-xs text-muted">
                    {t("ideas.materialize.titleHintLabel")}
                  </label>
                  <input
                    id="materialize-title-hint"
                    value={materializeTitleHint}
                    onChange={(e) => setMaterializeTitleHint(e.target.value)}
                    placeholder={t("ideas.materialize.titleHintPlaceholder")}
                    className="w-full rounded-md border border-edge bg-surface px-2.5 py-1.5 text-xs text-primary placeholder:text-muted focus:border-action focus:outline-none focus:ring-1 focus:ring-action/50"
                  />
                </div>
                <div className="flex flex-wrap gap-2">
                  <button
                    type="button"
                    onClick={() => void handlePreview()}
                    disabled={previewing || !materializeWorld}
                    className="rounded-md bg-action px-3 py-1.5 text-xs font-medium text-action-text transition-colors hover:bg-action-hover disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {previewing
                      ? t("ideas.materialize.previewing")
                      : t("ideas.materialize.preview")}
                  </button>
                  <button
                    type="button"
                    onClick={() => void handleMarkUsedOnly()}
                    disabled={markingUsed || !materializeWorld}
                    className="rounded-md border border-edge px-3 py-1.5 text-xs text-muted transition-colors hover:border-action/40 hover:text-primary disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {markingUsed
                      ? t("ideas.materialize.markingUsed")
                      : t("ideas.materialize.markUsedOnly")}
                  </button>
                  <button
                    type="button"
                    onClick={closeMaterialize}
                    disabled={previewing || confirming || markingUsed}
                    className="rounded-md border border-edge px-3 py-1.5 text-xs text-muted transition-colors hover:border-action/40 hover:text-primary disabled:opacity-50"
                  >
                    {t("ideas.materialize.cancel")}
                  </button>
                </div>
              </div>
            )}
          </section>

          {/* Version history (R-10) — archived versions only. The live
              frontmatter `version` is never shown here nor in the body
              (MarkdownViewer strips frontmatter); this panel is the product
              value: consultable archive of every prior version. */}
          <section
            aria-label={t("ideas.detail.versionsAria")}
            className="mb-4 rounded-lg border border-edge bg-surface-raised p-4"
          >
            <h3 className="mb-2 text-body font-medium text-primary">
              {t("ideas.detail.versionsHeading")}
            </h3>
            {versionsError ? (
              <p className="text-xs text-status-error">
                {getErrorMessage(
                  (versionsError as ApiError).status,
                  (versionsError as ApiError).detail,
                )}
              </p>
            ) : archivedVersions.length === 0 ? (
              <p className="text-xs text-muted">
                {t("ideas.detail.noVersions")}
              </p>
            ) : (
              <ul aria-label={t("ideas.detail.archivedAria")} className="space-y-1">
                {archivedVersions.map((v) => (
                  <li
                    key={v.version}
                    className="flex items-baseline justify-between gap-2 rounded-md bg-surface px-2.5 py-1.5 text-xs"
                  >
                    <span className="shrink-0 font-medium text-primary">
                      {t("ideas.detail.version", { version: v.version })}
                    </span>
                    <span
                      className="min-w-0 truncate text-muted"
                      title={v.path}
                    >
                      {v.path}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </section>

          {/* Delete */}
          <div className="flex justify-end border-t border-edge pt-4">
            <button
              type="button"
              onClick={() => void handleDelete()}
              disabled={deleting}
              className="flex items-center gap-1.5 rounded-md border border-status-error/30 px-3 py-1.5 text-xs text-status-error transition-colors hover:bg-status-error/10 disabled:opacity-50"
              aria-label={t("ideas.detail.deleteAria", { slug: selectedIdea.slug })}
            >
              <Icon name="trash" size={13} />
              {deleting ? t("ideas.detail.deleting") : t("ideas.detail.delete")}
            </button>
          </div>
        </article>
      )}
    </div>
  );

  // ── Right panel: persistent assistant (null-mundo) ───────────────────────
  const contextPanel = (
    <div className="flex min-h-0 flex-1 flex-col overflow-y-auto px-4 py-4">
      <h2 className="mb-2 text-body font-medium text-primary">{t("ideas.context.heading")}</h2>
      <p className="text-xs leading-relaxed text-muted">
        {t("ideas.context.body")}
      </p>
      <dl className="mt-4 space-y-2 text-xs text-muted">
        <div className="flex justify-between">
          <dt>{t("ideas.context.bankCount")}</dt>
          <dd className="text-primary">{ideas.length}</dd>
        </div>
        {selectedIdea && (
          <>
            <div className="flex justify-between">
              <dt>{t("ideas.context.selected")}</dt>
              <dd className="text-primary">{selectedIdea.slug}</dd>
            </div>
            <div className="flex justify-between">
              <dt>{t("ideas.context.status")}</dt>
              <dd className="text-primary">{t(STATUS_LABELS[selectedIdea.status])}</dd>
            </div>
          </>
        )}
      </dl>
    </div>
  );

  const rightPanel = (
    <div className="flex h-full flex-col">
      <TabBar onTabChange={setSidebarTab} />
      {sidebarTab === "asistente" ? (
        <AIAssistantSidebar />
      ) : (
        contextPanel
      )}
    </div>
  );

  return (
    <EditorLayout
      sidebar={sidebar}
      rightPanel={rightPanel}
    >
      {(actionError || toast) && (
        <div className="mb-4">
          {actionError && (
            <div role="alert" className="rounded-lg border border-status-error/30 bg-status-error/10 px-3 py-2 text-xs text-status-error">
              {actionError}
            </div>
          )}
          {toast && (
            <div role="status" className="rounded-lg border border-action/30 bg-action/10 px-3 py-2 text-xs text-primary">
              {toast}
            </div>
          )}
        </div>
      )}
      {main}

      {/* Export to PDF dialog — opened from the detail header "PDF" button.
          mundo="" keeps the idea's absolute /api/ideas/... image URLs
          untouched (MarkdownImage passes them through unchanged). */}
      {pdfTarget && (
        <ExportPdfDialog
          open={!!pdfTarget}
          onClose={() => setPdfTarget(null)}
          content={pdfTarget.content}
          fileName={pdfTarget.fileName}
          mundo=""
        />
      )}

      {/* Materialize preview dialog — read-only (AD8); opens on a successful
          preview or on a 409 collision suggestion (AD5). */}
      {(preview || collision) && (
        <MaterializePreviewDialog
          preview={preview}
          collision={collision}
          confirming={confirming}
          onConfirm={() => void handleConfirmPreview()}
          onClose={() => {
            setPreview(null);
            setCollision(null);
          }}
        />
      )}
    </EditorLayout>
  );
}