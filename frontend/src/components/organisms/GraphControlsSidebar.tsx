import { useState } from "react";
import type { FolderNode } from "@/lib/graphFilters";
import type { GraphStatusFilter } from "@/api/graph";
import type { SearchResult } from "@/api/types";
import { Icon } from "@/components/atoms/Icon";
import { Spinner } from "@/components/atoms/Spinner";
import { Switch } from "@/components/atoms/Switch";
import { FolderTreeNode } from "@/components/molecules/FolderTreeNode";
import { useAppLanguage } from "@/hooks/useAppLanguage";

interface GraphControlsSidebarProps {
  status: GraphStatusFilter;
  onStatusChange: (status: GraphStatusFilter) => void;
  selectedFolders: string[];
  onSelectedFoldersChange: (folders: string[]) => void;
  showOrphans: boolean;
  onShowOrphansChange: (show: boolean) => void;
  searchQuery: string;
  onSearchQueryChange: (query: string) => void;
  searchResults: SearchResult[];
  searching: boolean;
  searchError: string | null;
  onSelectResult: (result: SearchResult) => void;
  folderTree: FolderNode[];
  onFitView: () => void;
}

/**
 * Floating controls panel of the graph view, consolidating every control:
 * node search (input + results dropdown), status filter, hierarchical folder
 * tree, orphans toggle, and the "Ver todo" (fitView) button.
 *
 * PURE PRESENTATION component: every piece of state arrives as a prop and
 * every change is reported through a callback. No filter logic, no search
 * orchestration, no direct access to React Flow state — GraphView owns all
 * of that and passes the data down.
 *
 * Layout: a translucent panel that FLOATS over the canvas (S4) instead of
 * taking a column away from it — a header block of stacked labeled controls
 * above a scrollable body (the folder tree can grow long).
 */
