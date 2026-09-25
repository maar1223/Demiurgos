import type { GraphEntity } from "@/api/types";
import { Icon } from "@/components/atoms/Icon";
import { STATUS_META } from "@/lib/status";
import { cn } from "@/lib/utils";
import { useAppLanguage } from "@/hooks/useAppLanguage";

/** Content preview length — long ficha bodies never flood the panel. */
const CONTENT_PREVIEW_LIMIT = 280;

export interface NodeInspectorPanelProps {
  /** The selected entity whose metadata the panel renders. */
  entity: GraphEntity;
  /** Node keys currently visible in the graph (status/folder/orphan filter).
   *  Neighbors NOT in this set render as plain text (not clickable). */
  visibleEntityKeys: Set<string>;
  /** Node key → entity over the loaded entity set (neighbor resolution). */
  entityByKey: Map<string, GraphEntity>;
  /** Called when a clickable neighbor link is clicked. */
  onNeighborClick: (nodeKey: string) => void;
  /** Called when the "Open ficha" button is clicked. */
  onOpenFicha: () => void;
  /** Called when the close button is clicked. */
  onClose: () => void;
  /** Mundo name, shown for context in the metadata block. */
  mundo: string;
}

/** One neighbor entry after resolution: what to show and whether it links. */
interface LinkEntry {
  /** Display label (resolved entity name, or the raw reference). */
  label: string;
  /** Node key when the reference resolves to a loaded entity; null otherwise. */
  key: string | null;
  /** True only when the resolved neighbor is in the visible node set. */
  clickable: boolean;
}

/**
 * NodeInspectorPanel — right-hand inspector for a selected graph node.
 *
 * Pure presentational organism: GraphView owns the selection state and passes
 * the loaded entity plus the visible node-key set; the panel renders metadata
 * (name, type, status chip, path), neighbor links (forward/backlinks/
 * relaciones), and a truncated content preview. Zero data fetching — every
 * value comes from props, so the panel cannot trigger network requests.
 *
 * Neighbor resolution is best-effort: a reference (display name, path, or
 * canonical id) that matches a loaded entity renders as a clickable link when
 * that entity is visible; anything unresolvable or filtered out degrades to
 * plain text. Clicking a neighbor calls `onNeighborClick(key)` — the parent
 * decides what "navigate to neighbor" means (fitView centering).
 */
export function NodeInspectorPanel({
  entity,
  visibleEntityKeys,
  entityByKey,
  onNeighborClick,
  onOpenFicha,
  onClose,
  mundo,
}: NodeInspectorPanelProps) {
  const { t } = useAppLanguage();
  const statusMeta = entity.status ? STATUS_META[entity.status] : null;
  const preview = truncateContent(entity.content);

  const forwardEntries = entity.forward_links.map((ref) =>
    buildLinkEntry(ref, entityByKey, visibleEntityKeys),
  );
  const backEntries = entity.backlinks.map((ref) =>
    buildLinkEntry(ref, entityByKey, visibleEntityKeys),
  );
  const relacionEntries = entity.relaciones.map((rel) => {
    const { label, reference } = relacionEntry(rel);
    const built = buildLinkEntry(reference, entityByKey, visibleEntityKeys);
    // Prefer the resolved entity name; keep the raw label for unresolvable
    // entries (e.g. an object without id/name).
    return built.key ? built : { ...built, label };
  });

  return (
    <aside
      data-testid="node-inspector-panel"
      className="flex h-full flex-col border-l border-edge bg-surface-raised"
    >
      {/* Header: name + type + status chip + close */}
      <div className="flex items-start justify-between gap-2 border-b border-edge px-4 py-3">
        <div className="min-w-0">
          <h2 className="truncate font-heading text-h3 text-primary">
            {entity.name}
          </h2>
          <div className="mt-1 flex flex-wrap items-center gap-2 text-small text-muted">
            <span>{capitalize(entity.type)}</span>
            {statusMeta && (
              <span
                className={cn(
                  "rounded-full border px-2 py-0.5 text-xs",
                  statusMeta.chipClass,
                )}
              >
                {t(statusMeta.labelKey)}
              </span>
            )}
          </div>
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label={t("nodeInspector.closeAria")}
          className="shrink-0 rounded p-1 text-icon-muted transition-colors hover:bg-surface-hover hover:text-primary"
        >
          <Icon name="close" size={16} />
        </button>
      </div>

      {/* Body: metadata + neighbor lists + content preview + ficha action */}
      <div className="flex-1 space-y-4 overflow-y-auto px-4 py-3">
        {/* Path + world context */}
        <div>
          <span className="text-xs font-medium text-muted">{t("nodeInspector.path")}</span>
          <p className="mt-0.5 break-all text-small text-primary">
            {entity.path}
          </p>
          <p className="mt-0.5 text-xs text-muted">
            {t("nodeInspector.world", { world: mundo })}
          </p>
        </div>

        <LinkList
          title={t("nodeInspector.references")}
          entries={forwardEntries}
          onNeighborClick={onNeighborClick}
        />
        <LinkList
          title={t("nodeInspector.mentions")}
          entries={backEntries}
          onNeighborClick={onNeighborClick}
        />
        <LinkList
          title={t("nodeInspector.relations")}
          entries={relacionEntries}
          onNeighborClick={onNeighborClick}
        />

        {/* Content preview (truncated) */}
        <div>
          <span className="text-xs font-medium text-muted">
            {t("nodeInspector.content")}
          </span>
          {preview ? (
            <p className="mt-0.5 whitespace-pre-line text-small text-primary">
              {preview}
            </p>
          ) : (
            <p className="mt-0.5 text-small text-muted">
              {t("nodeInspector.noContent")}
            </p>
          )}
        </div>

        {/* Ficha access: clicking a node now selects it, so the ficha link
            lives here to preserve one-click navigation to the full page. */}
        <button
          type="button"
          onClick={onOpenFicha}
          className="w-full rounded border border-action bg-action/10 px-3 py-1.5 text-small font-medium text-action transition-colors hover:bg-action/20"
        >
          {t("nodeInspector.openFicha")}
        </button>
      </div>
    </aside>
  );
}

