import { useEffect } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useWorlds } from "@/hooks/useWorlds";
import { WorldNotFound } from "@/components/organisms/WorldNotFound";
import { getCurrentWorld, setCurrentWorld } from "@/lib/currentWorld";
import { WikiHomeLayout } from "@/components/templates/WikiHomeLayout";
import { SectionCard } from "@/components/molecules/SectionCard";
import { EmptyState } from "@/components/organisms/EmptyState";
import { ErrorBanner } from "@/components/organisms/ErrorBanner";
import { FirstValueHandoff } from "@/components/organisms/FirstValueHandoff";
import { Spinner } from "@/components/atoms/Spinner";
import { Icon } from "@/components/atoms/Icon";
import { VALID_SECTIONS, SECTION_LABELS, ROUTES, type Section } from "@/lib/constants";
import { useAppLanguage } from "@/hooks/useAppLanguage";
import { useFirstValueHandoff } from "@/hooks/useFirstValueHandoff";
import type { WorldInfo } from "@/api/types";
import { cn } from "@/lib/utils";

/**
 * Wiki World page (`/wiki/:mundo`) — section cards landing page.
 *
 * Opening a valid route marks `mundo` as the active world (same-tab
 * localStorage) without navigating back.
 *
 * States:
 * - 🟡 Loading: spinner centered on page
 * - 🔴 Error: ErrorBanner with retry
 * - 🟢 Missing params: EmptyState with link back
 * - 🟢 World not found: error panel with link back
 * - 🟢 Data: responsive grid of SectionCards (lore, personajes)
 */
export default function WikiWorld() {
  const { t } = useAppLanguage();
  const navigate = useNavigate();
  const { mundo } = useParams<{ mundo: string }>();
  const { worlds, isLoading, error, mutate } = useWorlds();

  const world = worlds.find((w) => w.name === mundo);

  const { visible, complete } = useFirstValueHandoff(world?.name);

  useEffect(() => {
    if (mundo && world && getCurrentWorld() !== mundo) {
      setCurrentWorld(mundo);
    }
  }, [mundo, world]);

  const getCount = (w: WorldInfo, section: Section): number => {
    switch (section) {
      case "lore":
        return w.lore_count;
      case "personajes":
        return w.character_count;
      case "referencias":
        return w.reference_count;
    }
  };

  const handleSectionClick = (section: Section) => {
    if (!mundo) return;
    navigate(`/wiki/${encodeURIComponent(mundo)}/${section}`);
  };

  /** Relaciones y Canon entry (BLOQUE 4, W9): the relations graph lives
   *  under the Taller de Mundo surface, not a content section. */
  const handleRelacionesClick = () => {
    if (!mundo) return;
    navigate(ROUTES.RELACIONES_CANON.replace(":mundo", encodeURIComponent(mundo)));
  };

  return (
    <WikiHomeLayout>
      {isLoading && (
        <div className="col-span-full flex items-center justify-center py-24">
          <Spinner size="lg" />
        </div>
      )}

      {error && !isLoading && (
        <div className="col-span-full px-4 py-8">
          <ErrorBanner
            message={t("wikiHome.loadError")}
            onRetry={() => mutate()}
          />
        </div>
      )}

      {!isLoading && !error && !mundo && (
        <div className="col-span-full">
          <EmptyState
            icon="error"
            message={t("relaciones.missingParams")}
            actionLabel={t("wikiWorld.goHome")}
            onAction={() => navigate("/wiki")}
          />
        </div>
      )}

      {!isLoading && !error && mundo && !world && (
        <div className="col-span-full">
          <WorldNotFound mundo={mundo} />
        </div>
      )}

      {!isLoading && !error && world && (
        <>
          {visible && (
            <div className="col-span-full">
              <FirstValueHandoff
                worldName={world.name}
                onImport={() => {
                  complete();
                  navigate(
                    `/wiki/${encodeURIComponent(world.name)}/importer`,
                  );
                }}
                onWriteNote={() => {
                  complete();
                  navigate(`/wiki/${encodeURIComponent(world.name)}/lore`);
                }}
                onSetupAssistant={() => {
                  complete();
                  navigate("/perfil?tab=conexiones");
                }}
                onDismiss={complete}
              />
            </div>
          )}
          {VALID_SECTIONS.map((section) => (
            <SectionCard
              key={section}
              section={section}
              label={t(SECTION_LABELS[section])}
              fileCount={getCount(world, section)}
              onClick={() => handleSectionClick(section)}
            />
          ))}
          {/* Relaciones y Canon — W9/W12: semantic relations graph entry.
              Inline card (SectionCard meta is fixed to content sections). */}
          <button
            type="button"
            onClick={handleRelacionesClick}
            className={cn(
              "group flex w-full flex-col gap-3 rounded-xl border border-edge bg-surface-raised p-5 text-left transition-all",
              "hover:border-action/40 hover:bg-surface-hover",
              "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-action/50",
              "focus-visible:ring-offset-2 focus-visible:ring-offset-surface",
            )}
          >
            <div className="flex h-32 items-center justify-center rounded-lg bg-surface-raised/50 text-action transition-colors group-hover:bg-surface-raised">
              <Icon name="world" size={48} />
            </div>
            <div className="flex items-center justify-between">
              <h3 className="font-heading text-h4 text-primary transition-colors group-hover:text-action">
                {t("relaciones.title")}
              </h3>
              <Icon
                name="chevron-right"
                size={16}
                className="text-icon-muted/50 transition-colors group-hover:text-action"
              />
            </div>
            <p className="text-small text-muted">
              {t("wikiWorld.relacionesBody")}
            </p>
          </button>
        </>
      )}
    </WikiHomeLayout>
  );
}