export function GraphControlsSidebar({
  status,
  onStatusChange,
  selectedFolders,
  onSelectedFoldersChange,
  showOrphans,
  onShowOrphansChange,
  searchQuery,
  onSearchQueryChange,
  searchResults,
  searching,
  searchError,
  onSelectResult,
  folderTree,
  onFitView,
}: GraphControlsSidebarProps) {
  const { t } = useAppLanguage();
  // The panel floats over the map, so it must be collapsible: when collapsed
  // it becomes a single pill and gives the canvas every pixel back.
  const [collapsed, setCollapsed] = useState(false);
  /** Controlled single-folder toggle: add or remove `path` from the array. */
  const handleToggleFolder = (path: string) => {
    const next = selectedFolders.includes(path)
      ? selectedFolders.filter((p) => p !== path)
      : [...selectedFolders, path];
    onSelectedFoldersChange(next);
  };

  if (collapsed) {
    return (
      <button
        type="button"
        onClick={() => setCollapsed(false)}
        aria-expanded={false}
        aria-label={t("graph.showFilters")}
        className="absolute left-3 top-3 z-10 flex items-center gap-2 rounded-xl border border-edge/80 bg-surface/90 px-3 py-2 text-small font-medium text-primary shadow-lg backdrop-blur-md transition-colors hover:border-action/40 hover:text-action"
      >
        <Icon name="search" size={14} className="text-icon-muted" />
        {t("graph.filters")}
        <Icon name="chevron-right" size={14} className="text-muted" />
      </button>
    );
  }

  return (
    <aside className="absolute left-3 top-3 z-10 flex max-h-[calc(100%-1.5rem)] w-72 max-w-[calc(100%-1.5rem)] flex-col overflow-hidden rounded-xl border border-edge/80 bg-surface/85 shadow-xl backdrop-blur-md">
      {/* Title bar: the panel collapses into a pill instead of stealing map. */}
      <div className="flex items-center justify-between border-b border-edge/70 px-4 py-2">
        <span className="text-xs font-semibold uppercase tracking-wide text-muted">
          {t("graph.filters")}
        </span>
        <button
          type="button"
          onClick={() => setCollapsed(true)}
          aria-expanded={true}
          aria-label={t("graph.hideFilters")}
          className="rounded p-1 text-icon-muted transition-colors hover:bg-surface-hover hover:text-primary"
        >
          <Icon name="chevron-left" size={14} />
        </button>
      </div>

      {/* Header block: stacked labeled controls (search + status) */}
      <div className="space-y-3 border-b border-edge/70 px-4 py-3">
        {/* Node search: debounced server-side search with results dropdown */}
        <div className="space-y-1">
          <span className="text-xs font-medium text-muted">{t("graph.search")}</span>
          <div className="relative">
            <input
              type="text"
              value={searchQuery}
              onChange={(event) => onSearchQueryChange(event.target.value)}
              placeholder={t("graph.searchPlaceholder")}
              aria-label={t("graph.searchAria")}
              className="w-full rounded border border-edge bg-surface-raised px-2 py-1 text-small text-primary placeholder:text-muted focus:border-action focus:outline-none"
            />

            {searchQuery.trim().length > 0 && (
              <div
                role="listbox"
                aria-label={t("graph.resultsAria")}
                className="absolute left-0 top-full z-10 mt-1 max-h-64 w-full overflow-y-auto rounded-md border border-edge bg-surface-raised shadow-lg"
              >
                {searchError && (
                  <p className="px-3 py-2 text-xs text-status-error">
                    {searchError}
                  </p>
                )}
                {!searchError && searching && (
                  <div className="flex justify-center px-3 py-2">
                    <Spinner size="sm" />
                  </div>
                )}
                {!searchError && !searching && searchResults.length === 0 && (
                  <p className="px-3 py-2 text-xs text-muted">{t("graph.noResults")}</p>
                )}
                {searchResults.map((result) => (
                  <button
                    key={result.path}
                    type="button"
                    role="option"
                    onClick={() => onSelectResult(result)}
                    className="flex w-full items-center gap-2 border-b border-edge/50 px-3 py-2 text-left text-small text-primary transition-colors last:border-b-0 hover:bg-surface-hover"
                  >
                    <span className="truncate font-medium">{result.name}</span>
                    {result.type && (
                      <span className="shrink-0 rounded bg-surface-raised px-1.5 py-0.5 text-xs text-muted">
                        {capitalize(result.type)}
                      </span>
                    )}
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* Status filter */}
        <div className="space-y-1">
          <span className="text-xs font-medium text-muted">{t("graph.status")}</span>
          <select
            aria-label={t("graph.statusFilterAria")}
            value={status}
            onChange={(event) =>
              onStatusChange(event.target.value as GraphStatusFilter)
            }
            className="w-full rounded border border-edge bg-surface-raised px-2 py-1 text-small text-primary"
          >
            <option value="all">{t("graph.allStatuses")}</option>
            <option value="draft">{t("status.draft")}</option>
            <option value="stable">{t("status.stable")}</option>
          </select>
        </div>
      </div>

      {/* Scrollable body: folder tree + orphans toggle + fitView */}
      <div className="flex-1 overflow-y-auto px-4 py-4">
        {/* Folder tree: hierarchical multi-select with prefix semantics */}
        <div className="space-y-1">
          <span className="text-xs font-medium text-muted">{t("graph.section")}</span>
          <button
            type="button"
            onClick={() => onSelectedFoldersChange([])}
            className="mb-1 rounded px-1 py-0.5 text-small text-muted transition-colors hover:text-action"
          >
            {t("graph.allSections")}
          </button>
          <ul className="list-none">
            {folderTree.map((node) => (
              <FolderTreeNode
                key={node.path}
                node={node}
                selectedFolders={selectedFolders}
                onToggle={handleToggleFolder}
              />
            ))}
          </ul>
        </div>

        {/* Orphans toggle */}
        <div className="mt-4 flex items-center justify-between gap-2">
          <span className="text-small text-muted">{t("graph.showOrphans")}</span>
          <Switch
            checked={showOrphans}
            onChange={onShowOrphansChange}
            aria-label={t("graph.showOrphans")}
          />
        </div>

        {/* FitView */}
        <button
          type="button"
          onClick={onFitView}
          className="mt-4 w-full rounded border border-edge bg-surface-raised px-3 py-1 text-small text-primary transition-colors hover:border-action"
        >
          {t("graph.fitView")}
        </button>
      </div>
    </aside>
  );
}

/** Capitalise the first letter of the server-normalized (lowercase) type. */
function capitalize(value: string): string {
  if (!value) return value;
  return value.charAt(0).toUpperCase() + value.slice(1);
}