import { useCallback, useEffect, useMemo, useRef, useState } from "react";
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
  type IdeaMaterializeTarget,
  type IdeaMaterializeTargetResult,
  type MaterializeCollision,
  type MaterializeSection,
  type ProposedMaterializeRelation,
  IDEA_TYPES,
  MATERIALIZE_SECTIONS,
  previewMaterialize,
  previewMaterializeTarget,
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

/** Debounce for re-resolving the destination while the filename is edited. */
const FILENAME_RESOLVE_DEBOUNCE_MS = 400;

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
 * Editable text field shared by the destination and collision steps. The
 * title field drives the ficha H1/frontmatter title; the filename field holds
 * the name WITHOUT the `.md` extension. The dialog owns both drafts and the
 * debounced re-resolve; this only renders the label + input + optional hint.
 * Module-level on purpose: a nested component would remount the inputs on
 * every render and steal focus from the typist.
 */
function MaterializeTextField({
  id,
  label,
  hint,
  value,
  onChange,
  onFocus,
  onBlur,
  mono = false,
}: {
  id: string;
  label: string;
  hint?: string;
  value: string;
  onChange: (value: string) => void;
  onFocus: () => void;
  onBlur: () => void;
  /** Filenames render monospaced; the human title does not. */
  mono?: boolean;
}) {
  return (
    <div>
      <label htmlFor={id} className="mb-1 block text-xs text-muted">
        {label}
      </label>
      <input
        id={id}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onFocus={onFocus}
        onBlur={onBlur}
        spellCheck={false}
        autoComplete="off"
        className={`w-full rounded-md border border-edge bg-surface px-2.5 py-1.5 text-xs text-primary placeholder:text-muted focus:border-action focus:outline-none focus:ring-1 focus:ring-action/50${
          mono ? " font-mono" : ""
        }`}
      />
      {hint && <p className="mt-1 text-[11px] text-muted">{hint}</p>}
    </div>
  );
}

/**
 * Focus baseline shared by the idea-detail dialogs (Fix 3): on mount move
 * focus into the dialog container and remember the element that opened it; on
 * unmount restore focus to that trigger when it is still in the document.
 */
function useDialogFocus<T extends HTMLElement>() {
  const ref = useRef<T | null>(null);
  useEffect(() => {
    const trigger = document.activeElement as HTMLElement | null;
    ref.current?.focus();
    return () => {
      if (trigger && trigger.isConnected) trigger.focus();
    };
  }, []);
  return ref;
}

/**
 * Shared modal frame for the small idea-detail dialogs (DM-2). Mirrors the
 * MaterializePreviewDialog shell — backdrop click closes, Escape closes, close
 * button in the header, focus moves in on open and returns to the trigger on
 * close — so every dialog keeps the same accessibility contract without a new
 * dependency. `error` is the modal-scoped failure surface (Fix 1): it renders
 * inside the dialog so a failure is never hidden behind the overlay.
 */
function DialogFrame({
  title,
  onClose,
  busy,
  error,
  children,
  footer,
}: {
  title: string;
  onClose: () => void;
  busy: boolean;
  error?: string | null;
  children: React.ReactNode;
  footer?: React.ReactNode;
}) {
  const { t } = useAppLanguage();
  const dialogRef = useDialogFocus<HTMLDivElement>();

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !busy) onClose();
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [busy, onClose]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-surface/80 backdrop-blur-sm"
      onClick={(e) => {
        if (e.target === e.currentTarget && !busy) onClose();
      }}
    >
      <div
        ref={dialogRef}
        tabIndex={-1}
        className="mx-4 flex max-h-[85vh] w-full max-w-md flex-col rounded-xl border border-edge bg-surface-raised shadow-2xl focus:outline-none"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label={title}
      >
        <div className="flex items-center justify-between border-b border-edge px-6 py-4">
          <h2 className="font-heading text-h4 text-primary">{title}</h2>
          <button
            type="button"
            onClick={onClose}
            disabled={busy}
            className="rounded-md p-1 text-icon-muted transition-colors hover:bg-surface-hover hover:text-primary disabled:opacity-50"
            aria-label={t("ideas.preview.close")}
          >
            <Icon name="close" size={20} />
          </button>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto px-6 py-4">
          {error && (
            <div
              role="alert"
              className="mb-3 rounded-lg border border-status-error/30 bg-status-error/10 px-3 py-2 text-xs text-status-error"
            >
              {error}
            </div>
          )}
          {children}
        </div>
        {footer && (
          <div className="flex items-center justify-end gap-2 border-t border-edge px-6 py-4">
            {footer}
          </div>
        )}
      </div>
    </div>
  );
}

/** One accessible item inside the `⋯` options menu. */
function IdeaMenuItem({
  label,
  onClick,
}: {
  label: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      role="menuitem"
      onClick={onClick}
      className="flex w-full items-center px-3 py-1.5 text-left text-xs text-primary transition-colors hover:bg-surface-hover focus:bg-surface-hover focus:outline-none"
    >
      {label}
    </button>
  );
}

/**
 * `⋯` options menu for the idea detail (DM-2). Opens on click; closes on
 * Escape, outside click or item activation. The trigger exposes
 * `aria-haspopup="menu"` + `aria-expanded`; the items are plain buttons, so
 * they are keyboard reachable (Tab) and the first one receives focus on open.
 */
function DetailActionsMenu({
  disabled,
  onTitle,
  onImage,
  onExportDocx,
  onExportPdf,
}: {
  disabled: boolean;
  onTitle: () => void;
  onImage: () => void;
  onExportDocx: () => void;
  onExportPdf: () => void;
}) {
  const { t } = useAppLanguage();
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement | null>(null);
  const menuRef = useRef<HTMLDivElement | null>(null);
  const triggerRef = useRef<HTMLButtonElement | null>(null);

  const close = useCallback(() => setOpen(false), []);

  // A modal opening (or any other disable signal) must dismiss the menu.
  useEffect(() => {
    if (disabled) setOpen(false);
  }, [disabled]);

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(event.target as Node)) {
        setOpen(false);
      }
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  useEffect(() => {
    if (!open) return;
    menuRef.current?.querySelector<HTMLElement>('[role="menuitem"]')?.focus();
  }, [open]);

  const activate = useCallback(
    (action: () => void) => {
      close();
      // Return focus to the trigger before the dialog mounts, so the dialog's
      // focus-restore target is the `⋯` button (Fix 3).
      triggerRef.current?.focus();
      action();
    },
    [close],
  );

  return (
    <div className="relative" ref={rootRef}>
      <button
        ref={triggerRef}
        type="button"
        onClick={() => setOpen((prev) => !prev)}
        disabled={disabled}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={t("ideas.detail.actionsMenuAria")}
        className="flex items-center rounded-md border border-edge bg-surface px-2 py-1 text-xs font-medium text-primary transition-colors hover:border-action/40 hover:text-action disabled:cursor-not-allowed disabled:opacity-50"
      >
        <Icon name="dots" size={16} />
      </button>
      {open && (
        <div
          role="menu"
          ref={menuRef}
          aria-label={t("ideas.detail.actionsMenuAria")}
          className="absolute right-0 z-30 mt-1 w-56 rounded-md border border-edge bg-surface-raised py-1 shadow-xl"
        >
          <IdeaMenuItem
            label={t("ideas.detail.titleHeading")}
            onClick={() => activate(onTitle)}
          />
          <IdeaMenuItem
            label={t("ideas.detail.imageHeading")}
            onClick={() => activate(onImage)}
          />
          <div role="separator" className="my-1 border-t border-edge" />
          <IdeaMenuItem
            label={t("ideas.detail.exportDocxAria")}
            onClick={() => activate(onExportDocx)}
          />
          <IdeaMenuItem
            label={t("ideas.detail.exportPdfAria")}
            onClick={() => activate(onExportPdf)}
          />
        </div>
      )}
    </div>
  );
}

