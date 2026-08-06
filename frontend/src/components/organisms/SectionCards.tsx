import { useCallback, useEffect, useRef, useState } from "react";
import { Icon, type IconName } from "@/components/atoms/Icon";
import { CardMenu, type CardAction } from "@/components/organisms/CardMenu";
import { getMediaUrl } from "@/api/wiki";
import { cn } from "@/lib/utils";
import { STATUS_META } from "@/lib/status";
import {
  canDropToGridBackground,
  isFolderDropValid,
  joinPath,
  parentPath,
  readDragPayload,
  setDragPayload,
  type DragPayload,
  type DragState,
  type DropDnd,
} from "@/lib/dnd";
import type { FileNode } from "@/api/types";

/** Pending "new file / new subfolder" creation inside a directory card. */
export interface CreateTarget {
  path: string;
  kind: "file" | "subfolder";
}

interface SectionCardsProps {
  nodes: FileNode[];
  mundo: string;
  section: string;
  onSelect: (path: string) => void;
  onAction?: (action: CardAction, node: FileNode) => void;
  /** Path of the card whose name is being edited inline (S8). */
  renamingPath?: string | null;
  /** S14: node whose request is in flight — its actions stay disabled. */
  busyPath?: string | null;
  /** S34/S36: API error detail shown above the grid / inside the open menu. */
  actionError?: string | null;
  /** Non-null while the "new file/subfolder" inline input is pending. */
  createTarget?: CreateTarget | null;
  /** Same-section move via drag & drop: from/to are section-relative paths. */
  onMove?: (from: string, to: string) => void;
  /** Section-relative path of the directory being browsed ("" = section root). */
  browsingDirPath?: string;
  /** Path of the node that should briefly highlight after a move. */
  movedPath?: string | null;
  onRenameCommit?: (node: FileNode, newName: string) => void;
  onRenameCancel?: () => void;
  onCreateCommit?: (name: string) => void;
  onCreateCancel?: () => void;
}

/**
 * Visual grid of directory and file cards for a section (or a subdirectory).
 *
 * Embedded in the WikiEditor content area when no file is selected: the
 * cards replace the old "Seleccioná un archivo" placeholder so the section
 * contents are browsable without leaving the editor. Directories render
 * first (tree order), then files.
 *
 * Each card lives in a `div.relative` wrapper: the full-size card button
 * plus an absolutely-positioned sibling ⋯ (CardMenu) — NEVER nested inside
 * the card button (S1). The single-open menu state is local (S5) and only
 * actions bubble up via `onAction` (presentational-pure, D1).
 *
 * Rename (S8) and "new file/subfolder" (S10) are inline inputs with LOCAL
 * validation (empty / path separators / sibling collision) that never fire a
 * request until valid. Cards render a cover image when `node.portada` is
 * resolved by the backend (?covers=true) — the image replaces the icon in
 * the card's 32-unit-tall media area.
 */
