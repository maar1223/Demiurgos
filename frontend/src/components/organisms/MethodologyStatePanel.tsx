import { useState } from "react";
import type { MethodologyInventoryItem, MethodologyStatus } from "@/api/types";
import { Badge } from "@/components/atoms/Badge";
import { Button } from "@/components/atoms/Button";
import { Icon } from "@/components/atoms/Icon";
import { EmptyState } from "@/components/organisms/EmptyState";
import { ProvenanceBadge } from "@/components/organisms/CoCreation/ProvenanceBadge";
import { MethodologyComparePanel } from "@/components/molecules/MethodologyComparePanel";
import type { Lens } from "@/components/organisms/LensToggle";
import { useAppLanguage } from "@/hooks/useAppLanguage";
import { GLOBAL_ASSISTANT_CONTEXT } from "@/hooks/useAIAssistantSessions";
import { isTransversalSkill } from "@/lib/tallerStates";
import { isTriggerApproved } from "@/lib/triggerBound";
import {
  AXIS_SCOPE,
  AXIS_TERMS,
  AXIS_TERM_KEYS,
} from "@/lib/vocabularyAxes";

/** Registry scope term (axis-3) — reverse lookup so the panel never hardcodes
 *  axis vocabulary (spec R3: scope/conflict terms render only from the
 *  registry). */
const SCOPE_TERM_KEY =
  AXIS_TERM_KEYS[
    Object.entries(AXIS_TERMS).find(([, axis]) => axis === AXIS_SCOPE)?.[0] ?? ""
  ];

/** Numeric version rank: "1.4" and "1.4.0" compare equal; a prerelease tail is
 *  ignored on purpose (the library publishes plain versions). */
function versionRank(version: string): number[] {
  return version
    .split(/[.-]/)
    .map((part) => Number.parseInt(part, 10))
    .map((value) => (Number.isFinite(value) ? value : 0));
}

/** Descending comparison, so the newest version sorts first. */
function compareVersions(a: string, b: string): number {
  const left = versionRank(a);
  const right = versionRank(b);
  const length = Math.max(left.length, right.length);
  for (let index = 0; index < length; index += 1) {
    const diff = (right[index] ?? 0) - (left[index] ?? 0);
    if (diff !== 0) {
      return diff;
    }
  }
  return 0;
}

interface MethodologySelection {
  skill_id: string;
  version: string;
}

interface MethodologyStatePanelProps {
  /** Page-level selection (REQ-SB-5). Null renders the empty state. */
  selected: MethodologySelection | null;
  /** Library status from `getMethodologyStatus()` — versions are derived
   *  client-side by filtering on `skill_id` (no per-skill endpoint). */
  status: MethodologyStatus | null;
  /** Lens-scoped action set (SC-SB-4.1/4.2). */
  lens: Lens;
  /** World whose chat the "Añadir al chat" action targets (mi-mundo). */
  world?: string;
  /** Active Taller SHORT KEY (Herramientas | Mundo | Ideas) — the browsing
   *  context shared with the sidebar tree. Drives the "Alcance de taller" /
   *  "Conflicto" panel blocks (axis-binding-ui R3, REQ-TRE-6). */
  activeTaller?: string;
  onAdaptar: (item: MethodologyInventoryItem) => void;
  onComparar: (item: MethodologyInventoryItem) => void;
  /** Catalogo "Exportar" — resolves the `.zip` download; when it rejects the
   *  panel surfaces the inline export error (REQ-IMP-1: feedback moved from
   *  the catalog rows to this panel). */
  onExportar: (item: MethodologyInventoryItem) => Promise<void> | void;
  /** Chat toggle, page-owned (refetches status). `on` adds the selected
   *  version to the world's chat; false removes the skill from it. */
  onToggleCompanion?: (skillId: string, version: string, on: boolean) => void;
  /** Guided-flow activation, page-owned (refetches status). This is the pin
   *  the guided sessions read — NOT the chat companion and NOT the row you are
   *  viewing. Omitted only where the caller cannot pin (e.g. ideas-global). */
  onActivate?: (skillId: string, version: string) => void;
  /** World whose first-activation latency notice is active (R-UI notice). */
  latencyNoticeWorld?: string | null;
  /** Request in flight — disables the chat actions. */
  busy?: boolean;
  /** Clickable Versiones (UL-3): fired when a version row is clicked. */
  onSelect?: (selection: MethodologySelection) => void;
  /** Controlled compare selection (UL-4): when exactly two items are
   *  compared, the compare panel renders below the actions block. */
  compareSelection?: MethodologyInventoryItem[];
  onCompareClear?: () => void;
}

