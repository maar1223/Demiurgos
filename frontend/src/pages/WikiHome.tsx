import { useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { useWorlds } from "@/hooks/useWorlds";
import { useCurrentWorld } from "@/hooks/useCurrentWorld";
import { WikiHomeLayout } from "@/components/templates/WikiHomeLayout";
import { CategoryCard } from "@/components/molecules/CategoryCard";
import { EmptyState } from "@/components/organisms/EmptyState";
import { ErrorBanner } from "@/components/organisms/ErrorBanner";
import { Spinner } from "@/components/atoms/Spinner";
import type { WorldInfo } from "@/api/types";

/**
 * Wiki Home page (`/wiki`).
 *
 * States:
 * - 🔀 Active world: redirects to `/wiki/:mundo`
 * - 🟡 Loading: spinner centered on page
 * - 🔴 Error: ErrorBanner with retry
 * - 🟢 Empty: EmptyState with message
 * - 🟢 Data: responsive grid of CategoryCards
 */
export default function WikiHome() {
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
    navigate(`/wiki/${encodeURIComponent(world.name)}`);
  };

  // Total file count across all sections
  const getFileCount = (world: WorldInfo): number => {
    return world.lore_count + world.character_count + world.reference_count;
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
            <CategoryCard
              key={world.name}
              world={world}
              fileCount={getFileCount(world)}
              onClick={handleWorldClick}
            />
          ))}
        </>
      )}
    </WikiHomeLayout>
  );
}
