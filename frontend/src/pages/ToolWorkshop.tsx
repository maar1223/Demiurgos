import { useState } from "react";
import { useWorlds } from "@/hooks/useWorlds";
import { Navbar } from "@/components/organisms/Navbar";
import { WorldSelector } from "@/components/molecules/WorldSelector";
import { MethodologyLibrary } from "@/components/organisms/MethodologyLibrary";
import { ErrorBanner } from "@/components/organisms/ErrorBanner";
import { Spinner } from "@/components/atoms/Spinner";

/**
 * Taller de Herramientas shell (`/taller-herramientas`).
 *
 * The free Core's methodology-workshop landing. Renders the methodology
 * library (view published → publish a validated draft → activate an immutable
 * version by world) and lets the Author pick which world receives the
 * activation via the shared world selector.
 *
 * States:
 * - 🟡 Loading: spinner centered on page
 * - 🔴 Error: ErrorBanner with retry
 * - 🟢 No world selected (or no worlds at all): the library still shows
 *   publications, but activation stays disabled ("Sin mundo")
 * - 🟢 Data: world selector + MethodologyLibrary
 */
export default function ToolWorkshop() {
  const { worlds, isLoading, error, mutate } = useWorlds();
  const [world, setWorld] = useState<string>();

  return (
    <div className="flex min-h-screen flex-col bg-cripta">
      <Navbar worlds={worlds} />
      <main className="mx-auto w-full max-w-7xl flex-1 px-4 py-8">
        <header className="mb-8">
          <h1 className="font-heading text-h3 text-pergamino">
            Taller de Herramientas
          </h1>
          <p className="mt-2 text-body text-tinta-desvaida">
            Metodologías de construcción seguras: editar, compilar, publicar
            versiones inmutables y activarlas por mundo.
          </p>
        </header>

        {isLoading ? (
          <div className="flex justify-center py-16">
            <Spinner size="lg" />
          </div>
        ) : error ? (
          <ErrorBanner
            message="No se pudo cargar la lista de mundos. Verificá que el servidor esté corriendo."
            onRetry={() => mutate()}
          />
        ) : (
          <>
            <div className="mb-6 flex flex-wrap items-center gap-3">
              <WorldSelector
                worlds={worlds}
                currentWorld={world}
                onWorldChange={setWorld}
              />
              <p className="text-small text-tinta-desvaida">
                {world
                  ? `Las activaciones se aplican a «${world}».`
                  : worlds.length > 0
                    ? "Elegí un mundo para poder activar versiones."
                    : "No hay mundos disponibles; podés ver publicaciones pero no activar."}
              </p>
            </div>
            <MethodologyLibrary world={world} />
          </>
        )}
      </main>
    </div>
  );
}