// ---------------------------------------------------------------------------
// Helpers (pure, exported for direct unit testing)
// ---------------------------------------------------------------------------

/** Strip [[wikilink]] brackets, if present. */
export function stripWikilink(reference: string): string {
  const match = reference.match(/^\[\[(.+)\]\]$/);
  return match ? match[1] : reference;
}

/** Resolve a neighbor reference (display name, path, or canonical id) to a
 *  node key over the loaded entity set. Null when nothing matches. */
export function resolveNeighborKey(
  reference: string,
  entityByKey: Map<string, GraphEntity>,
): string | null {
  const clean = stripWikilink(reference);
  for (const [key, candidate] of entityByKey) {
    // Backlinks from the indexer are entity paths; forward links are display
    // names; relaciones entries are canonical ids — match all three forms.
    if (
      key === clean ||
      candidate.id === clean ||
      candidate.name === clean ||
      candidate.path === clean
    ) {
      return key;
    }
  }
  return null;
}

/** Build a renderable LinkEntry for one forward/backlink reference. */
export function buildLinkEntry(
  reference: string,
  entityByKey: Map<string, GraphEntity>,
  visibleEntityKeys: Set<string>,
): LinkEntry {
  const key = resolveNeighborKey(reference, entityByKey);
  const label = key
    ? (entityByKey.get(key)?.name ?? stripWikilink(reference))
    : stripWikilink(reference);
  return { label, key, clickable: key !== null && visibleEntityKeys.has(key) };
}

/** Normalize a `relaciones` entry (string or object) to label + reference. */
export function relacionEntry(entry: unknown): {
  label: string;
  reference: string;
} {
  if (typeof entry === "string") {
    return { label: stripWikilink(entry), reference: stripWikilink(entry) };
  }
  if (entry && typeof entry === "object") {
    const obj = entry as Record<string, unknown>;
    const id = typeof obj.id === "string" ? obj.id : "";
    const name = typeof obj.name === "string" ? obj.name : "";
    const reference = id || name;
    const label = name || id || JSON.stringify(obj);
    return { label, reference };
  }
  return { label: String(entry), reference: String(entry) };
}

/** Truncate long content to the preview limit with an ellipsis suffix. */
export function truncateContent(content: string): string {
  if (content.length <= CONTENT_PREVIEW_LIMIT) return content;
  return content.slice(0, CONTENT_PREVIEW_LIMIT).trimEnd() + "…";
}

/** Capitalise the first letter of a string. */
function capitalize(value: string): string {
  if (!value) return value;
  return value.charAt(0).toUpperCase() + value.slice(1);
}

// ---------------------------------------------------------------------------
// Internal list renderer
// ---------------------------------------------------------------------------

function LinkList({
  title,
  entries,
  onNeighborClick,
}: {
  title: string;
  entries: LinkEntry[];
  onNeighborClick: (nodeKey: string) => void;
}) {
  const { t } = useAppLanguage();
  return (
    <div>
      <span className="text-xs font-medium text-muted">{title}</span>
      {entries.length === 0 ? (
        <p className="mt-0.5 text-small text-muted">{t("nodeInspector.none")}</p>
      ) : (
        <ul className="mt-0.5 space-y-0.5">
          {entries.map((entry, index) => (
            <li key={`${title}-${index}`} className="text-small">
              {entry.clickable ? (
                <button
                  type="button"
                  onClick={() => onNeighborClick(entry.key!)}
                  className="text-action transition-colors hover:underline"
                >
                  {entry.label}
                </button>
              ) : (
                <span className="text-primary">{entry.label}</span>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}