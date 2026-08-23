import { useState } from "react";
import { useParams } from "react-router-dom";
import { useWorlds } from "@/hooks/useWorlds";
import { Navbar } from "@/components/organisms/Navbar";
import { WikiHomeLayout } from "@/components/templates/WikiHomeLayout";
import GraphView from "@/components/GraphView";
import { EmptyState } from "@/components/organisms/EmptyState";
import { Icon } from "@/components/atoms/Icon";
import { GENERIC_TEASER_LABEL } from "@/lib/constants";
import { cn } from "@/lib/utils";

type TabKey = "grafo" | "conflictos" | "propuestas";

const TABS: readonly { key: TabKey; label: string }[] = [
  { key: "grafo", label: "Grafo" },
  { key: "conflictos", label: "Conflictos" },
  { key: "propuestas", label: "Propuestas" },
];

/**
 * Relaciones y Canon page (`/taller-mundo/:mundo/relaciones-canon`) — W9/W12.
 *
 * Three-tab shell (BLOQUE 4 · Slice A): "Grafo" is active by default and
 * renders the GraphView; "Conflictos" and "Propuestas" are follow-up slices
 * and render a "Próximamente" placeholder (no data, no actions).
 */
export default function RelacionesCanon() {
  const { mundo } = useParams<{ mundo: string }>();
  const { worlds } = useWorlds();
  const [activeTab, setActiveTab] = useState<TabKey>("grafo");

  return (
    <WikiHomeLayout
      header={<Navbar worlds={worlds} />}
    >
      <div className="col-span-full">
        <h1 className="font-heading text-h3 text-pergamino">
          Relaciones y Canon
        </h1>
        <p className="mt-2 text-body text-tinta-desvaida">
          Grafo de entidades del mundo, estados de certeza y conexiones.
        </p>
      </div>

      <div className="col-span-full">
        <div
          role="tablist"
          aria-label="Secciones de Relaciones y Canon"
          className="mb-4 flex gap-2 border-b border-filio"
        >
          {TABS.map((tab) => (
            <button
              key={tab.key}
              type="button"
              role="tab"
              aria-selected={activeTab === tab.key}
              onClick={() => setActiveTab(tab.key)}
              className={cn(
                "border-b-2 px-4 py-2 text-small font-medium transition-colors",
                activeTab === tab.key
                  ? "border-llamita text-llamita"
                  : "border-transparent text-tinta-desvaida hover:text-pergamino",
              )}
            >
              {tab.label}
            </button>
          ))}
        </div>

        {activeTab === "grafo" ? (
          mundo ? (
            <GraphView mundo={mundo} />
          ) : (
            <EmptyState
              icon="error"
              message="Faltan parámetros de ruta. Seleccioná un mundo desde la página principal."
            />
          )
        ) : (
          <div
            data-testid="placeholder-panel"
            className="flex flex-col items-center justify-center gap-2 rounded-xl border border-filio bg-madero py-24"
          >
            <Icon name="lightbulb" size={32} className="text-sombra" />
            <p className="text-body text-tinta-desvaida">
              {GENERIC_TEASER_LABEL}
            </p>
          </div>
        )}
      </div>
    </WikiHomeLayout>
  );
}