export function SectionCards({
  nodes,
  mundo,
  onSelect,
  onAction = () => {},
  renamingPath = null,
  busyPath = null,
  actionError = null,
  createTarget = null,
  onMove,
  browsingDirPath = "",
  movedPath = null,
  onRenameCommit,
  onRenameCancel,
  onCreateCommit,
  onCreateCancel,
}: SectionCardsProps) {
  // S5: at most one ⋯ menu open at a time — a single path value.
  const [openMenuPath, setOpenMenuPath] = useState<string | null>(null);

  const [renameDraft, setRenameDraft] = useState("");
  const [renameError, setRenameError] = useState<string | null>(null);

  const [createDraft, setCreateDraft] = useState("");
  const [createError, setCreateError] = useState<string | null>(null);

  // ── Drag & drop state (same-section moves) ──────────────────────────
  const [drag, setDrag] = useState<DragState | null>(null);
  const [absorbing, setAbsorbing] = useState<string | null>(null);
  const absorbTimer = useRef<number | null>(null);

  const handleDragStart = useCallback((payload: DragPayload) => {
    setDrag({ path: payload.path, is_dir: payload.is_dir, target: null });
  }, []);

  const handleDragEnd = useCallback(() => {
    setDrag(null);
  }, []);

  const handleTargetEnter = useCallback((path: string, valid: boolean) => {
    setDrag((prev) =>
      prev ? { ...prev, target: { path, valid } } : prev,
    );
  }, []);

  // Absorption animation (~150ms) BEFORE the actual move: the card shrinks
  // into the target, then onMove fires and the grid refreshes.
  const handleDropMove = useCallback(
    (from: string, to: string) => {
      setDrag(null);
      setAbsorbing(from);
      if (absorbTimer.current) window.clearTimeout(absorbTimer.current);
      absorbTimer.current = window.setTimeout(() => {
        setAbsorbing(null);
        onMove?.(from, to);
      }, 150);
    },
    [onMove],
  );

  // Grid background = "move one level up" (into the parent of the browsed
  // directory). Only events that never hit a card reach these handlers
  // (cards stop propagation).
  const handleBackgroundDragEnter = useCallback(
    (e: React.DragEvent) => {
      const dragged = readDragPayload(e.dataTransfer);
      if (!dragged) return;
      const valid = canDropToGridBackground(dragged, browsingDirPath);
      setDrag((prev) =>
        prev ? { ...prev, target: { path: "", valid } } : prev,
      );
    },
    [browsingDirPath],
  );

  const handleBackgroundDragOver = useCallback((e: React.DragEvent) => {
    if (drag) e.preventDefault();
  }, [drag]);

  const handleBackgroundDrop = useCallback(
    (e: React.DragEvent) => {
      const dragged = readDragPayload(e.dataTransfer);
      if (!dragged || !canDropToGridBackground(dragged, browsingDirPath)) {
        return;
      }
      e.preventDefault();
      const name = dragged.path.split("/").pop() ?? "";
      handleDropMove(dragged.path, joinPath(parentPath(browsingDirPath), name));
    },
    [browsingDirPath, handleDropMove],
  );

  const dnd: DropDnd = {
    drag,
    onDragStart: handleDragStart,
    onDragEnd: handleDragEnd,
    onTargetEnter: handleTargetEnter,
    onDropMove: handleDropMove,
  };

  const backgroundIsTarget = drag?.target?.path === "" && drag.target.valid;

  // Seed the rename draft when a new card enters rename mode.
  useEffect(() => {
    if (!renamingPath) return;
    const node = findTreeNode(nodes, renamingPath);
    setRenameDraft(node?.name ?? "");
    setRenameError(null);
  }, [renamingPath, nodes]);

  // Fresh input for every pending creation.
  useEffect(() => {
    setCreateDraft("");
    setCreateError(null);
  }, [createTarget]);

  const dirs = nodes.filter((n) => n.is_dir);
  const files = nodes.filter((n) => !n.is_dir);

  const handleRenameCommit = (node: FileNode) => {
    const baseError = validateName(renameDraft);
    if (baseError) {
      setRenameError(baseError);
      return;
    }
    const trimmed = renameDraft.trim();
    const collision = nodes.some(
      (n) =>
        n.path !== node.path &&
        n.name.toLowerCase() === trimmed.toLowerCase(),
    );
    if (collision) {
      setRenameError("Ya existe un archivo o carpeta con ese nombre");
      return;
    }
    onRenameCommit?.(node, trimmed);
  };

  const handleCreateCommit = () => {
    const baseError = validateName(createDraft);
    if (baseError) {
      setCreateError(baseError);
      return;
    }
    const trimmed = createDraft.trim();
    if (createTarget) {
      const dirNode = findTreeNode(nodes, createTarget.path);
      const collision = (dirNode?.children ?? []).some(
        (n) => n.name.toLowerCase() === trimmed.toLowerCase(),
      );
      if (collision) {
        setCreateError("Ya existe un archivo o carpeta con ese nombre");
        return;
      }
    }
    onCreateCommit?.(trimmed);
  };

  return (
    <div className="relative">
      {/* S34/S36: action errors never break the tree — inline banner above the grid */}
      {actionError && (
        <div
          role="alert"
          className="mb-4 flex items-start gap-3 rounded-lg border border-sangre/30 bg-sangre/10 p-3 text-small text-sangre"
        >
          <Icon name="error" size={16} className="mt-0.5 shrink-0" />
          <span>{actionError}</span>
        </div>
      )}

      <div
        data-testid="section-cards-drop-area"
        onDragEnter={handleBackgroundDragEnter}
        onDragOver={handleBackgroundDragOver}
        onDrop={handleBackgroundDrop}
      >
        {/* "Up one level" drop feedback — dashed llamita veil over the grid */}
        {backgroundIsTarget && (
          <div className="pointer-events-none absolute inset-0 z-10 flex items-center justify-center rounded-xl border-2 border-dashed border-llamita/60 bg-llamita/5">
            <span className="rounded-md bg-cripta/80 px-3 py-1 text-small text-llamita">
              Subir un nivel
            </span>
          </div>
        )}

        <div className="grid grid-cols-1 gap-4 tablet:grid-cols-2 desktop:grid-cols-3">
          {createTarget && (
            <CreateCard
              kind={createTarget.kind}
              draft={createDraft}
              error={createError}
              onChange={setCreateDraft}
              onCommit={handleCreateCommit}
              onCancel={() => onCreateCancel?.()}
            />
          )}

          {dirs.map((dir) => (
            <CardShell
              key={dir.path}
              node={dir}
              renaming={renamingPath === dir.path}
              openMenu={openMenuPath === dir.path}
              onOpenMenu={(open) => setOpenMenuPath(open ? dir.path : null)}
              onAction={onAction}
              busyPath={busyPath}
              menuError={openMenuPath === dir.path ? actionError : null}
              renameDraft={renameDraft}
              renameError={renameError}
              onRenameChange={setRenameDraft}
              onRenameCommit={() => handleRenameCommit(dir)}
              onRenameCancel={() => onRenameCancel?.()}
              mundo={mundo}
              onSelect={onSelect}
              dnd={dnd}
              absorbingPath={absorbing}
              movedPath={movedPath}
            />
          ))}

          {files.map((file) => (
            <CardShell
              key={file.path}
              node={file}
              renaming={renamingPath === file.path}
              openMenu={openMenuPath === file.path}
              onOpenMenu={(open) => setOpenMenuPath(open ? file.path : null)}
              onAction={onAction}
              busyPath={busyPath}
              menuError={openMenuPath === file.path ? actionError : null}
              renameDraft={renameDraft}
              renameError={renameError}
              onRenameChange={setRenameDraft}
              onRenameCommit={() => handleRenameCommit(file)}
              onRenameCancel={() => onRenameCancel?.()}
              mundo={mundo}
              onSelect={onSelect}
              dnd={dnd}
              absorbingPath={absorbing}
              movedPath={movedPath}
            />
          ))}
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Card shell — relative wrapper + absolute sibling ⋯ (S1) + card content
// ---------------------------------------------------------------------------

interface CardShellProps {
  node: FileNode;
  renaming: boolean;
  openMenu: boolean;
  onOpenMenu: (open: boolean) => void;
  onAction: (action: CardAction, node: FileNode) => void;
  busyPath: string | null;
  menuError: string | null;
  renameDraft: string;
  renameError: string | null;
  onRenameChange: (value: string) => void;
  onRenameCommit: () => void;
  onRenameCancel: () => void;
  mundo: string;
  onSelect: (path: string) => void;
  dnd?: DropDnd;
  absorbingPath?: string | null;
  movedPath?: string | null;
}

function CardShell({
  node,
  renaming,
  openMenu,
  onOpenMenu,
  onAction,
  busyPath,
  menuError,
  renameDraft,
  renameError,
  onRenameChange,
  onRenameCommit,
  onRenameCancel,
  mundo,
  onSelect,
  dnd,
  absorbingPath = null,
  movedPath = null,
}: CardShellProps) {
  return (
    <div className="relative">
      {/* Sibling ⋯ button — absolutely positioned on the TITLE line (S1 keeps
          it outside the card button: a button cannot nest a button). Dirs with
          a badge sit one line higher than plain files (badge is below the
          title, so the title line sits ~34px above the card bottom). */}
      <div
        className={cn(
          "absolute right-3 z-10",
          node.is_dir && node.children !== undefined
            ? "bottom-[34px]"
            : "bottom-3",
        )}
      >
        <CardMenu
          node={node}
          open={openMenu}
          onOpenChange={onOpenMenu}
          onAction={onAction}
          busyPath={busyPath}
          error={menuError}
        />
      </div>

      {renaming ? (
        <RenameCard
          node={node}
          draft={renameDraft}
          error={renameError}
          onChange={onRenameChange}
          onCommit={onRenameCommit}
          onCancel={onRenameCancel}
        />
      ) : (
        <CardButton
          node={node}
          mundo={mundo}
          onSelect={onSelect}
          dnd={dnd}
          absorbingPath={absorbingPath}
          movedPath={movedPath}
          busyPath={busyPath}
        />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Card button (dir or file) with optional cover image
// ---------------------------------------------------------------------------

function CardButton({
  node,
  mundo,
  onSelect,
  dnd,
  absorbingPath = null,
  movedPath = null,
  busyPath = null,
}: {
  node: FileNode;
  mundo: string;
  onSelect: (path: string) => void;
  dnd?: DropDnd;
  absorbingPath?: string | null;
  movedPath?: string | null;
  busyPath?: string | null;
}) {
  const isDir = node.is_dir;
  const badge =
    !isDir || node.children === undefined ? null : dirBadge(node);
  // Status dot: only for files with a KNOWN status — the backend omits the
  // field for unknown values (ideas "synced", no frontmatter) and dirs, and
  // the guard here keeps the card from ever lying even on a stale payload.
  const statusMeta = !isDir && node.status ? STATUS_META[node.status] : null;

  // ── Drag & drop feedback ───────────────────────────────────────────
  const isDragSource = dnd?.drag?.path === node.path;
  const isDropTarget = dnd?.drag?.target?.path === node.path;
  const targetValid = isDropTarget && !!dnd?.drag?.target?.valid;
  // Reddish tint on the dragged card while hovering an INVALID target.
  const invalidHover =
    isDragSource && !!dnd?.drag?.target && !dnd.drag.target.valid;
  const isAbsorbing = absorbingPath === node.path;
  const isBusy = busyPath === node.path;

  const handleDragStart = (e: React.DragEvent) => {
    if (!dnd) return;
    setDragPayload(e.dataTransfer, { path: node.path, is_dir: node.is_dir });
    e.dataTransfer.effectAllowed = "move";
    dnd.onDragStart({ path: node.path, is_dir: node.is_dir });
  };

  const handleDragEnd = () => {
    dnd?.onDragEnd();
  };

  const handleDragEnter = (e: React.DragEvent) => {
    if (!dnd?.drag) return;
    e.stopPropagation();
    // File cards are never valid targets — hovering them still reports an
    // invalid target so the ghost shows the sangre tint.
    const valid = node.is_dir && isFolderDropValid(dnd.drag, node.path);
    dnd.onTargetEnter(node.path, valid);
  };

  const handleDragOver = (e: React.DragEvent) => {
    if (!dnd?.drag) return;
    // Swallow drags on file cards too: the drop must fire HERE (as a no-op)
    // instead of bubbling to the grid background ("up one level").
    e.stopPropagation();
    e.preventDefault();
  };

  const handleDrop = (e: React.DragEvent) => {
    if (!dnd?.drag) return;
    e.stopPropagation();
    e.preventDefault();
    if (!node.is_dir) return;
    const dragged = readDragPayload(e.dataTransfer);
    if (!dragged || !isFolderDropValid(dragged, node.path)) return;
    const name = dragged.path.split("/").pop() ?? "";
    dnd.onDropMove(dragged.path, joinPath(node.path, name));
  };

  return (
    <button
      type="button"
      onClick={() => onSelect(node.path)}
      draggable={!!dnd}
      onDragStart={handleDragStart}
      onDragEnd={handleDragEnd}
      onDragEnter={handleDragEnter}
      onDragOver={handleDragOver}
      onDrop={handleDrop}
      className={cn(
        "group relative flex h-44 w-full flex-col overflow-hidden rounded-xl border border-filio bg-madero text-left transition-all hover:border-llamita/40 hover:bg-piedra focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-llamita/50 focus-visible:ring-offset-2 focus-visible:ring-offset-cripta",
        // Drag feedback: dimmed source, sangre tint on invalid hover,
        // llamita ring + slight grow on a valid folder target.
        isDragSource && "cursor-grabbing opacity-50 shadow-lg",
        invalidHover && "ring-2 ring-sangre/50",
        targetValid && "scale-[1.03] bg-piedra ring-2 ring-llamita",
        isAbsorbing && "scale-75 opacity-0",
        movedPath === node.path && "fade-slide-in",
        isBusy && "opacity-60",
      )}
    >
      {/* In-flight move feedback: dimmed card + small spinner overlay */}
      {isBusy && (
        <span className="absolute inset-0 z-10 flex items-center justify-center bg-cripta/40">
          <Icon name="spinner" size={24} className="animate-spin text-llamita" />
        </span>
      )}
      {/* Full-width media area: resolved portada image, or the icon as a
          large low-opacity backdrop so cover-less cards never look empty */}
      {!isDir && node.portada ? (
        <img
          src={getMediaUrl(mundo, node.portada)}
          alt={node.name}
          className="absolute inset-0 h-full w-full object-cover object-[center_25%] transition-transform duration-300 group-hover:scale-105"
          loading="lazy"
        />
      ) : (
        <div className="absolute inset-0 flex items-center justify-center">
          <Icon
            name={isDir ? "folder" : fileIconName(node.name)}
            size={56}
            className="text-llamita/30 transition-colors group-hover:text-llamita/45"
          />
        </div>
      )}

      {/* Bottom gradient — same veil over image and icon backdrops; gives
          the name (and the ⋯ replacing the chevron) permanent contrast */}
      <div className="pointer-events-none absolute inset-x-0 bottom-0 h-28 bg-gradient-to-t from-cripta/95 via-cripta/40 to-transparent" />

      {/* Name + optional badge — stacked so the name always gets full width
          (pr-7 reserves the title-line ⋯ spot, a sibling of the card) */}
      <div className="relative mt-auto flex flex-col gap-1 p-3">
        <h3 className="min-w-0 truncate pr-7 font-heading text-body text-pergamino transition-colors group-hover:text-llamita">
          {node.name}
        </h3>
        {badge && (
          <span className="self-start rounded-md bg-cripta/60 px-2 py-0.5 text-xs text-plata">
            {badge}
          </span>
        )}
      </div>

      {/* Status dot (item 14 follow-up): tiny circle in the card's top-right
          corner, over the media area, using the exact STATUS_META tokens of
          the file-bar chip. A pure-CSS tooltip (no native `title` — that one
          takes ~1s) appears instantly on hover: the wrapper's `group` class
          is the closest one, so `group-hover` fires when the dot itself is
          hovered, not the whole card. The dot keeps an aria-label for screen
          readers; the bubble is a visual duplicate (aria-hidden) and never
          affects the card button's accessible name. */}
      {statusMeta && (
        <span className="group absolute right-3 top-3">
          <span
            aria-label={statusMeta.label}
            className={cn(
              "block h-3 w-3 rounded-full border-2",
              statusMeta.dotClass,
            )}
          />
          <span
            aria-hidden="true"
            className="pointer-events-none absolute right-0 top-full z-20 mt-1.5 whitespace-nowrap rounded-md border border-filio bg-madero px-2 py-1 text-xs text-pergamino opacity-0 shadow-lg transition-opacity duration-75 group-hover:opacity-100"
          >
            {statusMeta.label}
          </span>
        </span>
      )}
    </button>
  );
}

// ---------------------------------------------------------------------------
// Inline rename card (S8): Enter commits, Escape/blur cancels, local errors
// ---------------------------------------------------------------------------

function RenameCard({
  node,
  draft,
  error,
  onChange,
  onCommit,
  onCancel,
}: {
  node: FileNode;
  draft: string;
  error: string | null;
  onChange: (value: string) => void;
  onCommit: () => void;
  onCancel: () => void;
}) {
  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") onCommit();
    else if (e.key === "Escape") onCancel();
  };

  return (
    <div className="flex w-full flex-col gap-3 rounded-xl border border-llamita/50 bg-madero p-5">
      <div className="flex h-32 items-center justify-center rounded-lg bg-filio/30">
        <Icon
          name={node.is_dir ? "folder" : fileIconName(node.name)}
          size={40}
          className="text-llamita/40"
        />
      </div>

      <input
        type="text"
        value={draft}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={handleKeyDown}
        onBlur={onCancel}
        autoFocus
        aria-label="Nuevo nombre"
        aria-invalid={!!error}
        className={cn(
          "w-full rounded-md border bg-piedra px-2 py-1.5 text-small text-pergamino",
          "focus:outline-none focus:ring-1",
          error
            ? "border-sangre/60 focus:border-sangre focus:ring-sangre/50"
            : "border-filio focus:border-llamita focus:ring-llamita/50",
        )}
      />

      {error && (
        <p role="alert" className="text-small text-sangre">
          {error}
        </p>
      )}

      <div className="mt-auto flex items-center justify-end text-plata/50">
        <Icon name="chevron-right" size={16} />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Pending "new file / new subfolder" card (S10): same inline pattern
// ---------------------------------------------------------------------------

function CreateCard({
  kind,
  draft,
  error,
  onChange,
  onCommit,
  onCancel,
}: {
  kind: "file" | "subfolder";
  draft: string;
  error: string | null;
  onChange: (value: string) => void;
  onCommit: () => void;
  onCancel: () => void;
}) {
  const placeholder =
    kind === "file" ? "Nombre del archivo…" : "Nombre de la subcarpeta…";

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") onCommit();
    else if (e.key === "Escape") onCancel();
  };

  return (
    <div className="flex w-full flex-col gap-3 rounded-xl border border-dashed border-llamita/40 bg-madero p-5">
      <div className="flex h-32 items-center justify-center rounded-lg bg-filio/30">
        <Icon
          name={kind === "file" ? "file" : "folder"}
          size={40}
          className="text-llamita/40"
        />
      </div>

      <input
        type="text"
        value={draft}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={handleKeyDown}
        onBlur={onCancel}
        autoFocus
        placeholder={placeholder}
        aria-label={placeholder}
        aria-invalid={!!error}
        className={cn(
          "w-full rounded-md border bg-piedra px-2 py-1.5 text-small text-pergamino",
          "focus:outline-none focus:ring-1",
          error
            ? "border-sangre/60 focus:border-sangre focus:ring-sangre/50"
            : "border-filio focus:border-llamita focus:ring-llamita/50",
        )}
      />

      {error && (
        <p role="alert" className="text-small text-sangre">
          {error}
        </p>
      )}

      <div className="mt-auto flex items-center justify-end text-plata/50">
        <Icon name="chevron-right" size={16} />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Local name validation (S8/S10): non-empty, no path separators. Collision
 * with existing siblings is checked by the caller against the current nodes.
 */
function validateName(name: string): string | null {
  const trimmed = name.trim();
  if (!trimmed) return "El nombre no puede estar vacío";
  if (trimmed.includes("/") || trimmed.includes("\\"))
    return "El nombre no puede contener '/'";
  return null;
}

/**
 * Recursively counts all files inside a directory node (direct + nested)
 * and all nested subdirectories, returning the card badge text.
 */
function dirBadge(node: FileNode): string {
  const fileCount = countFiles(node);
  const subdirCount = countDirs(node);
  if (fileCount > 0) {
    return `${fileCount} ${fileCount === 1 ? "archivo" : "archivos"}${
      subdirCount > 0
        ? `, ${subdirCount} ${subdirCount === 1 ? "subcarpeta" : "subcarpetas"}`
        : ""
    }`;
  }
  return "vacía";
}

/**
 * Recursively counts all files inside a directory node (direct + nested).
 */
function countFiles(node: FileNode): number {
  let count = 0;
  if (node.children) {
    for (const child of node.children) {
      if (!child.is_dir) count++;
      else count += countFiles(child);
    }
  }
  return count;
}

/**
 * Recursively counts all subdirectories inside a directory node.
 */
function countDirs(node: FileNode): number {
  let count = 0;
  if (node.children) {
    for (const child of node.children) {
      if (child.is_dir) {
        count++;
        count += countDirs(child);
      }
    }
  }
  return count;
}

/**
 * Depth-first search for a node by exact path.
 */
export function findTreeNode(
  nodes: FileNode[],
  path: string,
): FileNode | undefined {
  for (const node of nodes) {
    if (node.path === path) return node;
    if (node.is_dir && node.children) {
      const found = findTreeNode(node.children, path);
      if (found) return found;
    }
  }
  return undefined;
}

/**
 * Maps a file name to the icon that represents it: markdown for `.md`,
 * image for common image extensions, generic file otherwise.
 */
export function fileIconName(name: string): IconName {
  const lower = name.toLowerCase();
  if (lower.endsWith(".md")) return "markdown";
  if (/\.(jpg|jpeg|png|gif|webp)$/.test(lower)) return "image";
  return "file";
}
