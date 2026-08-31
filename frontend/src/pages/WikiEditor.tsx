import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useWorlds } from "@/hooks/useWorlds";
import { WorldNotFound } from "@/components/organisms/WorldNotFound";
import { useFileTree } from "@/hooks/useFileTree";
import { useFileContent } from "@/hooks/useFileContent";
import { useImageUpload } from "@/hooks/useImages";
import { EditorLayout } from "@/components/templates/EditorLayout";
import { FileTree } from "@/components/organisms/FileTree";
import { MarkdownViewer } from "@/components/organisms/MarkdownViewer";
import {
  SectionCards,
  findTreeNode,
  type CreateTarget,
} from "@/components/organisms/SectionCards";
import type { CardAction } from "@/components/organisms/CardMenu";
import { MoveModal } from "@/components/organisms/MoveModal";
import { MoveToSectionDialog } from "@/components/organisms/MoveToSectionDialog";
import { ExportPdfDialog } from "@/components/organisms/ExportPdfDialog";
import { ConfirmDialog } from "@/components/organisms/ConfirmDialog";
import { Toast } from "@/components/atoms/Toast";
import { EntitySearchPanel } from "@/components/organisms/EntitySearchPanel";
import {
  AIAssistantSidebar,
  type AssistantEditRequest,
} from "@/components/organisms/AIAssistantSidebar";
import { PapeleraPanel } from "@/components/organisms/PapeleraPanel";
import { HistoryPanel } from "@/components/organisms/HistoryPanel";
import { TabBar } from "@/components/molecules/TabBar";
import type { SidebarTab } from "@/components/molecules/TabBar";
import { SectionTabs } from "@/components/molecules/SectionTabs";
import { Breadcrumb } from "@/components/molecules/Breadcrumb";
import { StatusBadge } from "@/components/molecules/StatusBadge";
import { EmptyState } from "@/components/organisms/EmptyState";
import { ErrorBanner } from "@/components/organisms/ErrorBanner";
import { Spinner } from "@/components/atoms/Spinner";
import { Icon } from "@/components/atoms/Icon";
import { Button } from "@/components/atoms/Button";
import { ImagePicker } from "@/components/organisms/ImagePicker";
import { ImportImageModal } from "@/components/organisms/ImportImageModal";
import { VALID_SECTIONS, SECTION_LABELS, MOVE_DESTINATION_LABELS } from "@/lib/constants";
import type { MoveDestinationSection, Section } from "@/lib/constants";
import { decodePathSegment, getErrorMessage } from "@/lib/utils";
import { parentPath } from "@/lib/dnd";
import { getCurrentWorld, setCurrentWorld } from "@/lib/currentWorld";
import {
  splitFrontmatter,
  mergeFrontmatter,
  setPortada,
  parseFrontmatterStatus,
} from "@/lib/frontmatter";
import {
  createFileConfirmed,
  deleteFile,
  duplicateFile,
  getFileContent,
  moveNode,
  saveFile,
  saveFileConfirmed,
  setStatus,
} from "@/api/wiki";
import type {
  ApiError,
  EditProposal,
  FichaStatus,
  FileNode,
  FileContent,
} from "@/api/types";
import { useEditReview } from "@/hooks/useEditReview";

// CodeMirror is heavy (~300KB) — load the live diff editor only when the
// preview is actually opened, keeping the initial bundle lean.
const LiveDiffEditor = lazy(() => import("@/components/organisms/LiveDiffEditor"));

// Type-only import of the imperative handle — erased at runtime, so it does
// not pull the lazy chunk into the initial bundle.
import type { LiveDiffEditorHandle } from "@/components/organisms/LiveDiffEditor";

/**
 * Wiki Editor page (`/wiki/:mundo/:section/*path`).
 *
 * States:
 * - 🔴 Invalid section: ErrorBanner with link back
 * - 🟡 Loading world list: Spinner
 * - 🟢 Ready: EditorLayout with FileTree sidebar + MarkdownViewer + Breadcrumb
 *
 * Edit mode: "Editar" switches to a textarea. The toolbar offers
 * [Cancelar] [Vista previa] [Guardar]. "Vista previa" swaps the textarea
 * for a live diff view — original on the left (red, read-only), editable
 * draft on the right (green): you click a line and type directly in the
 * diff, and it recomputes on every keystroke. Wikilinks from the Contexto
 * panel insert at the caret of the focused diff line through the
 * imperative `insertText` handle (appended at the end when nothing is
 * focused). "Guardar" persists via POST /save and exits edit mode.
 *
 * The YAML frontmatter of wiki fichas is agent-only metadata: it never
 * appears in the editor, the diff, or the viewer. Only the body is
 * displayed/edited; the raw block is re-merged on save so the file on
 * disk stays byte-identical.
 */