/** Title dialog — the idea title input now lives here, not inline (DM-2). */
function TitleDialog({
  open,
  value,
  canSave,
  saving,
  error,
  onChange,
  onSave,
  onClose,
}: {
  open: boolean;
  value: string;
  canSave: boolean;
  saving: boolean;
  error: string | null;
  onChange: (value: string) => void;
  onSave: () => void;
  onClose: () => void;
}) {
  const { t } = useAppLanguage();
  if (!open) return null;
  return (
    <DialogFrame
      title={t("ideas.detail.titleHeading")}
      onClose={onClose}
      busy={saving}
      error={error}
      footer={
        <>
          <button
            type="button"
            onClick={onClose}
            disabled={saving}
            className="rounded-md border border-edge px-3 py-1.5 text-xs text-muted transition-colors hover:border-action/40 hover:text-primary disabled:opacity-50"
          >
            {t("ideas.preview.close")}
          </button>
          <button
            type="button"
            onClick={onSave}
            disabled={saving || !canSave}
            className="rounded-md bg-action px-3 py-1.5 text-xs font-medium text-action-text transition-colors hover:bg-action-hover disabled:cursor-not-allowed disabled:opacity-50"
          >
            {saving ? t("ideas.detail.saving") : t("ideas.detail.saveTitle")}
          </button>
        </>
      }
    >
      <label htmlFor="edit-idea-title" className="mb-1 block text-xs text-muted">
        {t("ideas.detail.titleHeading")}
      </label>
      <input
        id="edit-idea-title"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={t("ideas.detail.titlePlaceholder")}
        className="w-full rounded-md border border-edge bg-surface px-2.5 py-1.5 text-xs text-primary placeholder:text-muted focus:border-action focus:outline-none focus:ring-1 focus:ring-action/50"
      />
    </DialogFrame>
  );
}

/**
 * Image dialog — attach or replace the idea image. The copy states that
 * attaching replaces the current image and creates a new idea version (the
 * backend archives the current version on attach).
 */
function ImageDialog({
  open,
  mediaPath,
  attaching,
  error,
  onAttach,
  onClose,
}: {
  open: boolean;
  mediaPath: string | null;
  attaching: boolean;
  error: string | null;
  onAttach: (event: React.ChangeEvent<HTMLInputElement>) => void;
  onClose: () => void;
}) {
  const { t } = useAppLanguage();
  if (!open) return null;
  const fileName = mediaPath ? mediaPath.split("/").pop() ?? "" : "";
  return (
    <DialogFrame
      title={t("ideas.detail.imageHeading")}
      onClose={onClose}
      busy={attaching}
      error={error}
      footer={
        <button
          type="button"
          onClick={onClose}
          disabled={attaching}
          className="rounded-md border border-edge px-3 py-1.5 text-xs text-muted transition-colors hover:border-action/40 hover:text-primary disabled:opacity-50"
        >
          {t("ideas.preview.close")}
        </button>
      }
    >
      <p className="mb-2 text-xs text-muted">
        {fileName
          ? t("ideas.detail.imageDialogCurrent", { name: fileName })
          : t("ideas.detail.noImage")}
      </p>
      {fileName && (
        <img
          src={`/api/ideas/media/${fileName}`}
          alt={t("ideas.detail.imageDialogPreviewAlt")}
          className="mb-3 max-h-48 rounded-md border border-edge object-contain"
        />
      )}
      <p className="mb-3 text-xs text-muted">
        {t("ideas.detail.imageDialogReplaceNote")}
      </p>
      <label className="inline-flex cursor-pointer items-center gap-1.5 rounded-md bg-action px-3 py-1.5 text-xs font-medium text-action-text transition-colors hover:bg-action-hover">
        <Icon name="image" size={13} />
        {attaching
          ? t("ideas.detail.attaching")
          : fileName
            ? t("ideas.detail.replaceImage")
            : t("ideas.detail.attachImage")}
        <input
          type="file"
          accept="image/*"
          className="hidden"
          disabled={attaching}
          onChange={onAttach}
        />
      </label>
    </DialogFrame>
  );
}

/**
 * Materialize dialog (AD8). Five modes by priority:
 *   1. progress (`previewing`): the AI is writing the ficha; honest copy, a
 *      live elapsed-seconds counter and a Cancel that aborts the request.
 *   2. collision (`collision && !preview`): the destination exists; shows the
 *      `suggested_slug` hint, offers the one-click suggestion AND the same
 *      editable filename field so a free name can be typed. No generation
 *      while the collision persists.
 *   3. destination (`targetPreview && !preview && !collision`): the instantly
 *      resolved path, the editable filename field (server-normalized on blur)
 *      plus the primary "Generar contenido" action; a generation error renders
 *      here as an in-dialog alert with retry available.
 *   4. content (`preview`): the server-owned draft via MarkdownViewer plus the
 *      proposed/discarded relations. Nothing here is editable — the ficha
 *      becomes editable after creation.
 *   0. picker (none of the above): the world/section/folder picker that used
 *      to live inline. It is the INITIAL mode of this dialog, so the flow
 *      never stacks two modals (DM-2). Its "Previsualizar" advances to
 *      destination (or collision); the legacy "Solo marcar como usada" and
 *      Cancelar stay reachable here.
 * The outer shell is shared; only the aria-label/heading follow the mode.
 */
