import { useEffect, useMemo, useState } from "react";
import type { MethodologyStatus, PublishedMethodology } from "@/api/types";
import { Spinner } from "@/components/atoms/Spinner";
import { EmptyState } from "@/components/organisms/EmptyState";
import { ErrorBanner } from "@/components/organisms/ErrorBanner";
import { TallerTree } from "@/components/organisms/TallerTree";
import { useAppLanguage } from "@/hooks/useAppLanguage";
import { groupSkillsByChat } from "@/lib/tallerStates";

/** Page-level methodology selection (REQ-SB-5). Structural type. */
interface MethodologySelection {
  skill_id: string;
  version: string;
}

interface MethodologyLibraryProps {
  /** World to activate versions for (the selected Taller de Mundo world). */
  world?: string;
  /** Active Taller SHORT KEY (Herramientas | Mundo | Ideas) — drives the
   *  contextual tree via `groupSkillsByState` (spec REQ-TRE-3/5). */
  activeTaller: string;
  /** Page-lifted library status (task 2.3): `null` while the first fetch is
   *  in flight (spinner). The component no longer fetches — the page owns
   *  `getMethodologyStatus` and shares the result with the right panel. */
  status: MethodologyStatus | null;
  /** Page-level selection: highlighted row + filter contract (SC-SB-2.3). */
  selected: MethodologySelection | null;
  /** Selection setter; the filter contract calls it with `null` when the
   *  query filters the selected row out. */
  onSelect: (sel: MethodologySelection | null) => void;
  /** Fetch/activation error surfaced by the page; retry re-runs the page
   *  fetch. */
  error?: string | null;
  onRetry?: () => void;
  /** UL-5: empty-state CTA — navigates the Author to the "Crear skill" tab
   *  (wired by the page through TallerExplorerSidebar). */
  onGoToCoCrear?: () => void;
  /** One-click chat update when the chat still pins an older version. */
  onUpdateCompanion?: (skillId: string, version: string) => void;
}

/**
 * Taller de Herramientas — methodology library (operational view).
 *
 * Slimmed to the mi-mundo explorer content (task 2.3): the heading now lives
 * in the EditorLayout sidebar shell, and `getMethodologyStatus` is lifted to
 * the page (shared with `MethodologyStatePanel`). This component lists
 * published methodology versions for the selected world and exposes a
 * client-side filter (SC-SB-1.1). Rows are selection + information only —
 * activation actions live in the right MethodologyStatePanel (the page owns
 * `activateMethodology` and refetches the shared status).
 */
export function MethodologyLibrary({
  world,
  activeTaller,
  status,
  selected,
  onSelect,
  error,
  onRetry,
  onGoToCoCrear,
  onUpdateCompanion,
}: MethodologyLibraryProps) {
  const { t } = useAppLanguage();
  /** Client-side filter over the grouped tree (SC-SB-1.1 "filters"). */
  const [query, setQuery] = useState("");

  const groups = useMemo(() => {
    if (!status) return null;
    return groupSkillsByChat(
      status.published,
      activeTaller,
      status.companions?.[world ?? ""] ?? [],
    );
  }, [status, activeTaller, world]);

  /** The filter-selection contract (SC-SB-2.3) needs the VISIBLE row set
   *  after the query: derived here and consumed by the effect below. */
  const filteredGroups = useMemo(() => {
    if (!groups) return null;
    const q = query.trim().toLowerCase();
    if (!q) return groups;
    const match = (skills: PublishedMethodology[]) =>
      skills.filter(
        (skill) =>
          skill.name.toLowerCase().includes(q) ||
          skill.skill_id.toLowerCase().includes(q),
      );
    return {
      enChat: match(groups.enChat),
      fueraDelChat: match(groups.fueraDelChat),
      sinTaller: match(groups.sinTaller),
    };
  }, [groups, query]);

  /** The filter-selection contract (SC-SB-2.3, REQ-TRE-12) needs the VISIBLE
   *  skill set after the query — one row per `skill_id`, so visibility is
   *  keyed by `skill_id` (version is navigation state, not row identity). */
  const visibleKeys = useMemo(() => {
    if (!filteredGroups) return new Set<string>();
    const keys = new Set<string>();
    for (const group of Object.values(filteredGroups)) {
      for (const skill of group) {
        keys.add(skill.skill_id);
      }
    }
    return keys;
  }, [filteredGroups]);

  /** Filter-selection contract (SC-SB-2.3, REQ-TRE-12): applying a filter
   *  preserves `selected` while its `skill_id` stays visible; when the
   *  selected skill is filtered out, the selection is cleared. The sidebar
   *  must NOT reset selection on filter changes where the skill (any version)
   *  is still present. */
  useEffect(() => {
    if (!selected) return;
    if (!visibleKeys.has(selected.skill_id)) {
      onSelect(null);
    }
  }, [visibleKeys, selected, onSelect]);

  // Fetch errors take precedence over the loading spinner so a failed first
  // load surfaces the retry surface instead of spinning forever.
  if (error) {
    return <ErrorBanner message={error} onRetry={onRetry} />;
  }

  if (!status) {
    return (
      <div className="flex justify-center py-16">
        <Spinner size="lg" />
      </div>
    );
  }

  const published = status.published ?? [];
  const isEmpty = published.length === 0;
  const noResults =
    !isEmpty &&
    Object.values(filteredGroups ?? {}).every((group) => group.length === 0);

  return (
    <section
      aria-label={t("methodology.library.sectionAria")}
      className="space-y-4"
    >
      <label className="flex flex-col gap-1 text-small text-muted">
        {t("methodology.library.search")}
        <input
          type="search"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder={t("methodology.library.searchPlaceholder")}
          className="rounded-lg bg-surface px-3 py-2 text-body text-primary outline-none focus:ring-2 focus:ring-action/50"
        />
      </label>

      {isEmpty ? (
        <EmptyState
          icon="empty"
          message={t("methodology.library.empty")}
          actionLabel={t("methodology.library.emptyCta")}
          onAction={onGoToCoCrear}
        />
      ) : noResults ? (
        <EmptyState icon="search" message={t("methodology.library.noResults")} />
      ) : (
        <TallerTree
          groups={filteredGroups ?? groups!}
          activeTaller={activeTaller}
          companions={world ? status.companions?.[world] ?? [] : []}
          onSelect={(skillId, version) => onSelect({ skill_id: skillId, version })}
          onUpdateCompanion={onUpdateCompanion}
          selected={selected}
        />
      )}
    </section>
  );
}