/**
 * Right state/actions panel for the "Taller" EditorLayout (REQ-SB-4).
 *
 * Renders versions derived from `getMethodologyStatus()` filtered by
 * `skill_id`, provenance via `ProvenanceBadge(parentSkillId/parentVersion)`
 * (SC-SB-4.3), talleres compatibles, etiquetas, and lens-appropriate actions:
 * mi-mundo → Adaptar + chat toggle (S1/S2/S5); catalogo → Adaptar + Comparar
 * + Exportar. Null selection renders an empty state (SC-SB-4.4).
 */
export function MethodologyStatePanel({
  selected,
  status,
  lens,
  world,
  activeTaller,
  onAdaptar,
  onComparar,
  onExportar,
  onSelect,
  onToggleCompanion,
  onActivate,
  latencyNoticeWorld,
  busy = false,
  compareSelection,
  onCompareClear,
}: MethodologyStatePanelProps) {
  const { t } = useAppLanguage();
  /** Export failure feedback (REQ-IMP-1): the right panel owns the inline
   *  alert the catalog rows used to render. */
  const [exportFailed, setExportFailed] = useState(false);
  /** Trigger description fold state (UX): the approval badge stays visible
   *  while the (potentially long) description can be collapsed. */
  const [triggerOpen, setTriggerOpen] = useState(true);
  /** Version disclosure: newest + active + in-view stay visible; the rest fold
   *  behind "Ver versiones anteriores". Declared with the other hooks because
   *  the empty state returns before the derived values exist. */
  const [showAllVersions, setShowAllVersions] = useState(false);

  if (!selected) {
    return (
      <EmptyState
        icon="empty"
        message={t("methodology.state.empty")}
      />
    );
  }

  const published = status?.published ?? [];
  const entry = published.find(
    (item) =>
      item.skill_id === selected.skill_id && item.version === selected.version,
  );
  /** Every published version of this skill (SC-SB-4: "versions filtered by
   *  skill_id"), newest first. */
  const versions = published
    .filter((item) => item.skill_id === selected.skill_id)
    .sort((a, b) => compareVersions(a.version, b.version));

  /** Action payload: the selected published entry as an inventory item.
   *  `clasificacion`/`trust_attributes` default when the published record
   *  omits them. */
  const item: MethodologyInventoryItem = entry
    ? {
        ...entry,
        clasificacion: entry.clasificacion ?? null,
        trust_attributes: entry.trust_attributes ?? [],
      }
    : {
        skill_id: selected.skill_id,
        version: selected.version,
        name: selected.skill_id,
        description: "",
        digest: "",
        published_at: "",
      };

  const talleresCompatibles = entry?.talleres_compatibles ?? [];
  const etiquetas = entry?.etiquetas ?? [];
  /** Etapa 2 trigger approval state (D4): the selected version's approved
   *  trigger is shown distinguishably from an unapproved/legacy one. */
  /** The index label: the authored trigger when present, else the legacy
   *  description (records that predate the separate field). */
  const triggerText = entry?.trigger ?? entry?.description ?? "";
  const triggerApproved = isTriggerApproved(
    entry?.trigger_approval,
    triggerText,
  );
  /** Foundational skills ship with the product: their trigger is approved by
   *  Demiurgos itself, never by an Author draft. Showing them as "pending"
   *  would misreport distrust of the product's own methodology, so they get a
   *  distinguishable product-approval state instead of a fabricated audit
   *  row (the server deliberately installs them with no author approval). */
  const isFoundational = (entry?.trust_attributes ?? []).includes("fundacional");
  /** Stable id for the collapsible trigger body (`aria-controls` target). */
  const triggerBodyId = `methodology-trigger-body-${selected.skill_id}-${selected.version}`;
  const isMiMundo = lens === "mi-mundo";
  /** Companions of the current world (status-derived; absent key → none).
   *  The selected version is ON when it appears in this list. */
  const companions = world ? status?.companions?.[world] ?? [] : [];
  /** One companion slot per skill_id: the chat uses exactly the pinned
   *  version. A newer published version is NOT the one in the chat, so the
   *  action must never read as "add" while the skill is already there. */
  const companion = companions.find(
    (entry) => entry.skill_id === selected.skill_id,
  ) ?? null;
  const isCompanion = companion?.version === selected.version;
  const pinnedVersion = companion && !isCompanion ? companion.version : null;
  /** ideas-global is the assistant's null-mundo context, NOT a workshop
   *  world: it never gets a chat block (the companion routes 404 it). */
  const isIdeasGlobal = world === GLOBAL_ASSISTANT_CONTEXT;
  /** The version the guided flow actually runs in this world. The version
   *  badge used to read "Seleccionada" for the row being VIEWED, which is a
   *  different thing and made "1.4 is selected" look like "1.4 is active"
   *  (2026-11-17: 1.4 was never activated and nobody could do it). */
  const activeActivation = world ? status?.activations?.[world] ?? null : null;
  const activeVersion =
    activeActivation && activeActivation.skill_id === selected.skill_id
      ? activeActivation.version
      : null;
  const isActiveVersion = activeVersion === selected.version;
  /** The rule the Owner asked for: always show the newest, keep the active and
   *  the one in view (they can be older), and collapse the rest behind a
   *  disclosure. Nothing is hidden that carries a badge. */
  const latestVersion = versions[0]?.version ?? null;
  const alwaysVisible = new Set(
    [latestVersion, activeVersion, selected.version].filter(
      (version): version is string => Boolean(version),
    ),
  );
  const hiddenVersions = versions.filter(
    (version) => !alwaysVisible.has(version.version),
  );
  const visibleVersions = showAllVersions ? versions : versions.filter(
    (version) => alwaysVisible.has(version.version),
  );

  /** Wraps the download so a rejection surfaces the inline alert instead of
   *  failing silently (REQ-IMP-1). */
  const handleExport = async (item: MethodologyInventoryItem) => {
    setExportFailed(false);
    try {
      await onExportar(item);
    } catch {
      setExportFailed(true);
    }
  };

  /** Axis-surface derivation (REQ-TRE-6): the selected skill is a
   *  transversal of the active Taller. */
  const isTransversal =
    entry != null &&
    activeTaller != null &&
    isTransversalSkill(entry, activeTaller);

  return (
    <section
      aria-label={t("methodology.state.sectionAria")}
      className="min-h-0 flex-1 space-y-6 overflow-y-auto pb-4"
    >
      {/* Versions (SC-SB-4) */}
      <div className="rounded-lg border border-edge bg-surface-raised p-4">
        <h3 className="font-heading text-small font-semibold text-primary">
          {t("methodology.state.versions")}
        </h3>
        {activeVersion && (
          <p className="mt-1 text-small text-muted">
            {t("methodology.state.activeVersion", { version: activeVersion })}
          </p>
        )}
        {versions.length === 0 ? (
          <p className="mt-2 text-small text-muted">
            {t("methodology.state.noVersions", {
              skillId: selected.skill_id,
            })}
          </p>
        ) : (
          <ul className="mt-3 space-y-2">
            {visibleVersions.map((version) => {
              const isCurrent = version.version === selected.version;
              const isActive = version.version === activeVersion;
              return (
                <li key={version.version}>
                  <button
                    type="button"
                    onClick={() =>
                      onSelect?.({
                        skill_id: selected.skill_id,
                        version: version.version,
                      })
                    }
                    className="flex w-full cursor-pointer flex-wrap items-center gap-2 rounded-md px-1 py-0.5 text-left text-small transition-colors hover:bg-surface-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-action/50"
                  >
                    <span className="font-medium text-primary">
                      v{version.version}
                    </span>
                    {isActive && (
                      <Badge variant="success">
                        {t("methodology.state.active")}
                      </Badge>
                    )}
                    {isCurrent && (
                      <Badge variant="info">
                        {t("methodology.state.selected")}
                      </Badge>
                    )}
                  </button>
                </li>
              );
            })}
          </ul>
        )}
        {hiddenVersions.length > 0 && (
          <button
            type="button"
            onClick={() => setShowAllVersions((current) => !current)}
            className="mt-2 cursor-pointer text-small text-action underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-action/50"
          >
            {showAllVersions
              ? t("methodology.state.hideOlder")
              : t("methodology.state.showOlder", {
                  count: hiddenVersions.length,
                })}
          </button>
        )}
      </div>

      {/* Etapa 2 trigger approval state (D4): no tree filtering — the
          unapproved state is visible here and never reads as ready-to-publish.
          The description is collapsible (UX): folding it keeps the panel
          short while the approval badge stays visible either way. */}
      <div className="rounded-lg border border-edge bg-surface-raised p-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h3 className="font-heading text-small font-semibold text-primary">
            {t("triggerApproval.title")}
          </h3>
          <span className="flex items-center gap-2">
            <span data-testid="methodology-trigger-badge">
              <Badge
                variant={
                  triggerApproved || isFoundational ? "success" : "warning"
                }
              >
                {triggerApproved
                  ? t("triggerApproval.badgeApproved")
                  : isFoundational
                    ? t("triggerApproval.badgeFoundational")
                    : t("triggerApproval.badgePending")}
              </Badge>
            </span>
            <button
              type="button"
              aria-expanded={triggerOpen}
              aria-controls={triggerBodyId}
              aria-label={t("methodology.state.triggerToggle")}
              onClick={() => setTriggerOpen((open) => !open)}
              className="rounded-md p-1 text-icon-muted transition-colors hover:bg-surface-hover hover:text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-action/50"
            >
              <Icon
                name={triggerOpen ? "chevron-down" : "chevron-right"}
                size={14}
              />
            </button>
          </span>
        </div>
        {triggerOpen && triggerText && (
          <p
            id={triggerBodyId}
            className="mt-2 break-words text-small text-muted"
          >
            {triggerText}
          </p>
        )}
      </div>

      {/* Provenance (SC-SB-4.3) */}
      <div className="rounded-lg border border-edge bg-surface-raised p-4">
        <h3 className="font-heading text-small font-semibold text-primary">
          {t("methodology.state.origin")}
        </h3>
        <div className="mt-2">
          <ProvenanceBadge
            parentSkillId={entry?.parent_skill_id}
            parentVersion={entry?.parent_version}
          />
        </div>
        {!entry?.parent_skill_id && (
          <p className="mt-2 text-small text-muted">
            {t("methodology.state.rootSkill")}
          </p>
        )}
      </div>

      {/* Talleres compatibles */}
      {talleresCompatibles.length > 0 && (
        <div className="rounded-lg border border-edge bg-surface-raised p-4">
          <h3 className="font-heading text-small font-semibold text-primary">
            {t("methodology.state.compatibleTalleres")}
          </h3>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {talleresCompatibles.map((taller) => (
              <Badge key={taller} variant="default">
                {taller}
              </Badge>
            ))}
          </div>
        </div>
      )}

      {/* Alcance de taller (axis-binding-ui R3): the registry scope term
       * renders ONLY in this panel block — never a primary badge. Shown when
       * the selected skill is a transversal of the active taller. */}
      {isTransversal && (
        <div className="rounded-lg border border-edge bg-surface-raised p-4">
          <h3 className="font-heading text-small font-semibold text-primary">
            {t("methodology.state.scopeTitle")}
          </h3>
          <div className="mt-2 flex flex-wrap gap-1.5">
            <span data-axis={AXIS_SCOPE} className="inline-flex">
              <Badge variant="default">{t(SCOPE_TERM_KEY)}</Badge>
            </span>
          </div>
        </div>
      )}

      {/* Etiquetas */}
      {etiquetas.length > 0 && (
        <div className="rounded-lg border border-edge bg-surface-raised p-4">
          <h3 className="font-heading text-small font-semibold text-primary">
            {t("methodology.state.etiquetas")}
          </h3>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {etiquetas.map((tag) => (
              <Badge key={tag} variant="info">
                {tag}
              </Badge>
            ))}
          </div>
        </div>
      )}

      {/* Lens-specific actions (SC-SB-4.1/4.2) */}
      <div className="rounded-lg border border-edge bg-surface-raised p-4">
        <h3 className="font-heading text-small font-semibold text-primary">
          {t("methodology.state.actions")}
        </h3>
        <div className="mt-3 flex flex-wrap gap-2">
          {isMiMundo ? (
            <>
              <Button
                variant="secondary"
                size="sm"
                onClick={() => onAdaptar(item)}
                title={t("methodology.state.adaptTitle")}
              >
                {t("methodology.state.adapt")}
              </Button>
              {onActivate !== undefined && Boolean(world) && (
                <Button
                  variant="primary"
                  size="sm"
                  disabled={!world || busy || isActiveVersion}
                  onClick={() => onActivate(selected.skill_id, selected.version)}
                  title={t("methodology.action.activateFlowTitle")}
                >
                  {t("methodology.action.activateFlow")}
                </Button>
              )}
            </>
          ) : (
            <>
              <Button
                variant="secondary"
                size="sm"
                onClick={() => onAdaptar(item)}
                title={t("methodology.state.adaptTitle")}
              >
                {t("methodology.state.adapt")}
              </Button>
              <Button variant="secondary" size="sm" onClick={() => onComparar(item)}>
                {t("methodology.state.compare")}
              </Button>
              <Button
                variant="secondary"
                size="sm"
                onClick={() => void handleExport(item)}
              >
                {t("methodology.state.export")}
              </Button>
            </>
          )}
        </div>

        {exportFailed && (
          <p
            role="alert"
            className="mt-3 rounded-md border border-status-error/30 bg-status-error/10 px-3 py-2 text-xs text-status-error"
          >
            {t("methodology.state.exportError")}
          </p>
        )}

        {/* Chat block (S1/S5): names the real effect — adding/removing a
         *  skill from the world's chat. The chat routes on its own (S3); this
         *  block never pins a guided method. */}
        {isMiMundo && !isIdeasGlobal && (
          <div className="mt-4 space-y-3 border-t border-edge pt-4">
            <div>
              <p className="text-small font-medium text-primary">
                {t("methodology.chat.title", { world: world ?? "" })}
              </p>
              <p className="mt-1 text-small text-muted">
                {t("methodology.chat.helper")}
              </p>
            </div>
            {pinnedVersion ? (
              <>
                <p className="text-small text-muted">
                  {t("methodology.chat.pinnedVersion", {
                    version: pinnedVersion,
                  })}
                </p>
                <div className="flex flex-wrap gap-2">
                  <Button
                    variant="primary"
                    size="sm"
                    disabled={!world || busy}
                    onClick={() =>
                      onToggleCompanion?.(
                        selected.skill_id,
                        selected.version,
                        true,
                      )
                    }
                  >
                    {t("methodology.chat.useVersion", {
                      version: selected.version,
                    })}
                  </Button>
                  <Button
                    variant="secondary"
                    size="sm"
                    disabled={!world || busy}
                    onClick={() =>
                      onToggleCompanion?.(
                        selected.skill_id,
                        companion!.version,
                        false,
                      )
                    }
                  >
                    {t("methodology.chat.remove")}
                  </Button>
                </div>
              </>
            ) : (
              <Button
                variant={isCompanion ? "secondary" : "primary"}
                size="sm"
                disabled={!world || busy}
                onClick={() =>
                  onToggleCompanion?.(
                    selected.skill_id,
                    selected.version,
                    !isCompanion,
                  )
                }
              >
                {isCompanion
                  ? t("methodology.chat.remove")
                  : t("methodology.chat.add")}
              </Button>
            )}
            {latencyNoticeWorld === world && (
              <p className="text-small text-muted">
                {t("methodology.state.latencyNotice")}
              </p>
            )}
          </div>
        )}
      </div>

      {/* Guided assistant (S1/S6): the method is chosen at session start,
          never pinned from this library. */}
      {isMiMundo && (
        <div className="rounded-lg border border-edge bg-surface-raised p-4">
          <h3 className="font-heading text-small font-semibold text-primary">
            {t("methodology.guided.title")}
          </h3>
          <p className="mt-2 text-small text-muted">
            {t("methodology.guided.info")}
          </p>
        </div>
      )}

      {/* Compare panel (UL-4): rendered in the right panel area, below the
       *  actions block, when exactly two items are compared. The clear
       *  control moved here with the panel (REQ-LIB-7). */}
      {compareSelection && compareSelection.length === 2 && (
        <div className="space-y-2">
          <div className="flex justify-end">
            <Button variant="ghost" size="sm" onClick={onCompareClear}>
              {t("methodology.state.clear")}
            </Button>
          </div>
          <MethodologyComparePanel
            a={compareSelection[0]}
            b={compareSelection[1]}
          />
        </div>
      )}
    </section>
  );
}

export default MethodologyStatePanel;