function MaterializePreviewDialog({
  preview,
  targetPreview,
  collision,
  previewing,
  materializeError,
  elapsedSeconds,
  confirming,
  titleDraft,
  onTitleChange,
  onTitleFocus,
  onTitleBlur,
  filenameDraft,
  onFilenameChange,
  onFilenameFocus,
  onFilenameBlur,
  onApplySuggestedSlug,
  onConfirm,
  onGenerate,
  onCancelGenerate,
  onClose,
  onCancelPicker,
  worlds,
  materializeWorld,
  materializeSection,
  materializeFolder,
  folderNodes,
  folderLoading,
  markingUsed,
  onWorldChange,
  onSectionChange,
  onFolderChange,
  onPreview,
  onMarkUsedOnly,
}: {
  preview: IdeaMaterializePreviewResult | null;
  targetPreview: IdeaMaterializeTarget | null;
  collision: MaterializeCollision | null;
  previewing: boolean;
  materializeError: string | null;
  elapsedSeconds: number;
  confirming: boolean;
  titleDraft: string;
  onTitleChange: (value: string) => void;
  onTitleFocus: () => void;
  onTitleBlur: () => void;
  filenameDraft: string;
  onFilenameChange: (value: string) => void;
  onFilenameFocus: () => void;
  onFilenameBlur: () => void;
  onApplySuggestedSlug: () => void;
  onConfirm: () => void;
  onGenerate: () => void;
  onCancelGenerate: () => void;
  /** Destination/content/collision dismiss: resets back to the picker step. */
  onClose: () => void;
  /** Picker dismiss: closes the whole materialize flow. */
  onCancelPicker: () => void;
  worlds: { name: string }[];
  materializeWorld: string;
  materializeSection: MaterializeSection;
  materializeFolder: string;
  folderNodes: FileNode[];
  folderLoading: boolean;
  markingUsed: boolean;
  onWorldChange: (value: string) => void;
  onSectionChange: (value: MaterializeSection) => void;
  onFolderChange: (value: string) => void;
  onPreview: () => void;
  onMarkUsedOnly: () => void;
}) {
  const { t } = useAppLanguage();
  const mode: "progress" | "content" | "collision" | "destination" | "picker" =
    previewing
      ? "progress"
      : preview
        ? "content"
        : collision
          ? "collision"
          : targetPreview
            ? "destination"
            : "picker";
  const titleKey =
    mode === "picker"
      ? "ideas.materialize.heading"
      : mode === "progress"
        ? "ideas.materialize.progressTitle"
        : "ideas.preview.title";
  // The header close returns to the picker from a later step, but closes the
  // whole flow while already on the picker.
  const handleHeaderClose = mode === "picker" ? onCancelPicker : onClose;

  // DISPLAY ONLY: the previewed body references the carried image at its final
  // world path (`media/<dest>`), but the bytes are copied only on confirm
  // (R-IM-04), so rendering that path would show a broken image. Point it at
  // the idea-bank URL instead. The confirm payload keeps the original
  // `preview.content` — its digest is bound to the world path.
  const displayContent = preview?.media
    ? preview.content.split(preview.media.dest).join(preview.media.src)
    : preview?.content;

  const busy = confirming || markingUsed;
  const dialogRef = useDialogFocus<HTMLDivElement>();

  // Escape follows the same close semantics as the header button: a later step
  // returns to the picker; the picker itself closes the whole flow (Fix 3).
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !busy) handleHeaderClose();
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [busy, handleHeaderClose]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-surface/80 backdrop-blur-sm"
      onClick={(e) => {
        if (e.target === e.currentTarget && !busy) handleHeaderClose();
      }}
    >
      <div
        ref={dialogRef}
        tabIndex={-1}
        className="mx-4 flex max-h-[85vh] w-full max-w-2xl flex-col rounded-xl border border-edge bg-surface-raised shadow-2xl focus:outline-none"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label={t(titleKey)}
      >
        {/* Header */}
        <div className="flex items-center justify-between border-b border-edge px-6 py-4">
          <h2 className="font-heading text-h4 text-primary">{t(titleKey)}</h2>
          <button
            type="button"
            onClick={handleHeaderClose}
            disabled={busy}
            className="rounded-md p-1 text-icon-muted transition-colors hover:bg-surface-hover hover:text-primary disabled:opacity-50"
            aria-label={t("ideas.preview.close")}
          >
            <Icon name="close" size={20} />
          </button>
        </div>

        {/* Body */}
        <div className="min-h-0 flex-1 overflow-y-auto px-6 py-4">
          {/* Modal-scoped failure surface (Fix 1): the page banner renders
              behind the overlay, so a failed resolve / mark-used / confirm /
              generation is shown here instead. */}
          {materializeError && (
            <div
              role="alert"
              className="mb-4 rounded-lg border border-status-error/30 bg-status-error/10 px-3 py-2 text-xs text-status-error"
            >
              {materializeError}
            </div>
          )}
          {previewing ? (
            <div className="space-y-4">
              <p className="text-xs text-muted">
                {t("ideas.materialize.progressBody")}
              </p>
              <div className="flex items-center gap-2 rounded-md bg-surface px-3 py-2">
                <Spinner size="sm" />
                <span className="text-xs text-muted">
                  {t("ideas.materialize.elapsedLabel")}
                </span>
                <span className="font-mono text-xs text-primary">
                  {t("ideas.materialize.elapsedSeconds", {
                    seconds: elapsedSeconds,
                  })}
                </span>
              </div>
            </div>
          ) : targetPreview && !preview && !collision ? (
            <div className="space-y-4">
              {/* The title drives the H1/frontmatter; the filename only names
                  the file. Editing the title re-derives the filename until the
                  author edits the filename by hand. */}
              <MaterializeTextField
                id="materialize-title"
                label={t("ideas.materialize.titleLabel")}
                hint={t("ideas.materialize.titleHint")}
                value={titleDraft}
                onChange={onTitleChange}
                onFocus={onTitleFocus}
                onBlur={onTitleBlur}
              />
              <MaterializeTextField
                id="materialize-filename"
                label={t("ideas.materialize.filenameLabel")}
                hint={t("ideas.materialize.filenameHint")}
                value={filenameDraft}
                onChange={onFilenameChange}
                onFocus={onFilenameFocus}
                onBlur={onFilenameBlur}
                mono
              />
              <p className="text-xs text-muted">
                {t("ideas.preview.targetLabel")}{" "}
                <span className="font-mono">{targetPreview.path}</span>
              </p>
            </div>
          ) : collision && !preview ? (
            <div className="space-y-4">
              {/* The title stays visible/editable here so the H1/frontmatter
                  title can still be adjusted while resolving the name clash. */}
              <MaterializeTextField
                id="materialize-title"
                label={t("ideas.materialize.titleLabel")}
                hint={t("ideas.materialize.titleHint")}
                value={titleDraft}
                onChange={onTitleChange}
                onFocus={onTitleFocus}
                onBlur={onTitleBlur}
              />
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
                  <span className="font-mono">{collision.suggested_target}</span>
                  )
                </p>
                <button
                  type="button"
                  onClick={onApplySuggestedSlug}
                  className="mt-2 rounded-md border border-edge px-2.5 py-1 text-xs font-medium text-primary transition-colors hover:border-action/40 hover:text-action"
                >
                  {t("ideas.materialize.useSuggestedName")}
                </button>
              </div>
              {/* The name is taken, so the same editable field is exactly what
                  the author needs: typing a free name re-resolves and clears
                  the collision through the shared debounce flow. */}
              <MaterializeTextField
                id="materialize-filename"
                label={t("ideas.materialize.filenameLabel")}
                hint={t("ideas.materialize.filenameHint")}
                value={filenameDraft}
                onChange={onFilenameChange}
                onFocus={onFilenameFocus}
                onBlur={onFilenameBlur}
                mono
              />
            </div>
          ) : preview ? (
            <div className="space-y-4">
              <p className="text-xs text-muted">
                {t("ideas.preview.targetLabel")}{" "}
                <span className="font-mono">{preview.target.path}</span>
              </p>
              <MarkdownViewer
                content={displayContent}
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
          ) : (
            <div className="space-y-2">
              <div>
                <label
                  htmlFor="materialize-world"
                  className="mb-1 block text-xs text-muted"
                >
                  {t("ideas.materialize.worldLabel")}
                </label>
                <select
                  id="materialize-world"
                  value={materializeWorld}
                  onChange={(e) => onWorldChange(e.target.value)}
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
                <label
                  htmlFor="materialize-section"
                  className="mb-1 block text-xs text-muted"
                >
                  {t("ideas.materialize.sectionLabel")}
                </label>
                <select
                  id="materialize-section"
                  value={materializeSection}
                  onChange={(e) =>
                    onSectionChange(e.target.value as MaterializeSection)
                  }
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
                    onClick={() => onFolderChange("")}
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
                      onSelect={onFolderChange}
                    />
                  )}
                </div>
              </div>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-2 border-t border-edge px-6 py-4">
          {previewing ? (
            <button
              type="button"
              onClick={onCancelGenerate}
              className="rounded-md border border-edge px-3 py-1.5 text-xs text-muted transition-colors hover:border-action/40 hover:text-primary"
            >
              {t("ideas.materialize.cancel")}
            </button>
          ) : mode === "picker" ? (
            <>
              <button
                type="button"
                onClick={onPreview}
                disabled={!materializeWorld}
                className="rounded-md bg-action px-3 py-1.5 text-xs font-medium text-action-text transition-colors hover:bg-action-hover disabled:cursor-not-allowed disabled:opacity-50"
              >
                {t("ideas.materialize.preview")}
              </button>
              <button
                type="button"
                onClick={onMarkUsedOnly}
                disabled={!materializeWorld || markingUsed}
                className="rounded-md border border-edge px-3 py-1.5 text-xs text-muted transition-colors hover:border-action/40 hover:text-primary disabled:cursor-not-allowed disabled:opacity-50"
              >
                {markingUsed
                  ? t("ideas.materialize.markingUsed")
                  : t("ideas.materialize.markUsedOnly")}
              </button>
              <button
                type="button"
                onClick={onCancelPicker}
                disabled={markingUsed}
                className="rounded-md border border-edge px-3 py-1.5 text-xs text-muted transition-colors hover:border-action/40 hover:text-primary disabled:opacity-50"
              >
                {t("ideas.materialize.cancel")}
              </button>
            </>
          ) : (
            <>
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
              {targetPreview && !preview && !collision && (
                <button
                  type="button"
                  onClick={onGenerate}
                  className="rounded-md bg-action px-3 py-1.5 text-xs font-medium text-action-text transition-colors hover:bg-action-hover"
                >
                  {materializeError
                    ? t("ideas.materialize.generateAgain")
                    : t("ideas.materialize.generate")}
                </button>
              )}
            </>
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
  const { language, t } = useAppLanguage();

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

  // DM-2 — detail surface: the metadata collapsible (default collapsed) and
  // the two small dialogs opened from the `⋯` options menu.
  const [detailsOpen, setDetailsOpen] = useState(false);
  const [titleDialogOpen, setTitleDialogOpen] = useState(false);
  const [imageDialogOpen, setImageDialogOpen] = useState(false);
  // Modal-scoped error surfaces (Fix 1): rendered INSIDE their dialog, since
  // the page banner sits behind the `fixed inset-0` overlay. Cleared on open,
  // on retry and on close so they never leak to the next idea or step.
  const [titleDialogError, setTitleDialogError] = useState<string | null>(null);
  const [imageDialogError, setImageDialogError] = useState<string | null>(null);

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

  /** Resolve an API failure to localized copy for a modal-scoped alert (Fix 1). */
  const apiErrorMessage = useCallback((err: unknown) => {
    const apiError = err as ApiError;
    return getErrorMessage(apiError.status, apiError.detail);
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
    setTitleDialogError(null);
    try {
      await updateIdea(selectedSlug, { title: editTitle.trim() });
      setTitleDialogOpen(false);
      await mutateDetail();
      await mutateList();
      await mutateVersions();
      showToast(t("ideas.toast.titleSaved", { title: editTitle.trim() }));
    } catch (err) {
      setTitleDialogError(apiErrorMessage(err));
    } finally {
      setSavingTitle(false);
    }
  }, [selectedSlug, editTitle, selectedIdea?.title, mutateDetail, mutateList, mutateVersions, apiErrorMessage, showToast, t]);

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
      setImageDialogError(null);
      try {
        await attachIdeaMedia(selectedSlug, file);
        await mutateDetail();
        await mutateList();
        await mutateVersions();
        showToast(t("ideas.toast.imageAttached"));
        // Close on success so the toast is visible.
        setImageDialogOpen(false);
      } catch (err) {
        // Keep the dialog open: the modal-scoped alert is visible there and
        // the author can retry from where they are (Fix 1).
        setImageDialogError(apiErrorMessage(err));
      } finally {
        setAttachingMedia(false);
        input.value = "";
      }
    },
    [selectedSlug, mutateDetail, mutateList, mutateVersions, apiErrorMessage, showToast, t],
  );

  /** DM-2 — copy an archived version's on-disk path (icon-only affordance). */
  const handleCopyVersionPath = useCallback(
    async (path: string) => {
      try {
        await navigator.clipboard?.writeText(path);
        showToast(t("ideas.toast.pathCopied"));
      } catch {
        // Clipboard unavailable (insecure context / denied) — stay silent.
      }
    },
    [showToast, t],
  );

  /** Locale-aware `dd/mm/aaaa` label for a version's ISO-8601 timestamp. */
  const formatVersionDate = useCallback(
    (iso: string) => {
      const date = new Date(iso);
      if (Number.isNaN(date.getTime())) return "";
      return new Intl.DateTimeFormat(language, {
        day: "2-digit",
        month: "2-digit",
        year: "numeric",
      }).format(date);
    },
    [language],
  );

  // ── Materialize ("usar en el mundo") ─────────────────────────────────────
  const [materializeWorld, setMaterializeWorld] = useState("");
  const [materializeSection, setMaterializeSection] =
    useState<MaterializeSection>("lore");
  const [materializeFolder, setMaterializeFolder] = useState("");
  const [preview, setPreview] = useState<IdeaMaterializePreviewResult | null>(null);
  const [targetPreview, setTargetPreview] = useState<IdeaMaterializeTarget | null>(
    null,
  );
  const [collision, setCollision] = useState<MaterializeCollision | null>(null);
  const [previewing, setPreviewing] = useState(false);
  // Single materialize-scoped failure surface (Fix 1): covers target resolve,
  // legacy mark-as-used, generation and confirm. Rendered at the top of the
  // dialog body so it is visible in every step.
  const [materializeError, setMaterializeError] = useState<string | null>(null);
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const [confirming, setConfirming] = useState(false);
  const [markingUsed, setMarkingUsed] = useState(false);
  // User-controlled ficha title draft. Drives the body H1 and the frontmatter
  // `title`; while the filename is clean it also drives the file name.
  const [titleDraft, setTitleDraft] = useState("");
  // User-controlled filename draft (without extension). Kept separate from the
  // server-resolved slug so a debounced response never fights the typist; it
  // snaps to the normalized value on blur.
  const [filenameDraft, setFilenameDraft] = useState("");

  // In-flight generation, so Cancel (and closing the dialog) can abort it.
  const generateAbortRef = useRef<AbortController | null>(null);
  // True while the title/filename input has focus — the server-resolved value
  // must not overwrite what the author is typing.
  const titleFocusedRef = useRef(false);
  const filenameFocusedRef = useRef(false);
  // True once the author edits the filename by hand. While clean, a title edit
  // re-derives the filename; once dirty, the manual name is preserved.
  const filenameDirtyRef = useRef(false);
  // Monotonic request counter: a resolve response is applied only when it is
  // still the latest request (stale responses are discarded).
  const resolveRequestRef = useRef(0);
  // The last (title, slug) pair the dialog resolved/displayed; used to skip the
  // no-op prefill echo and to avoid duplicate debounced requests.
  const lastResolvedRef = useRef<{ title: string; slug: string }>({
    title: "",
    slug: "",
  });
  // The last server-resolved title; the title field snaps to it on blur.
  const resolvedTitleRef = useRef("");
  // The scheduled debounced re-resolve, so a pre-generate resolve can cancel it
  // (the author asked to generate before the ~400 ms window elapsed).
  const resolveDebounceRef = useRef<number | null>(null);
  // Gate the debounce effect until the first explicit "Previsualizar".
  const hasResolvedRef = useRef(false);

  // Live elapsed-seconds counter while the AI writes the ficha. No fake
  // percentage: the ticking number is the evidence that work is happening.
  useEffect(() => {
    if (!previewing) return;
    setElapsedSeconds(0);
    const timer = window.setInterval(
      () => setElapsedSeconds((seconds) => seconds + 1),
      1000,
    );
    return () => window.clearInterval(timer);
  }, [previewing]);

  // Folder tree for the selected world + section (AD7). Null key while no
  // world is chosen, so the hook stays idle until a world is picked.
  const { nodes: folderNodes, isLoading: folderLoading } = useFileTree(
    materializeWorld || undefined,
    materializeSection,
  );

  /** Clear both drafts (title, filename), the dirty/focus flags and the
   *  resolve bookkeeping so a previous edit never leaks into the next idea or
   *  dialog. Bumps the request counter so any in-flight resolve from the
   *  previous dialog is discarded. */
  const resetMaterializeDrafts = useCallback(() => {
    setTitleDraft("");
    setFilenameDraft("");
    resolvedTitleRef.current = "";
    titleFocusedRef.current = false;
    filenameFocusedRef.current = false;
    filenameDirtyRef.current = false;
    hasResolvedRef.current = false;
    lastResolvedRef.current = { title: "", slug: "" };
    if (resolveDebounceRef.current !== null) {
      window.clearTimeout(resolveDebounceRef.current);
      resolveDebounceRef.current = null;
    }
    resolveRequestRef.current += 1;
  }, []);

  const openMaterialize = useCallback(() => {
    if (!selectedIdea) return;
    setActionError(null);
    setPreview(null);
    setTargetPreview(null);
    setCollision(null);
    setMaterializeError(null);
    setMaterializeFor(selectedIdea.slug);
    setMaterializeWorld("");
    setMaterializeSection(suggestSectionFor(selectedIdea.type));
    setMaterializeFolder("");
    resetMaterializeDrafts();
    // Start the title from the idea title; the server confirms/normalizes it
    // and its response becomes the field's truth.
    setTitleDraft(selectedIdea.title ?? "");
  }, [selectedIdea, resetMaterializeDrafts]);

  const closeMaterialize = useCallback(() => {
    generateAbortRef.current?.abort();
    generateAbortRef.current = null;
    setPreviewing(false);
    setMaterializeFor(null);
    setMaterializeWorld("");
    setMaterializeSection("lore");
    setMaterializeFolder("");
    setPreview(null);
    setTargetPreview(null);
    setCollision(null);
    setMaterializeError(null);
    resetMaterializeDrafts();
  }, [resetMaterializeDrafts]);

  /** Close only the dialog (the picker stays open) and abort any generation. */
  const closeMaterializeDialog = useCallback(() => {
    generateAbortRef.current?.abort();
    generateAbortRef.current = null;
    setPreviewing(false);
    setPreview(null);
    setTargetPreview(null);
    setCollision(null);
    setMaterializeError(null);
    resetMaterializeDrafts();
  }, [resetMaterializeDrafts]);

  /** Resolve the destination (and the resolved title) and apply the response
   *  only when this request is still the latest one (a stale response is
   *  dropped). `applyResolvedSlug` controls whether the server-normalized file
   *  name is mirrored into the draft: a title-driven re-resolve must never
   *  overwrite a name the author edited by hand. Returns the resolved values so
   *  "Generar contenido" can use them synchronously; `null` means no fresh
   *  result (stale request, collision or failure already surfaced). */
  const resolveTarget = useCallback(
    async (
      title: string,
      clientSlug: string,
      requestId: number,
      applyResolvedSlug: boolean,
    ): Promise<IdeaMaterializeTargetResult | null> => {
      if (!materializeFor || !materializeWorld) return null;
      const trimmedTitle = title.trim();
      const trimmedSlug = clientSlug.trim();
      try {
        const result = await previewMaterializeTarget(materializeFor, {
          world: materializeWorld,
          section: materializeSection,
          folder: materializeFolder,
          ...(trimmedTitle ? { title: trimmedTitle } : {}),
          ...(trimmedSlug ? { slug: trimmedSlug } : {}),
        });
        if (requestId !== resolveRequestRef.current) return null;
        setTargetPreview(result.target);
        setCollision(null);
        const resolvedTitle = result.title || trimmedTitle;
        resolvedTitleRef.current = resolvedTitle;
        lastResolvedRef.current = {
          title: resolvedTitle,
          // When the server derived the name, the draft mirrors it; when a
          // manual name rode along on a title edit, keep the manual value.
          slug: applyResolvedSlug ? result.target.slug : trimmedSlug,
        };
        // Never fight the typist: mirror the server-resolved values only when
        // the matching field is not focused. On blur the draft snaps to them.
        if (!titleFocusedRef.current) setTitleDraft(resolvedTitle);
        if (applyResolvedSlug && !filenameFocusedRef.current) {
          setFilenameDraft(result.target.slug);
        }
        return { title: resolvedTitle, target: result.target };
      } catch (err) {
        if (requestId !== resolveRequestRef.current) return null;
        const apiError = err as ApiError & { collision?: MaterializeCollision };
        if (apiError.collision) {
          setCollision(apiError.collision);
          setTargetPreview(null);
          if (trimmedTitle) resolvedTitleRef.current = trimmedTitle;
          // On the first resolve the name is derived, so the field is still
          // empty: surface the colliding basename (without `.md`) so the
          // author can see and edit the taken name. A prior edit is preserved.
          const collidingName =
            apiError.collision.target
              .split("/")
              .pop()
              ?.replace(/\.md$/i, "") ?? "";
          if (!trimmedSlug && collidingName) {
            setFilenameDraft(collidingName);
            lastResolvedRef.current = {
              title: trimmedTitle,
              slug: collidingName,
            };
          } else {
            lastResolvedRef.current = {
              title: trimmedTitle,
              slug: trimmedSlug,
            };
          }
          return null;
        }
        setMaterializeError(apiErrorMessage(err));
        return null;
      }
    },
    [
      materializeFor,
      materializeWorld,
      materializeSection,
      materializeFolder,
      apiErrorMessage,
    ],
  );

  // Step 1 — "Previsualizar" is INSTANT: POST /materialize-target resolves
  // the destination path, the resolved title and any collision with no AI call.
  // The dialog opens in destination (or collision) mode; the author decides
  // whether to pay for a generation after seeing where the ficha will land.
  const handleResolveTarget = useCallback(async () => {
    if (!materializeFor || !materializeWorld) {
      setMaterializeError(t("ideas.materialize.error.selectWorldPreview"));
      return;
    }
    setActionError(null);
    setPreview(null);
    setTargetPreview(null);
    setCollision(null);
    setMaterializeError(null);
    hasResolvedRef.current = true;
    const requestId = ++resolveRequestRef.current;
    // A fresh resolve never carries a manual name; the file name is derived
    // from the title unless the author already edited it in this session.
    const clientSlug = filenameDirtyRef.current ? filenameDraft : "";
    await resolveTarget(titleDraft, clientSlug, requestId, true);
  }, [
    materializeFor,
    materializeWorld,
    titleDraft,
    filenameDraft,
    resolveTarget,
    t,
  ]);

  // Debounced re-resolution while the author edits the title (~400 ms) or the
  // filename. While the filename is clean, a title edit re-derives it (send the
  // title and NO slug); once dirty, the manual name is preserved (send both).
  // The guard skips the prefill echo and any edit before the first explicit
  // "Previsualizar". The timer is cleared on dialog close/unmount.
  useEffect(() => {
    if (!hasResolvedRef.current) return;
    if (!materializeFor || !materializeWorld) return;
    const title = titleDraft.trim();
    const filename = filenameDraft.trim();
    const dirty = filenameDirtyRef.current;
    const titleChanged = title !== lastResolvedRef.current.title;
    const filenameChanged = dirty && filename !== lastResolvedRef.current.slug;
    if (!titleChanged && !filenameChanged) return;
    // Dirty filename: always send the manual slug (a filename edit, or a title
    // edit that must not re-derive it). Clean: omit the slug so the server
    // derives the file name from the title.
    const slugToSend = dirty ? filename : "";
    // A filename edit may mirror the server-normalized name; a title edit while
    // the name is dirty must not overwrite the manual name.
    const applyResolvedSlug = !dirty || filenameChanged;
    const requestId = ++resolveRequestRef.current;
    const timer = window.setTimeout(() => {
      void resolveTarget(title, slugToSend, requestId, applyResolvedSlug);
    }, FILENAME_RESOLVE_DEBOUNCE_MS);
    resolveDebounceRef.current = timer;
    return () => {
      window.clearTimeout(timer);
      if (resolveDebounceRef.current === timer) resolveDebounceRef.current = null;
    };
  }, [titleDraft, filenameDraft, materializeFor, materializeWorld, resolveTarget]);

  const handleTitleChange = useCallback((value: string) => {
    setTitleDraft(value);
  }, []);

  const handleTitleFocus = useCallback(() => {
    titleFocusedRef.current = true;
  }, []);

  const handleTitleBlur = useCallback(() => {
    titleFocusedRef.current = false;
    // Snap to the exact title the server resolved (server truth).
    if (resolvedTitleRef.current) setTitleDraft(resolvedTitleRef.current);
  }, []);

  const handleFilenameChange = useCallback((value: string) => {
    // Editing the file name by hand makes it authoritative: later title edits
    // no longer re-derive it.
    filenameDirtyRef.current = true;
    setFilenameDraft(value);
  }, []);

  const handleFilenameFocus = useCallback(() => {
    filenameFocusedRef.current = true;
  }, []);

  const handleFilenameBlur = useCallback(() => {
    filenameFocusedRef.current = false;
    // Snap to the exact name the server will write (server truth).
    if (targetPreview) setFilenameDraft(targetPreview.slug);
  }, [targetPreview]);

  /** One-click adoption of the 409 `suggested_slug`; re-resolves immediately
   *  and clears the collision on success. */
  const handleApplySuggestedSlug = useCallback(() => {
    if (!collision) return;
    const suggested = collision.suggested_slug;
    filenameFocusedRef.current = false;
    // The adopted name is now an explicit author choice: keep it on later
    // title edits. Optimistic so the debounce effect does not duplicate it.
    filenameDirtyRef.current = true;
    lastResolvedRef.current = {
      title: resolvedTitleRef.current || titleDraft.trim(),
      slug: suggested,
    };
    setFilenameDraft(suggested);
    const requestId = ++resolveRequestRef.current;
    void resolveTarget(titleDraft, suggested, requestId, true);
  }, [collision, resolveTarget, titleDraft]);

  // Step 2 — "Generar contenido" runs the (slow) AI preview from destination
  // mode only. Before spending the AI run it resolves any draft that is still
  // ahead of the debounced re-resolve, so the generated ficha matches exactly
  // what the author sees (never a stale title/file name). The AbortController is
  // stored so Cancel aborts the request and returns to destination mode.
  const handleGenerateContent = useCallback(async () => {
    if (!materializeFor || !materializeWorld) return;

    // What the author currently sees vs. the last resolved (server) values.
    const title = titleDraft.trim();
    const filename = filenameDraft.trim();
    const dirty = filenameDirtyRef.current;
    const filenameChanged = dirty && filename !== lastResolvedRef.current.slug;
    const pending =
      title !== lastResolvedRef.current.title || filenameChanged;

    let generateTitle = resolvedTitleRef.current || title;
    let generateSlug = targetPreview?.slug;

    if (pending) {
      // This immediate resolve supersedes any scheduled debounce.
      if (resolveDebounceRef.current !== null) {
        window.clearTimeout(resolveDebounceRef.current);
        resolveDebounceRef.current = null;
      }
      const requestId = ++resolveRequestRef.current;
      const resolved = await resolveTarget(
        title,
        dirty ? filename : "",
        requestId,
        !dirty || filenameChanged,
      );
      if (!resolved) {
        // A collision switched the dialog to the collision step; a failure is
        // already visible in the in-dialog alert. Never generate in either case.
        return;
      }
      generateTitle = resolved.title;
      generateSlug = resolved.target.slug;
    }

    const controller = new AbortController();
    generateAbortRef.current = controller;
    setPreviewing(true);
    setPreview(null);
    setMaterializeError(null);
    setActionError(null);
    try {
      const result = await previewMaterialize(
        materializeFor,
        {
          world: materializeWorld,
          section: materializeSection,
          folder: materializeFolder,
          // The title the author sees drives the body H1/frontmatter; the slug
          // is the freshest resolved file name (just re-resolved if pending).
          ...(generateTitle ? { title: generateTitle } : {}),
          ...(generateSlug ? { slug: generateSlug } : {}),
        },
        controller.signal,
      );
      setPreview(result);
    } catch (err) {
      // A user-initiated Cancel is not an error: return to destination mode.
      if (controller.signal.aborted || (err as Error)?.name === "AbortError") {
        return;
      }
      const apiError = err as ApiError & { collision?: MaterializeCollision };
      if (apiError.collision) {
        setPreview(null);
        setCollision(apiError.collision);
        return;
      }
      // Surface the localized failure INSIDE the dialog; the page-top banner
      // is behind the modal and would be invisible.
      setMaterializeError(getErrorMessage(apiError.status, apiError.detail));
    } finally {
      if (generateAbortRef.current === controller) {
        generateAbortRef.current = null;
      }
      setPreviewing(false);
    }
  }, [
    materializeFor,
    materializeWorld,
    materializeSection,
    materializeFolder,
    titleDraft,
    filenameDraft,
    targetPreview?.slug,
    resolveTarget,
  ]);

  const handleCancelGenerate = useCallback(() => {
    generateAbortRef.current?.abort();
    generateAbortRef.current = null;
    setPreviewing(false);
  }, []);

  // Confirm — issue the single-use edit-confirmation token (kind=new,
  // edit_id=proposal_id, proposed_content=content) and create through the
  // gated pipeline; the digest binds the exact previewed content (R-IM-05).
  const handleConfirmPreview = useCallback(async () => {
    if (!preview || !materializeWorld) return;
    setConfirming(true);
    setActionError(null);
    setMaterializeError(null);
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
      setMaterializeError(apiErrorMessage(err));
    } finally {
      setConfirming(false);
    }
  }, [
    preview,
    materializeWorld,
    mutateDetail,
    mutateList,
    closeMaterialize,
    apiErrorMessage,
    showToast,
    t,
  ]);

  // Legacy fallback (R-IM-10): mark the idea as used in the world WITHOUT
  // creating a ficha, via the original POST /api/ideas/{slug}/materialize.
  const handleMarkUsedOnly = useCallback(async () => {
    if (!materializeFor || !materializeWorld) {
      setMaterializeError(t("ideas.materialize.error.selectWorldMark"));
      return;
    }
    setMarkingUsed(true);
    setActionError(null);
    setMaterializeError(null);
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
      setMaterializeError(apiErrorMessage(err));
    } finally {
      setMarkingUsed(false);
    }
  }, [
    materializeFor,
    materializeWorld,
    mutateDetail,
    mutateList,
    closeMaterialize,
    apiErrorMessage,
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
  // Single source of truth for "a modal owns the screen" (Fix 2): extend this
  // expression when a new dialog is added; every modal must disable the `⋯`
  // menu so it can never be opened behind an overlay.
  const isModalOpen =
    titleDialogOpen || imageDialogOpen || !!pdfTarget || !!materializeFor;

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
            {/* Header row: title + badges + actions. From `lg` up the row is a
                single line and the TITLE is the only item that gives — it
                shrinks with an ellipsis (full text kept in `title`). That
                keeps the badges and the actions on the title's line, so the
                buttons can never wrap onto a second row and read as offset
                from the title/badges. Below `lg` the row still wraps, which
                the compact layout needs. */}
            <div className="flex flex-wrap items-center gap-2 lg:flex-nowrap">
              <h2
                className="min-w-0 font-heading text-h2 text-primary lg:truncate"
                title={selectedIdea.title || selectedIdea.slug}
              >
                {selectedIdea.title || selectedIdea.slug}
              </h2>
              <span className="shrink-0 rounded-full bg-action/10 px-2.5 py-0.5 text-xs text-action">
                {t(TYPE_LABELS[selectedIdea.type])}
              </span>
              <span className="shrink-0 rounded-full bg-surface-raised px-2.5 py-0.5 text-xs text-muted">
                {t(STATUS_LABELS[selectedIdea.status])}
              </span>
              <div className="ml-auto flex shrink-0 items-center gap-2">
                {/* DM-2: the primary action stays visible (it turns an idea
                    into canon); exports + edits live in the `⋯` menu. */}
                <button
                  type="button"
                  onClick={openMaterialize}
                  className="flex items-center gap-1.5 rounded-md border border-edge bg-surface px-2.5 py-1 text-xs font-medium text-primary transition-colors hover:border-action/40 hover:text-action"
                >
                  <Icon name="world" size={13} />
                  {t("ideas.materialize.button")}
                </button>
                <DetailActionsMenu
                  disabled={isModalOpen}
                  onTitle={() => {
                    setTitleDialogError(null);
                    setTitleDialogOpen(true);
                  }}
                  onImage={() => {
                    setImageDialogError(null);
                    setImageDialogOpen(true);
                  }}
                  onExportDocx={() => void handleExportIdeaDocx()}
                  onExportPdf={handleExportIdeaPdf}
                />
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

          {/* DM-2: ONE collapsible metadata section directly below the
              title/metadata rows and above the body image — Clasificación +
              version history. Default COLLAPSED; the control exposes
              `aria-expanded`. */}
          <section className="mb-4 rounded-lg border border-edge bg-surface-raised">
            <button
              type="button"
              onClick={() => setDetailsOpen((prev) => !prev)}
              aria-expanded={detailsOpen}
              aria-controls="idea-details-panel"
              className="flex w-full items-center gap-2 px-4 py-3 text-left text-body font-medium text-primary transition-colors hover:bg-surface-hover"
            >
              <Icon
                name={detailsOpen ? "chevron-down" : "chevron-right"}
                size={14}
                className="text-muted"
              />
              {t("ideas.detail.detailsHeading")}
            </button>
            {detailsOpen && (
              <div
                id="idea-details-panel"
                className="space-y-4 border-t border-edge px-4 py-4"
              >
                {/* Clasificación (type correction) */}
                <section aria-label={t("ideas.detail.reclassifyAria")}>
                  <h3 className="mb-2 text-body font-medium text-primary">
                    {t("ideas.detail.classification")}
                  </h3>
                  <div className="flex flex-wrap items-center gap-2">
                    <select
                      aria-label={t("ideas.detail.typeAria")}
                      value={reclassifyType}
                      onChange={(e) =>
                        setReclassifyType(e.target.value as IdeaType)
                      }
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
                      disabled={
                        reclassifying || reclassifyType === selectedIdea.type
                      }
                      className="rounded-md bg-action px-3 py-1.5 text-xs font-medium text-action-text transition-colors hover:bg-action-hover disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      {reclassifying
                        ? t("ideas.detail.saving")
                        : t("ideas.detail.saveType")}
                    </button>
                  </div>
                </section>

                {/* Version history (R-10) — archived versions only. The live
                    frontmatter `version` is never shown as plain user text.
                    Rows are readable labels; the path stays available through
                    the icon-only copy action. */}
                <section aria-label={t("ideas.detail.versionsAria")}>
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
                    <ul
                      aria-label={t("ideas.detail.archivedAria")}
                      className="space-y-1"
                    >
                      {archivedVersions.map((v) => (
                        <li
                          key={v.version}
                          className="flex items-center justify-between gap-2 rounded-md bg-surface px-2.5 py-1.5 text-xs"
                        >
                          <span className="shrink-0 font-medium text-primary">
                            {t("ideas.detail.versionWithDate", {
                              version: v.version,
                              date: formatVersionDate(v.created_at),
                            })}
                          </span>
                          <button
                            type="button"
                            onClick={() => void handleCopyVersionPath(v.path)}
                            aria-label={t("ideas.detail.copyPathAria", {
                              version: v.version,
                            })}
                            title={t("ideas.detail.copyPathAria", {
                              version: v.version,
                            })}
                            className="rounded-md p-1 text-icon-muted transition-colors hover:bg-surface-hover hover:text-primary"
                          >
                            <Icon name="copy" size={13} />
                          </button>
                        </li>
                      ))}
                    </ul>
                  )}
                </section>
              </div>
            )}
          </section>

          {/* Body rendered as GFM markdown (R-1). Frontmatter is stripped
              inside MarkdownViewer (splitFrontmatter); no `mundo` prop by
              design — /api/ideas/media/... embeds pass through MarkdownImage.
              imageFit="contain" keeps exact proportions (no crop) so images
              of any resolution render consistently in the idea bank. */}
          <div className="mb-6">
            <MarkdownViewer content={selectedIdea.body} imageFit="contain" />
          </div>

          {/* Attach image, edit title and reclassify now live in the `⋯`
              options menu / the collapsible metadata section (DM-2). The idea
              body rendering above stays untouched. */}

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

      {/* Export to PDF dialog — opened from the `⋯` menu item. mundo=""
          keeps the idea's absolute /api/ideas/... image URLs untouched
          (MarkdownImage passes them through unchanged). */}
      {pdfTarget && (
        <ExportPdfDialog
          open={!!pdfTarget}
          onClose={() => setPdfTarget(null)}
          content={pdfTarget.content}
          fileName={pdfTarget.fileName}
          mundo=""
        />
      )}

      {/* Title / image dialogs — opened from the `⋯` options menu (DM-2).
          Each carries its own modal-scoped error (Fix 1). */}
      <TitleDialog
        open={titleDialogOpen}
        value={editTitle}
        canSave={
          !!selectedIdea && editTitle.trim() !== (selectedIdea.title ?? "")
        }
        saving={savingTitle}
        error={titleDialogError}
        onChange={setEditTitle}
        onSave={() => void handleEditTitle()}
        onClose={() => {
          setTitleDialogError(null);
          setTitleDialogOpen(false);
        }}
      />
      <ImageDialog
        open={imageDialogOpen}
        mediaPath={selectedIdea?.media_path ?? null}
        attaching={attachingMedia}
        error={imageDialogError}
        onAttach={handleAttachMedia}
        onClose={() => {
          setImageDialogError(null);
          setImageDialogOpen(false);
        }}
      />

      {/* Materialize dialog — its INITIAL mode is the world/section/folder
          picker (DM-2), so the picker never stacks another modal. Previsualizar
          advances to destination (or collision); generation then swaps to
          progress → content. */}
      {materializeFor && (
        <MaterializePreviewDialog
          preview={preview}
          targetPreview={targetPreview}
          collision={collision}
          previewing={previewing}
          materializeError={materializeError}
          elapsedSeconds={elapsedSeconds}
          confirming={confirming}
          titleDraft={titleDraft}
          onTitleChange={handleTitleChange}
          onTitleFocus={handleTitleFocus}
          onTitleBlur={handleTitleBlur}
          filenameDraft={filenameDraft}
          onFilenameChange={handleFilenameChange}
          onFilenameFocus={handleFilenameFocus}
          onFilenameBlur={handleFilenameBlur}
          onApplySuggestedSlug={handleApplySuggestedSlug}
          onConfirm={() => void handleConfirmPreview()}
          onGenerate={() => void handleGenerateContent()}
          onCancelGenerate={handleCancelGenerate}
          onClose={closeMaterializeDialog}
          onCancelPicker={closeMaterialize}
          worlds={worlds}
          materializeWorld={materializeWorld}
          materializeSection={materializeSection}
          materializeFolder={materializeFolder}
          folderNodes={folderNodes}
          folderLoading={folderLoading}
          markingUsed={markingUsed}
          onWorldChange={setMaterializeWorld}
          onSectionChange={(value) => {
            setMaterializeSection(value);
            setMaterializeFolder("");
          }}
          onFolderChange={setMaterializeFolder}
          onPreview={() => void handleResolveTarget()}
          onMarkUsedOnly={() => void handleMarkUsedOnly()}
        />
      )}
    </EditorLayout>
  );
}