export default function WikiEditor() {
  const navigate = useNavigate();
  const { mundo, section, "*": splatPath } = useParams<{
    mundo: string;
    section: string;
    "*"?: string;
  }>();

  // Edit mode state
  const [isEditing, setIsEditing] = useState(false);
  const [editedContent, setEditedContent] = useState<string | null>(null);

  // Split preview state — toggles the LiveDiffEditor merge view
  const [previewOpen, setPreviewOpen] = useState(false);

  // Save state
  const [isSaving, setIsSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saveSuccess, setSaveSuccess] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [pendingNewFile, setPendingNewFile] = useState<{ path: string } | null>(
    null,
  );

  // Textarea ref for wikilink cursor insertion
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Live diff imperative handle — wikilink insertion while the preview is open
  const liveDiffRef = useRef<LiveDiffEditorHandle>(null);

  // Image picker modal state — reachable only from the editing toolbar
  const [showPicker, setShowPicker] = useState(false);

  // Import image modal state — reachable from the file bar in view mode
  const [showImportModal, setShowImportModal] = useState(false);

  // Focus mode — hides both side panels for distraction-free editing
  const [focusMode, setFocusMode] = useState(false);

  // Papelera (trash) panel — restore / purge / empty of deleted entries
  const [trashOpen, setTrashOpen] = useState(false);

  // File-bar options dropdown (⋯) for ficha-level actions like delete.
  // Controlled open state + ref for the outside-click/Escape close pattern
  // (mirrors CardMenu). Sits between the status chip and the focus button.
  const [optionsOpen, setOptionsOpen] = useState(false);
  const optionsRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!optionsOpen) return;
    const handleMousedown = (e: MouseEvent) => {
      if (optionsRef.current && !optionsRef.current.contains(e.target as Node)) {
        setOptionsOpen(false);
      }
    };
    const handleKeydown = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOptionsOpen(false);
    };
    document.addEventListener("mousedown", handleMousedown);
    document.addEventListener("keydown", handleKeydown);
    return () => {
      document.removeEventListener("mousedown", handleMousedown);
      document.removeEventListener("keydown", handleKeydown);
    };
  }, [optionsOpen]);

  // ── Card action state (⋯ menu flows) ──────────────────────────────────
  // Cards view (browsingDir) is mutually exclusive with edit mode — the
  // editor only renders SectionCards when no file is selected, so none of
  // these flows can ever run against an unsaved draft (S33).
  const [coverTarget, setCoverTarget] = useState<string | null>(null);
  const [moveSource, setMoveSource] = useState<{
    section: string;
    path: string;
  } | null>(null);
  /** "Mover a sección…" dialog target (cross-section move, no undo). */
  const [moveSectionTarget, setMoveSectionTarget] = useState<{
    section: string;
    path: string;
  } | null>(null);
  /** Transient move feedback — auto-cleared after a short delay. */
  const [toast, setToast] = useState<{
    message: string;
    kind: "success" | "error";
  } | null>(null);
  /** Path of the node that briefly highlights (fade-slide-in) after a move. */
  const [movedPath, setMovedPath] = useState<string | null>(null);
  const [trashTarget, setTrashTarget] = useState<string | null>(null);
  /** "Exportar Ficha a PDF" dialog target — content + basename of the open ficha. */
  const [exportTarget, setExportTarget] = useState<{
    content: string;
    fileName: string;
  } | null>(null);
  const [renamingPath, setRenamingPath] = useState<string | null>(null);
  const [createTarget, setCreateTarget] = useState<CreateTarget | null>(null);
  /** Path of the node whose request is in flight — its menu actions disable (S14). */
  const [busyPath, setBusyPath] = useState<string | null>(null);
  /** Latest action error (ApiError.detail mapped) — shown inline, tree untouched (S34/S36). */
  const [actionError, setActionError] = useState<string | null>(null);

  // Image upload (DropZone in view mode) — uploads + revalidates the gallery
  const { upload, isUploading, uploadError } = useImageUpload(mundo ?? "");

  // Sidebar tab state — persisted in sessionStorage by TabBar
  const [sidebarTab, setSidebarTab] = useState<SidebarTab>(() => {
    if (typeof window === "undefined") return "asistente";
    const stored = sessionStorage.getItem("sidebar-tab");
    if (stored === "asistente" || stored === "contexto") return stored;
    return "asistente";
  });

  // Decode the path from URL encoding
  const filePath = splatPath ? decodePathSegment(splatPath) : undefined;
  const reviewPath = pendingNewFile?.path ?? filePath;

  // Validate section
  const sectionValid = section && VALID_SECTIONS.includes(section as typeof VALID_SECTIONS[number]);

  // Worlds (for world validation — the Navbar selector is hoisted to AppLayout)
  const { worlds, isLoading: worldsLoading } = useWorlds();

  // World not found (loaded worlds, but this one doesn't exist)
  const worldExists = worlds.some((w) => w.name === mundo);

  // Opening a valid route marks `mundo` as the active world (same-tab
  // localStorage) without navigating back.
  useEffect(() => {
    if (mundo && worldExists && getCurrentWorld() !== mundo) {
      setCurrentWorld(mundo);
    }
  }, [mundo, worldExists]);

  // File tree for the sidebar
  const {
    nodes: treeNodes,
    isLoading: treeLoading,
    error: treeError,
    mutate: retryTree,
  } = useFileTree(mundo, sectionValid ? section : undefined);

  // File content for the markdown viewer
  const {
    file,
    revision,
    isLoading: contentLoading,
    error: contentError,
    mutate: retryContent,
  } = useFileContent(
    mundo,
    sectionValid ? section : undefined,
    filePath,
  );

  const review = useEditReview({
    mundo,
    section: sectionValid ? section : undefined,
    path: reviewPath,
  });

  // Content to display/edit — the YAML frontmatter is agent-only metadata
  // and is hidden from every user-facing surface (editor, diff, viewer).
  // `body` is the displayable baseline; the raw `frontmatter` block is kept
  // aside (re-derived only when the file content changes, so it survives
  // edits) and re-merged on save to keep the on-disk file byte-identical.
  const { frontmatter, body } = useMemo(
    () => splitFrontmatter(file?.content ?? ""),
    [file?.content],
  );

  // OKF status shown in the file-bar chip — parsed from the frontmatter of
  // the OPEN file. Files without a `status:` field default to Canon
  // (stable), coherent with OKF fichas. After a mutation the content is
  // revalidated so the chip always reflects the on-disk truth.
  const fichaStatus: FichaStatus = useMemo(
    () => parseFrontmatterStatus(file?.content ?? "") ?? "stable",
    [file?.content],
  );

  // Baseline body — used for change detection and as the diff `original`
  const currentContent = body;
  const baseRevision = revision ?? file?.revision ?? null;

  // Initialise edited content when file path actually changes.
  // MUST use useEffect + useRef, NOT setState during render:
  // React 18 StrictMode double-invokes the component function, and a
  // setState during render would overwrite the user's edits with the
  // original file content. Effect runs AFTER commit, outside StrictMode's
  // double-invocation path.
  const prevFilePathRef = useRef<string | undefined>();
  useEffect(() => {
    if (filePath && filePath !== prevFilePathRef.current && currentContent) {
      setEditedContent(currentContent);
      prevFilePathRef.current = filePath;
    }
  }, [filePath, currentContent]);

  // Breadcrumb segments
  const breadcrumbSegments = useMemo(() => {
    const segs: string[] = [];
    if (mundo) segs.push(mundo);
    if (section) segs.push(section);
    if (filePath) {
      const parts = filePath.split("/");
      segs.push(...parts);
    }
    return segs;
  }, [mundo, section, filePath]);

  // Breadcrumb click handler: navigate to that directory level
  const handleBreadcrumbClick = useCallback(
    (index: number) => {
      if (!mundo || !section) return;

      if (index === 0) {
        // World chip → world page with the section cards
        navigate(`/wiki/${encodeURIComponent(mundo)}`);
        return;
      }
      if (index === 1) {
        // Section chip → section root (embedded section cards)
        navigate(`/wiki/${encodeURIComponent(mundo)}/${section}`);
        return;
      }

      const pathParts = breadcrumbSegments.slice(2, index + 1);
      const newPath = pathParts.map((s) => encodeURIComponent(s)).join("/");
      navigate(`/wiki/${encodeURIComponent(mundo)}/${section}/${newPath}`);
    },
    [mundo, section, navigate, breadcrumbSegments],
  );

  // File tree node click: navigate to the selected file
  const handleFileSelect = useCallback(
    (path: string) => {
      if (!mundo || !section) return;
      const encodedPath = path.split("/").map((s) => encodeURIComponent(s)).join("/");
      navigate(`/wiki/${encodeURIComponent(mundo)}/${section}/${encodedPath}`);
    },
    [mundo, section, navigate],
  );

  // ── Card ⋯ action flows (T16) ─────────────────────────────────────────
  // All mutation handlers follow the same contract (S34/S36): tree/content
  // state is untouched until the request succeeds (SWR keeps the stale
  // cache on failure); `busyPath` disables the node's actions while its
  // request is in flight (S14) and is cleared in `finally`.

  /** Duplicate a file (S21-S23): POST duplicate → refresh tree. */
  const handleDuplicate = useCallback(
    async (node: FileNode) => {
      if (!mundo || !section) return;
      setBusyPath(node.path);
      setActionError(null);
      try {
        await duplicateFile(mundo, node.path);
        await retryTree();
      } catch (err) {
        const apiErr = err as ApiError;
        setActionError(getErrorMessage(apiErr.status, apiErr.detail));
      } finally {
        setBusyPath(null);
      }
    },
    [mundo, section, retryTree],
  );

  /**
   * Rename commit (S8): rename is a same-parent move via POST move (D6).
   * If the currently open file lives under the renamed path, navigate back
   * to the section root — it no longer exists at the old location.
   */
  const handleRenameCommit = useCallback(
    async (node: FileNode, newName: string) => {
      if (!mundo || !section) return;
      // The tree returns section-relative paths (`node.path` has no `lore/`
      // prefix), but the move endpoint requires mundo-relative paths whose
      // first segment is a valid section. Prepend the active section so the
      // backend can resolve `from`/`to` instead of rejecting them (400).
      const from = section ? `${section}/${node.path}` : node.path;
      const parentDir = from.includes("/")
        ? from.slice(0, from.lastIndexOf("/"))
        : "";
      const to = parentDir ? `${parentDir}/${newName}` : newName;
      setBusyPath(from);
      setActionError(null);
      try {
        await moveNode(mundo, from, to);
        await retryTree();
        if (
          filePath &&
          (filePath === from || filePath.startsWith(from + "/"))
        ) {
          navigate(`/wiki/${encodeURIComponent(mundo)}/${section}`);
        }
      } catch (err) {
        const apiErr = err as ApiError;
        setActionError(getErrorMessage(apiErr.status, apiErr.detail));
      } finally {
        setBusyPath(null);
        setRenamingPath(null);
      }
    },
    [mundo, section, filePath, navigate, retryTree],
  );

  /**
   * Move confirm (S9): POST move with the mundo-relative destination.
   * `destPath` is a destination DIRECTORY (section root or section/folder,
   * as MoveModal emits) — the source basename is appended so the backend
   * receives the final target path (e.g. `lore/ciudades/Cultura.md`).
   * Moving to the folder the node already lives in is a no-op.
   */
  const handleMoveConfirm = useCallback(
    async (destPath: string) => {
      if (!mundo || !section || !moveSource) return;
      const from = `${moveSource.section}/${moveSource.path}`;
      const movedPath = moveSource.path;
      const name = moveSource.path.split("/").pop() ?? "";
      const to = `${destPath}/${name}`;
      if (to === from) {
        setMoveSource(null);
        setToast({
          message: "El archivo ya está en esa carpeta",
          kind: "success",
        });
        return;
      }
      setMoveSource(null);
      setBusyPath(movedPath);
      setActionError(null);
      try {
        await moveNode(mundo, from, to);
        await retryTree();
        if (
          filePath &&
          (filePath === movedPath || filePath.startsWith(movedPath + "/"))
        ) {
          navigate(`/wiki/${encodeURIComponent(mundo)}/${section}`);
        }
      } catch (err) {
        const apiErr = err as ApiError;
        setActionError(getErrorMessage(apiErr.status, apiErr.detail));
      } finally {
        setBusyPath(null);
      }
    },
    [mundo, section, moveSource, filePath, navigate, retryTree],
  );

  /**
   * Drag & drop move (tree + cards, same section): from/to are
   * section-relative paths; the world-relative form is `${section}/{path}`.
   * The destination is a FULL path (folder + name) — the move endpoint
   * treats `to` as the target location and rejects existing destinations.
   * On success: tree refresh, success toast, brief highlight of the node in
   * its new position, and the open-file navigation guard.
   */
  const handleDropMove = useCallback(
    async (from: string, to: string) => {
      if (!mundo || !section) return;
      setBusyPath(from);
      setActionError(null);
      try {
        await moveNode(mundo, `${section}/${from}`, `${section}/${to}`);
        await retryTree();
        const parent = parentPath(to);
        const targetLabel = parent
          ? `${parent}/`
          : `${SECTION_LABELS[section as Section]}/`;
        setToast({ message: `Movido a ${targetLabel}`, kind: "success" });
        setMovedPath(to);
        if (
          filePath &&
          (filePath === from || filePath.startsWith(from + "/"))
        ) {
          navigate(`/wiki/${encodeURIComponent(mundo)}/${section}`);
        }
      } catch (err) {
        const apiErr = err as ApiError;
        const message = getErrorMessage(apiErr.status, apiErr.detail);
        setActionError(message);
        setToast({ message, kind: "error" });
      } finally {
        setBusyPath(null);
      }
    },
    [mundo, section, filePath, navigate, retryTree],
  );

  /**
   * Cross-section move confirm (⋯ menu "Mover a sección…"): the relative
   * path is preserved inside the destination section. Irreversible — the
   * dialog warns before this handler can run.
   */
  const handleMoveToSectionConfirm = useCallback(
    async (destSection: MoveDestinationSection) => {
      if (!mundo || !section || !moveSectionTarget) return;
      const { path } = moveSectionTarget;
      setMoveSectionTarget(null);
      setBusyPath(path);
      setActionError(null);
      try {
        await moveNode(mundo, `${section}/${path}`, `${destSection}/${path}`);
        await retryTree();
        setToast({
          message: `Movido a ${MOVE_DESTINATION_LABELS[destSection]}/`,
          kind: "success",
        });
        if (filePath && (filePath === path || filePath.startsWith(path + "/"))) {
          navigate(`/wiki/${encodeURIComponent(mundo)}/${section}`);
        }
      } catch (err) {
        const apiErr = err as ApiError;
        const message = getErrorMessage(apiErr.status, apiErr.detail);
        setActionError(message);
        setToast({ message, kind: "error" });
      } finally {
        setBusyPath(null);
      }
    },
    [mundo, section, moveSectionTarget, filePath, navigate, retryTree],
  );

  /** Delete confirm (S12): DELETE moves the node to the trash → refresh tree. */
  const handleTrashConfirm = useCallback(
    async () => {
      if (!mundo || !section || !trashTarget) return;
      const target = trashTarget;
      setBusyPath(target);
      setActionError(null);
      try {
        await deleteFile(mundo, section, target);
        setTrashTarget(null);
        await retryTree();
        if (
          filePath &&
          (filePath === target || filePath.startsWith(target + "/"))
        ) {
          // Item 10: land on the folder that contained the deleted node —
          // same parentDir pattern as handleRenameCommit — instead of the
          // section root. Empty parentDir falls back to the section root.
          const parentDir = target.includes("/")
            ? target.slice(0, target.lastIndexOf("/"))
            : "";
          const encodedParent = parentDir
            ? parentDir
                .split("/")
                .map((s) => encodeURIComponent(s))
                .join("/")
            : "";
          navigate(
            encodedParent
              ? `/wiki/${encodeURIComponent(mundo)}/${section}/${encodedParent}`
              : `/wiki/${encodeURIComponent(mundo)}/${section}`,
          );
        }
      } catch (err) {
        const apiErr = err as ApiError;
        setActionError(getErrorMessage(apiErr.status, apiErr.detail));
      } finally {
        setBusyPath(null);
      }
    },
    [mundo, section, trashTarget, filePath, navigate, retryTree],
  );

  /**
   * New file / new subfolder commit (S10, D7): reuse the existing
   * create_file endpoint; a subfolder is materialized by its invisible
   * `_README.md` placeholder (create_file writes text, so an empty folder
   * would fail; `_`-prefixed files stay invisible to tree/graph).
   * `createTarget.path` is the directory being browsed — empty at the
   * section root, so the target path is built without a prefix there.
   */
  const handleCreateCommit = useCallback(
    async (name: string) => {
      if (!mundo || !section || !createTarget) return;
      const dirPath = createTarget.path;
      const base = dirPath ? `${dirPath}/` : "";
      const targetPath =
        createTarget.kind === "subfolder"
          ? `${base}${name}/_README.md`
          : `${base}${name}`;
      setActionError(null);
      setCreateTarget(null);
      setPendingNewFile({ path: targetPath });
      setEditedContent("");
      setPreviewOpen(false);
      setIsEditing(true);
    },
    [createTarget, mundo, section],
  );

  /**
   * Set cover (S32): getFileContent (raw) → setPortada (line-preserving
   * frontmatter edit) → saveFile → refresh the tree so the card shows the
   * new cover. Cards view is mutually exclusive with edit mode (S33), so
   * there is never an unsaved draft in play here.
   */
  const handleCoverSelect = useCallback(
    async (mediaPath: string) => {
      if (!mundo || !section || !coverTarget) return;
      const target = coverTarget;
      setCoverTarget(null);
      setBusyPath(target);
      setActionError(null);
      try {
        const file = await getFileContent(mundo, section, target);
        const updated = setPortada(file.content, mediaPath);
        await saveFile(mundo, section, target, updated);
        await retryTree();
      } catch (err) {
        const apiErr = err as ApiError;
        setActionError(getErrorMessage(apiErr.status, apiErr.detail));
      } finally {
        setBusyPath(null);
      }
    },
    [mundo, section, coverTarget, retryTree],
  );

  /** Route a CardMenu action (S7) to its flow. */
  const handleCardAction = useCallback(
    (action: CardAction, node: FileNode) => {
      // Fresh error context for every action; the tree stays untouched.
      setActionError(null);
      switch (action) {
        case "open":
          handleFileSelect(node.path);
          break;
        case "set-cover":
          setCoverTarget(node.path);
          break;
        case "rename":
          setRenamingPath(node.path);
          break;
        case "move":
          setMoveSource({ section: section!, path: node.path });
          break;
        case "move-section":
          setMoveSectionTarget({ section: section!, path: node.path });
          break;
        case "duplicate":
          void handleDuplicate(node);
          break;
        case "trash":
          setTrashTarget(node.path);
          break;
      }
    },
    [handleFileSelect, handleDuplicate, section],
  );

  // Resolve the current path against the tree. Directories are browsable —
  // the central area shows their contents as embedded section cards.
  const selectedNode = useMemo(
    () => (filePath ? findTreeNode(treeNodes, filePath) : undefined),
    [filePath, treeNodes],
  );

  // Browsing a directory (or the section root) renders visual cards in the
  // central area instead of the markdown viewer. Files are the only
  // editable/rendered entities — directories have no content of their own.
  const browsingDir = !pendingNewFile && (!filePath || selectedNode?.is_dir === true);
  const browsingNodes = selectedNode?.is_dir ? (selectedNode.children ?? []) : treeNodes;

  // Section tab click: navigate to the section root (resets file path).
  // The tree/content SWR keys include `section`, so both re-fetch on change.
  const handleSectionSelect = useCallback(
    (nextSection: string) => {
      if (!mundo) return;
      navigate(`/wiki/${encodeURIComponent(mundo)}/${nextSection}`);
    },
    [mundo, navigate],
  );

  /**
   * Auto-purge feedback from the trash panel — the lazy 30-day TTL purge
   * result (GET /papelera) surfaces as a toast, mirroring the move-success
   * pattern. Stable so the panel's fetch effect is not re-triggered.
   */
  const handleTtlPurged = useCallback((count: number) => {
    setToast({
      message: `${count} expired entries auto-purged (30-day TTL).`,
      kind: "success",
    });
  }, []);

  // Auto-clear the "Guardado ✓" feedback after a short delay
  useEffect(() => {
    if (!saveSuccess) return;
    const t = setTimeout(() => setSaveSuccess(false), 2500);
    return () => clearTimeout(t);
  }, [saveSuccess]);

  // Auto-clear the move toast after a short delay
  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(null), 2500);
    return () => clearTimeout(t);
  }, [toast]);

  // Auto-clear the post-move highlight once the entrance animation plays
  useEffect(() => {
    if (!movedPath) return;
    const t = setTimeout(() => setMovedPath(null), 600);
    return () => clearTimeout(t);
  }, [movedPath]);

  const startReview = useCallback(
    (proposal: EditProposal) => {
      review.startReview(proposal);
      setPreviewOpen(true);
    },
    [review],
  );

  // Manual drafts and new files enter the same review surface before any write.
  const handleSave = useCallback(() => {
    if (!mundo || !section || (!filePath && !pendingNewFile) || editedContent === null) {
      return;
    }
    const target = pendingNewFile?.path ?? filePath!;
    const proposedContent = pendingNewFile
      ? editedContent
      : mergeFrontmatter(frontmatter, editedContent);
    startReview({
      proposal_id: `manual-${Date.now()}`,
      target: `${section}/${target}`,
      base_revision: pendingNewFile ? "" : baseRevision ?? "",
      proposed_content: proposedContent,
      proposed_digest: "",
      rationale: pendingNewFile ? "Create a new Markdown file" : "Review manual changes",
      is_new_file: pendingNewFile !== null,
    });
    setSaveError(null);
  }, [baseRevision, editedContent, filePath, frontmatter, mundo, pendingNewFile, section, startReview]);

  const handleReviewContentChange = useCallback(
    (nextContent: string) => {
      setEditedContent(nextContent);
      if (review.status === "reviewing") {
        review.updateProposal((proposal) => ({
          ...proposal,
          proposed_content: pendingNewFile
            ? nextContent
            : mergeFrontmatter(frontmatter, nextContent),
        }));
      }
    },
    [frontmatter, pendingNewFile, review.status, review.updateProposal],
  );

  const handleAssistantEditProposal = useCallback(async ({
    prompt,
    sessionId,
  }: AssistantEditRequest) => {
    if (!filePath) return;
    setSaveError(null);
    try {
      const response = await review.suggest(prompt, sessionId);
      if (!response.proposal) {
        setSaveError(response.message ?? "The assistant could not produce a proposal. Use manual editing or chat.");
        return;
      }
      const { body: suggestedBody } = splitFrontmatter(response.proposal.proposed_content);
      setEditedContent(suggestedBody);
      setIsEditing(true);
      setPreviewOpen(true);
    } catch (error) {
      const apiError = error as ApiError;
      setSaveError(getErrorMessage(apiError.status, apiError.detail));
    }
  }, [filePath, review]);

  const handleGuidedReview = useCallback(async (proposal: EditProposal) => {
    if (!mundo || !section || !proposal.is_new_file) return;
    const prefix = `${section}/`;
    if (!proposal.target.startsWith(prefix)) {
      setSaveError("The guided proposal target is outside the current section.");
      return;
    }
    const path = proposal.target.slice(prefix.length);
    setPendingNewFile({ path });
    setEditedContent(proposal.proposed_content);
    setIsEditing(true);
    setPreviewOpen(true);
    review.startReview(proposal);
    setSaveError(null);
  }, [mundo, review, section]);

  const handleRejectReview = useCallback(() => {
    review.reject();
    setPendingNewFile(null);
    setEditedContent(null);
    setPreviewOpen(false);
    setIsEditing(false);
    setSaveError(null);
  }, [review]);

  const handleAcceptReview = useCallback(async () => {
    if (!mundo || !section || !review.proposal || !reviewPath) return;
    const proposal = review.proposal;
    const kind = proposal.is_new_file ? "new" : "edit";
    setIsSaving(true);
    setSaveError(null);
    setSaveSuccess(false);
    try {
      const confirmation = await review.requestConfirmation(proposal.proposal_id, kind);
      const request = {
        content: proposal.proposed_content,
        base_revision: proposal.base_revision || undefined,
        proposed_digest: confirmation.proposed_digest,
        edit_id: proposal.proposal_id,
        token: confirmation.token,
      };
      if (proposal.is_new_file) {
        await createFileConfirmed(mundo, section, reviewPath, request);
        await retryTree();
      } else {
        await saveFileConfirmed(mundo, section, reviewPath, request);
        await retryContent();
      }
      review.reset();
      setPendingNewFile(null);
      setPreviewOpen(false);
      setIsEditing(false);
      setEditedContent(null);
      setSaveSuccess(true);
    } catch (error) {
      const apiError = error as ApiError;
      if (apiError.status === 409) {
        const refreshed = await retryContent();
        const refreshedFile = refreshed as FileContent | undefined;
        const nextBody = refreshedFile?.content !== undefined
          ? splitFrontmatter(refreshedFile.content).body
          : currentContent;
        review.reset();
        setEditedContent(nextBody);
        setPreviewOpen(false);
        setIsEditing(true);
        setSaveError("The file changed while it was under review. It was reloaded; review the changes again.");
      } else {
        review.reset();
        setPreviewOpen(false);
        setIsEditing(true);
        setSaveError(getErrorMessage(apiError.status, apiError.detail));
      }
    } finally {
      setIsSaving(false);
    }
  }, [currentContent, mundo, retryContent, retryTree, review, reviewPath, section]);

  /**
   * Set OKF status (Borrador/Canon): a dedicated POST rewrites ONLY the
   * frontmatter — instant and independent of the save gate. The content is
   * revalidated on success so the chip reflects the on-disk truth (same
   * contract as the card flows: state untouched until the request succeeds).
   */
  const handleStatusChange = useCallback(
    async (next: FichaStatus) => {
      if (!mundo || !section || !filePath) return;
      await setStatus(mundo, section, filePath, next);
      await retryContent();
    },
    [mundo, section, filePath, retryContent],
  );

  // Toggle edit mode — exiting resets preview and transient state
  const handleToggleEdit = useCallback(() => {
    if (isEditing) {
      if (pendingNewFile) {
        handleRejectReview();
        return;
      }
      // Exiting edit mode — reset edited content to original body
      if (file) {
        setEditedContent(currentContent);
      }
      setPreviewOpen(false);
      setSaveError(null);
      setSaveSuccess(false);
    } else {
      // Entering edit mode — initialise content if needed
      if (editedContent === null && file) {
        setEditedContent(currentContent);
      }
    }
    setIsEditing((prev) => !prev);
  }, [currentContent, editedContent, file, handleRejectReview, isEditing, pendingNewFile]);

  // Insert a wikilink at the cursor position. While the preview is open the
  // live diff's side B is the writing surface — the imperative handle
  // splices the wikilink into the focused diff line (or appends at the end).
  // Otherwise insert into the textarea at its preserved caret.
  const handleInsertWikilink = useCallback(
    (name: string) => {
      const wikilink = `[[${name}]]`;
      if (previewOpen) {
        liveDiffRef.current?.insertText(wikilink);
        return;
      }
      const ta = textareaRef.current;
      if (!ta) return;

      const start = ta.selectionStart;
      const end = ta.selectionEnd;
      const current = editedContent ?? "";

      const newContent =
        current.slice(0, start) + wikilink + current.slice(end);
      setEditedContent(newContent);

      // Restore cursor after the inserted wikilink
      requestAnimationFrame(() => {
        ta.focus();
        ta.selectionStart = ta.selectionEnd = start + wikilink.length;
      });
    },
    [editedContent, previewOpen],
  );

  // Insert an image markdown at the cursor position. Mirrors the wikilink
  // flow: while the preview is open the live diff is the writing surface
  // (imperative insertText), otherwise splice into the textarea caret.
  const insertMarkdown = useCallback(
    (path: string) => {
      const name = path.split("/").pop()?.split(".")[0] ?? "image";
      const md = `![${name}](${path})`;
      if (previewOpen) {
        liveDiffRef.current?.insertText(md);
        return;
      }
      const ta = textareaRef.current;
      if (!ta) return;

      const start = ta.selectionStart;
      const end = ta.selectionEnd;
      const current = editedContent ?? "";

      const newContent =
        current.slice(0, start) + md + current.slice(end);
      setEditedContent(newContent);

      // Restore cursor after the inserted markdown
      requestAnimationFrame(() => {
        ta.focus();
        ta.selectionStart = ta.selectionEnd = start + md.length;
      });
    },
    [editedContent, previewOpen],
  );

  // Handle file drop in view mode — upload and append markdown at the end
  const handleFileDrop = useCallback(
    async (file: File) => {
      if (!mundo) return;
      try {
        const result = await upload(file);
        const md = `![${result.path.split("/").pop()!.split(".")[0]}](${result.path})`;
        setEditedContent((prev) => (prev ?? "") + "\n" + md + "\n");
      } catch (err) {
        // Upload error — surfaced by the uploadError banner
        console.error("Upload failed:", err);
      }
    },
    [mundo, upload],
  );

  const hasChanges =
    editedContent !== null && editedContent !== currentContent;

  // Right panel content — always visible
  const rightPanelContent = (
    <div className="flex h-full flex-col">
      <TabBar onTabChange={setSidebarTab} />
      {sidebarTab === "asistente" ? (
        <AIAssistantSidebar
          mundo={mundo!}
          section={section}
          filePath={filePath}
          onProposeEdit={handleAssistantEditProposal}
          onGuidedReview={handleGuidedReview}
        />
      ) : (
        <EntitySearchPanel mundo={mundo!} onInsert={handleInsertWikilink} />
      )}
    </div>
  );

  // Editor textarea — used standalone; the preview replaces it with the
  // live diff (side B of the diff is the writing surface while open)
  const editorTextarea = (
    <textarea
      ref={textareaRef}
      value={editedContent ?? ""}
      onChange={(e) => setEditedContent(e.target.value)}
      className="min-h-[400px] w-full resize-y rounded-lg border border-edge bg-surface-raised px-4 py-3 font-mono text-body text-primary placeholder:text-muted focus:border-action focus:outline-none focus:ring-1 focus:ring-action/50"
      aria-label="Editor de contenido"
      spellCheck={false}
    />
  );

  // --- Render states ---

  // Invalid section
  if (section && !sectionValid) {
    return (
      <EditorLayout
        sidebar={null}
      >
        <div className="flex flex-col items-center justify-center gap-4 py-24">
          <div className="flex h-16 w-16 items-center justify-center rounded-full bg-surface-raised text-status-error">
            <Icon name="error" size={32} />
          </div>
          <h2 className="font-heading text-h3 text-primary">
            Sección no válida
          </h2>
          <p className="text-body text-muted">
            Secciones válidas:{" "}
            {VALID_SECTIONS.map((s) => `"${s}"`).join(", ")}
          </p>
          <Button variant="secondary" onClick={() => navigate("/wiki")}>
            <Icon name="chevron-left" size={16} />
            Volver al inicio
          </Button>
        </div>
      </EditorLayout>
    );
  }

  // Loading world list
  if (worldsLoading) {
    return (
      <EditorLayout
        sidebar={null}
      >
        <div className="flex items-center justify-center py-24">
          <Spinner size="lg" />
        </div>
      </EditorLayout>
    );
  }

  // Has issues that prevent rendering
  if (!mundo || !section) {
    return (
      <EditorLayout
        sidebar={null}
      >
        <EmptyState
          icon="error"
          message="Faltan parámetros de ruta. Seleccioná un mundo desde la página principal."
          actionLabel="Ir al inicio"
          onAction={() => navigate("/wiki")}
        />
      </EditorLayout>
    );
  }

  if (!worldExists) {
    return (
      <EditorLayout
        sidebar={null}
      >
        <WorldNotFound mundo={mundo} />
      </EditorLayout>
    );
  }

  // Ready state
  return (
    <EditorLayout
      sidebar={
        <div className="flex h-full min-h-0 flex-col">
          <SectionTabs
            activeSection={section}
            onSelect={handleSectionSelect}
          />
          {/* World-level importer entry (UI1): sits at the top of the tree,
              never a folder node — analysis stays read-only until an
              explicit gated approval runs. */}
          <div className="border-b border-edge px-3 py-2">
            <Button
              variant="ghost"
              size="sm"
              onClick={() =>
                navigate(`/wiki/${encodeURIComponent(mundo)}/importer`)
              }
              className="w-full justify-start"
            >
              <Icon name="upload" size={14} />
              Importar contenido
            </Button>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto pb-2">
            <FileTree
              key={section}
              nodes={treeNodes}
              selectedPath={filePath}
              onSelect={handleFileSelect}
              isLoading={treeLoading}
              error={treeError}
              onRetry={retryTree}
              onMove={handleDropMove}
              movedPath={movedPath}
            />
          </div>
        </div>
      }
      rightPanel={rightPanelContent}
      focusMode={focusMode}
    >
      {/* Unified file bar — always visible so navigation never disappears:
          file name + badges (left), breadcrumb chips (middle), actions (right) */}
      <div className="sticky top-0 z-10 mb-4 flex flex-wrap items-center gap-x-4 gap-y-2 rounded-lg border border-edge bg-surface-raised px-4 py-2">
        {pendingNewFile ? (
          <span className="min-w-0 truncate text-small text-muted">
            {pendingNewFile.path}
            <span className="ml-2 rounded bg-action/10 px-2 py-0.5 text-xs text-action">
              New file review
            </span>
          </span>
        ) : filePath && file ? (
          <span className="min-w-0 truncate text-small text-muted">
            {file.name}
            {isEditing && (
              <span className="ml-2 rounded bg-action/10 px-2 py-0.5 text-xs text-action">
                Editando
              </span>
            )}
            {saveSuccess && (
              <span className="ml-2 rounded bg-status-success/10 px-2 py-0.5 text-xs text-status-success">
                Guardado ✓
              </span>
            )}
          </span>
        ) : null}

        {/* Breadcrumb chips — left-aligned in the bar */}
        <div className="flex min-w-0 items-center">
          <Breadcrumb
            segments={breadcrumbSegments}
            onSegmentClick={handleBreadcrumbClick}
          />
        </div>

        {/* Actions — creation buttons (browsing only) + focus toggle, rest only with a file selected */}
        <div className="ml-auto flex items-center gap-2">
          {/* Creation lives in the file bar, NOT in the card ⋯ menu: a card
              menu suggests "create inside this card", which is not how the
              directory scope works. Visible only while browsing (no open
              file); the target is the directory being viewed — the section
              root when no directory is open. */}
          {browsingDir && (
            <>
              <Button
                variant="ghost"
                size="sm"
                onClick={() =>
                  setCreateTarget({
                    path: selectedNode?.is_dir ? filePath! : "",
                    kind: "file",
                  })
                }
              >
                <Icon name="file" size={14} />
                Nuevo archivo
              </Button>
              <Button
                variant="ghost"
                size="sm"
                onClick={() =>
                  setCreateTarget({
                    path: selectedNode?.is_dir ? filePath! : "",
                    kind: "subfolder",
                  })
                }
              >
                <Icon name="folder" size={14} />
                Nueva carpeta
              </Button>
              {/* Papelera — restore / purge / empty of deleted entries.
                  Trash management is world-scoped; visible only in the
                  cards view (browsing). The open-ficha bar swaps it for
                  'Eliminar Ficha' — the two are mutually exclusive. */}
              <Button
                variant="ghost"
                size="sm"
                onClick={() => setTrashOpen(true)}
              >
                <Icon name="trash" size={14} />
                Papelera
              </Button>
            </>
          )}
          {/* Status chip — file-only: it describes the open ficha's
              frontmatter, so it never renders on cards/browsing screens.
              Sits before the focus button in the right zone. */}
          {!browsingDir && filePath && file && (
            <StatusBadge
              status={fichaStatus}
              onStatusChange={handleStatusChange}
            />
          )}
          {/* File-bar options dropdown (⋯) — ficha-level actions. Sits right
              after the status chip and before the focus button so
              Edit/Import actions stay at the far right of the bar (the
              Author's first intent on an open ficha is to edit, not to
              delete). Visible only when a ficha is open and the editor
              is NOT in edit mode. */}
          {!browsingDir && filePath && file && !isEditing && (
            <div ref={optionsRef} className="relative inline-block">
              <button
                type="button"
                aria-label="Opciones de ficha"
                aria-haspopup="menu"
                aria-expanded={optionsOpen}
                onClick={() => setOptionsOpen((o) => !o)}
                className="flex h-8 w-8 items-center justify-center rounded-md border border-edge bg-surface text-muted transition-colors hover:border-action/40 hover:text-primary"
              >
                <Icon name="dots" size={14} />
              </button>
              {optionsOpen && (
                <div
                  role="menu"
                  aria-label="Opciones de ficha"
                  className="absolute top-full right-0 z-20 min-w-48 overflow-hidden rounded-lg border border-edge bg-surface-raised shadow-xl"
                >
                  <button
                    type="button"
                    role="menuitem"
                    onClick={() => {
                      setExportTarget({
                        content: file?.content ?? "",
                        fileName: filePath.split("/").pop() ?? "",
                      });
                      setOptionsOpen(false);
                    }}
                    className="block w-full px-3 py-2 text-left text-small text-primary transition-colors hover:bg-surface-hover hover:text-action focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-action/50"
                  >
                    <span className="flex items-center gap-2">
                      <Icon name="file" size={14} className="shrink-0 text-muted" />
                      Exportar Ficha a PDF
                    </span>
                  </button>
                  <button
                    type="button"
                    role="menuitem"
                    onClick={() => {
                      setHistoryOpen(true);
                      setOptionsOpen(false);
                    }}
                    className="block w-full px-3 py-2 text-left text-small text-primary transition-colors hover:bg-surface-hover hover:text-action focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-action/50"
                  >
                    <span className="flex items-center gap-2">
                      <Icon name="history" size={14} className="shrink-0 text-muted" />
                      History
                    </span>
                  </button>
                  <button
                    type="button"
                    role="menuitem"
                    onClick={() => {
                      setTrashTarget(filePath);
                      setOptionsOpen(false);
                    }}
                    className="block w-full px-3 py-2 text-left text-small text-primary transition-colors hover:bg-surface-hover hover:text-action focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-action/50"
                  >
                    <span className="flex items-center gap-2">
                      <Icon name="trash" size={14} className="shrink-0 text-muted" />
                      Eliminar Ficha
                    </span>
                  </button>
                </div>
              )}
            </div>
          )}
          <button
            type="button"
            onClick={() => setFocusMode((prev) => !prev)}
            title={focusMode ? "Restaurar paneles laterales" : "Modo foco: ocultar paneles"}
            aria-label={focusMode ? "Restaurar paneles laterales" : "Modo foco: ocultar paneles"}
            aria-pressed={focusMode}
            className="flex h-8 w-8 items-center justify-center rounded-md border border-edge bg-surface text-muted transition-colors hover:border-action/40 hover:text-primary"
          >
            <Icon name={focusMode ? "minimize" : "expand"} size={14} />
          </button>
          {/* Edit/import actions are file-only: they make no sense outside
              the file screen (browsing a directory has no draft to edit and
              no content to attach images to). Guarded by !browsingDir, not
              just filePath && file — the content hook may resolve a value
              for directory paths, which would leak the buttons elsewhere. */}
          {pendingNewFile && isEditing && (
            <>
              {!previewOpen && (
                <Button
                  variant="primary"
                  size="sm"
                  onClick={handleSave}
                  disabled={isSaving}
                >
                  Revisar creación
                </Button>
              )}
              <Button
                variant="ghost"
                size="sm"
                onClick={handleToggleEdit}
                disabled={isSaving}
              >
                Cancelar
              </Button>
            </>
          )}
          {!browsingDir && filePath && file && (
            <>
              {isEditing ? (
              <>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => setShowPicker(true)}
                >
                  <Icon name="image" size={14} />
                  Imagen
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={handleToggleEdit}
                  disabled={isSaving}
                >
                  <Icon name="close" size={14} />
                  Cancelar
                </Button>
                {hasChanges && (
                  <>
                    <Button
                      variant="secondary"
                      size="sm"
                      onClick={handleSave}
                    >
                      <Icon name="diff" size={14} />
                      Vista previa
                    </Button>
                    {!previewOpen && (
                      <Button
                        variant="primary"
                        size="sm"
                        onClick={handleSave}
                        disabled={isSaving}
                      >
                        <Icon name="save" size={14} />
                        Revisar cambios
                      </Button>
                    )}
                  </>
                )}
              </>
              ) : (
              <>
                <Button
                  variant="primary"
                  size="sm"
                  onClick={() => setShowImportModal(true)}
                >
                  <Icon name="upload" size={14} />
                  Importar Imagen
                </Button>
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={handleToggleEdit}
                >
                  <Icon name="edit" size={14} />
                  Editar
                </Button>
              </>
            )}
            </>
          )}
        </div>
      </div>

      {/* Save error banner */}
      {saveError && (
        <ErrorBanner message={saveError} className="mb-4" />
      )}

      {/* Content area: section cards (no file / directory selected),
          live diff preview, textarea editor, or viewer */}
      {browsingDir ? (
        treeLoading ? (
          <div className="flex items-center justify-center py-24">
            <Spinner size="lg" />
          </div>
        ) : treeError ? (
          <div className="px-4 py-8">
            <ErrorBanner
              message="No se pudo cargar el contenido de la sección"
              onRetry={retryTree}
            />
          </div>
        ) : browsingNodes.length === 0 ? (
          <EmptyState icon="folder" message="La sección está vacía" />
        ) : (
          <SectionCards
            nodes={browsingNodes}
            mundo={mundo}
            section={section}
            onSelect={handleFileSelect}
            onAction={handleCardAction}
            renamingPath={renamingPath}
            busyPath={busyPath}
            actionError={actionError}
            createTarget={createTarget}
            onMove={handleDropMove}
            browsingDirPath={selectedNode?.is_dir ? filePath! : ""}
            movedPath={movedPath}
            onRenameCommit={handleRenameCommit}
            onRenameCancel={() => {
              setRenamingPath(null);
              setActionError(null);
            }}
            onCreateCommit={handleCreateCommit}
            onCreateCancel={() => {
              setCreateTarget(null);
              setActionError(null);
            }}
          />
        )
      ) : isEditing && editedContent !== null ? (
        // The preview REPLACES the textarea — the diff's right side is the
        // writing surface. The textarea unmounts while the preview is open
        // and remounts (with the preserved draft) when it closes.
        previewOpen ? (
          <>
            <Suspense
              fallback={
                <div className="flex h-[70vh] items-center justify-center rounded-lg border border-edge bg-surface-raised">
                  <Spinner size="lg" />
                </div>
              }
            >
              <LiveDiffEditor
                ref={liveDiffRef}
                original={currentContent}
                value={editedContent}
                onChange={handleReviewContentChange}
              />
            </Suspense>
            {review.status === "reviewing" && (
              <div
                className="mt-4 flex items-center justify-end gap-2"
                role="group"
                aria-label="Review actions"
              >
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={handleRejectReview}
                  disabled={isSaving || review.isLoading}
                >
                  Reject
                </Button>
                <Button
                  variant="primary"
                  size="sm"
                  onClick={() => void handleAcceptReview()}
                  disabled={isSaving || review.isLoading}
                >
                  Accept
                </Button>
              </div>
            )}
          </>
        ) : (
          editorTextarea
        )
      ) : (
        <MarkdownViewer
          content={file ? body : null}
          fileName={file?.name}
          isLoading={contentLoading}
          error={contentError}
          onRetry={retryContent}
          mundo={mundo}
        />
      )}

      {/* Image picker modal — opened from the editing toolbar */}
      {showPicker && mundo && (
        <ImagePicker
          mundo={mundo}
          onSelect={(path) => {
            insertMarkdown(path);
            setShowPicker(false);
          }}
          onClose={() => setShowPicker(false)}
        />
      )}

      {/* Import image modal — opened from the file bar in view mode */}
      {showImportModal && (
        <ImportImageModal
          onFile={handleFileDrop}
          isUploading={isUploading}
          uploadError={uploadError}
          onClose={() => setShowImportModal(false)}
        />
      )}

      {/* Move modal — opened from a card ⋯ action (S9) */}
      {moveSource && (
        <MoveModal
          mundo={mundo}
          source={moveSource}
          onConfirm={handleMoveConfirm}
          onClose={() => {
            setMoveSource(null);
            setActionError(null);
          }}
        />
      )}

      {/* Move to section dialog — opened from a card ⋯ action. Cross-section
          moves are irreversible; the dialog warns before confirming. */}
      {moveSectionTarget && (
        <MoveToSectionDialog
          source={moveSectionTarget}
          onConfirm={handleMoveToSectionConfirm}
          onClose={() => {
            setMoveSectionTarget(null);
            setActionError(null);
          }}
        />
      )}

      {/* Delete confirmation (S12) — cancel aborts, confirm moves to trash */}
      {trashTarget && (
        <ConfirmDialog
          title="Eliminar"
          message={`¿Eliminar "${trashTarget.split("/").pop()}"? Se moverá a la papelera.`}
          confirmLabel="Eliminar"
          isBusy={busyPath === trashTarget}
          error={actionError}
          onConfirm={handleTrashConfirm}
          onClose={() => {
            setTrashTarget(null);
            setActionError(null);
          }}
        />
      )}

      {/* Export to PDF dialog — opened from the ⋯ options menu. Renders the
          ficha body (frontmatter stripped) into a hidden print portal and
          opens the browser print dialog; no server round-trip. */}
      {exportTarget && (
        <ExportPdfDialog
          open={!!exportTarget}
          onClose={() => setExportTarget(null)}
          content={exportTarget.content}
          fileName={exportTarget.fileName}
          mundo={mundo ?? ""}
        />
      )}

      {/* Set cover picker (S11/S32) — rawMode emits the bare media path */}
      {coverTarget && (
        <ImagePicker
          mundo={mundo}
          rawMode
          onSelect={handleCoverSelect}
          onClose={() => {
            setCoverTarget(null);
            setActionError(null);
          }}
        />
      )}

      {/* Papelera — restore / purge / empty (trash v2). Always mounted,
          `open` gates visibility; a successful restore revalidates the tree
          so restored files reappear in the sidebar immediately. */}
      {mundo && (
        <PapeleraPanel
          mundo={mundo}
          open={trashOpen}
          onClose={() => setTrashOpen(false)}
          onRestored={retryTree}
          onPurged={retryTree}
          onTtlPurged={handleTtlPurged}
        />
      )}

      {historyOpen && filePath && file && section && (
        <HistoryPanel
          mundo={mundo}
          section={section}
          path={filePath}
          currentRevision={revision}
          currentContent={file.content}
          open={historyOpen}
          onClose={() => setHistoryOpen(false)}
          onRestored={retryContent}
        />
      )}

      {/* Move feedback toast — success (action) or error (status-error) */}
      {toast && <Toast message={toast.message} kind={toast.kind} />}
    </EditorLayout>
  );
}
