import { useEffect } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useWorlds } from "@/hooks/useWorlds";
import { getCurrentWorld, setCurrentWorld } from "@/lib/currentWorld";
import { Navbar } from "@/components/organisms/Navbar";
import { WikiHomeLayout } from "@/components/templates/WikiHomeLayout";
import { SectionCard } from "@/components/molecules/SectionCard";
import { EmptyState } from "@/components/organisms/EmptyState";
import { ErrorBanner } from "@/components/organisms/ErrorBanner";
import { Spinner } from "@/components/atoms/Spinner";
import { Icon } from "@/components/atoms/Icon";
import { Button } from "@/components/atoms/Button";
import { VALID_SECTIONS, SECTION_LABELS, ROUTES, type Section } from "@/lib/constants";
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
  const navigate = useNavigate();
  const { mundo } = useParams<{ mundo: string }>();
  const { worlds, isLoading, error, mutate } = useWorlds();

  const world = worlds.find((w) => w.name === mundo);

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

  const handleWorldChange = (newWorld: string) => {
    navigate(`/wiki/${encodeURIComponent(newWorld)}`, { replace: true });
  };

  return (
    <WikiHomeLayout
      header={
        <Navbar
          worlds={worlds}
          currentWorld={mundo}
          onWorldChange={handleWorldChange}
        />
      }
    >
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

      {!isLoading && !error && !mundo && (
        <div className="col-span-full">
          <EmptyState
            icon="error"
            message="Faltan parámetros de ruta. Seleccioná un mundo desde la página principal."
            actionLabel="Ir al inicio"
            onAction={() => navigate("/wiki")}
          />
        </div>
      )}

      {!isLoading && !error && mundo && !world && (
        <div className="col-span-full flex flex-col items-center justify-center gap-4 py-24">
          <div className="flex h-16 w-16 items-center justify-center rounded-full bg-piedra text-sangre">
            <Icon name="error" size={32} />
          </div>
          <h2 className="font-heading text-h3 text-pergamino">
            Mundo no encontrado
          </h2>
          <p className="text-body text-tinta-desvaida">
            No existe un mundo llamado "{mundo}".
          </p>
          <Button variant="secondary" onClick={() => navigate("/wiki")}>
            <Icon name="chevron-left" size={16} />
            Volver al inicio
          </Button>
        </div>
      )}

      {!isLoading && !error && world && (
        <>
          {VALID_SECTIONS.map((section) => (
            <SectionCard
              key={section}
              section={section}
              label={SECTION_LABELS[section]}
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
              "group flex w-full flex-col gap-3 rounded-xl border border-filio bg-madero p-5 text-left transition-all",
              "hover:border-llamita/40 hover:bg-piedra",
              "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-llamita/50",
              "focus-visible:ring-offset-2 focus-visible:ring-offset-cripta",
            )}
          >
            <div className="flex h-32 items-center justify-center rounded-lg bg-filio/50 text-llamita transition-colors group-hover:bg-filio">
              <Icon name="world" size={48} />
            </div>
            <div className="flex items-center justify-between">
              <h3 className="font-heading text-h4 text-pergamino transition-colors group-hover:text-llamita">
                Relaciones y Canon
              </h3>
              <Icon
                name="chevron-right"
                size={16}
                className="text-plata/50 transition-colors group-hover:text-llamita"
              />
            </div>
            <p className="text-small text-tinta-desvaida">
              Grafo de entidades, estados de certeza y conexiones
            </p>
          </button>
        </>
      )}
    </WikiHomeLayout>
  );
}
