import { useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { useWorlds } from "@/hooks/useWorlds";
import { useCurrentWorld } from "@/hooks/useCurrentWorld";
import { setCurrentWorld } from "@/lib/currentWorld";
import { WikiHomeLayout } from "@/components/templates/WikiHomeLayout";
import { CategoryCard } from "@/components/molecules/CategoryCard";
import { EmptyState } from "@/components/organisms/EmptyState";
import { ErrorBanner } from "@/components/organisms/ErrorBanner";
import { Spinner } from "@/components/atoms/Spinner";
import { Button } from "@/components/atoms/Button";
import { Icon } from "@/components/atoms/Icon";
import type { WorldInfo } from "@/api/types";

/**
 * Taller de Mundo shell (`/taller-mundo`).
 *
 * The free Core's world-workshop surface: pick a world and jump into its
 * connected sections (lore, personajes), the guided character flow,
 * and ficha PDF export — all already present in the wiki workspace.
 *
 * States:
 * - 🔀 Active world: redirects to `/wiki/:mundo`
 * - 🟡 Loading: spinner centered on page
 * - 🔴 Error: ErrorBanner with retry
 * - 🟢 Empty: EmptyState with message (no worlds configured yet)
 * - 🟢 Data: responsive grid of CategoryCards → `/wiki/:mundo`
 */
export default function WorldWorkshop() {
  const navigate = useNavigate();
  const { worlds, isLoading, error, mutate } = useWorlds();
  const { world: activeWorld } = useCurrentWorld();

  const activeWorldExists = Boolean(
    activeWorld && worlds.some((w) => w.name === activeWorld),
  );

  useEffect(() => {
    if (!activeWorld || !activeWorldExists) return;
    navigate(`/wiki/${encodeURIComponent(activeWorld)}`, { replace: true });
  }, [activeWorld, activeWorldExists, navigate]);

  const handleWorldClick = (world: WorldInfo) => {
    setCurrentWorld(world.name);
    navigate(`/wiki/${encodeURIComponent(world.name)}`);
  };

  /** World-level importer entry (UI1): open the import workflow for a world. */
  const handleImportClick = (world: WorldInfo) => {
    setCurrentWorld(world.name);
    navigate(`/wiki/${encodeURIComponent(world.name)}/importer`);
  };

  const getFileCount = (world: WorldInfo): number => {
    return world.lore_count + world.character_count + world.reference_count;
  };

  return (
    <WikiHomeLayout>
      <div className="col-span-full">
        <h1 className="font-heading text-h3 text-primary">
          Taller de Mundo
        </h1>
        <p className="mt-2 text-body text-muted">
          Construí tu mundo y mantenelo conectado: lore y personajes,
          con creación de personajes guiada y exportación de ficha a PDF.
        </p>
      </div>

      {isLoading && (
        <div className="col-span-full flex items-center justify-center py-24">
          <Spinner size="lg" />
        </div>
      )}

      {error && !isLoading && (
        <div className="col-span-full px-4 py-8">
          <ErrorBanner
            message="No se pudo cargar la lista de mundos. Verificá que el servidor esté corriendo."
            onRetry={() => mutate()}
          />
        </div>
      )}

      {!isLoading && !error && worlds.length === 0 && (
        <div className="col-span-full">
          <EmptyState
            icon="empty"
            message="No hay mundos disponibles. Creá un mundo primero."
          />
        </div>
      )}

      {!isLoading && !error && worlds.length > 0 && (
        <>
          {worlds.map((world) => (
            <div key={world.name} className="flex flex-col gap-2">
              <CategoryCard
                world={world}
                fileCount={getFileCount(world)}
                onClick={handleWorldClick}
              />
              {/* World-level import entry — read-only analysis until an
                  explicit gated approval runs (UI1/UI3). */}
              <Button
                variant="ghost"
                size="sm"
                onClick={() => handleImportClick(world)}
                className="w-full"
              >
                <Icon name="upload" size={14} />
                Importar contenido
              </Button>
            </div>
          ))}
        </>
      )}
    </WikiHomeLayout>
  );
}
