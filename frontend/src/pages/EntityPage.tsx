import { useEffect, useState } from "react";
import { useParams, useNavigate, Link } from "react-router-dom";
import { useWorlds } from "@/hooks/useWorlds";
import { getCurrentWorld, setCurrentWorld } from "@/lib/currentWorld";
import { useBacklinks } from "@/hooks/useBacklinks";
import { EditorLayout } from "@/components/templates/EditorLayout";
import { EntityDetail } from "@/components/organisms/EntityDetail";
import { AIAssistantSidebar } from "@/components/organisms/AIAssistantSidebar";
import { TabBar } from "@/components/molecules/TabBar";
import type { SidebarTab } from "@/components/molecules/TabBar";
import { EmptyState } from "@/components/organisms/EmptyState";
import { Spinner } from "@/components/atoms/Spinner";
import { Button } from "@/components/atoms/Button";
import { Icon } from "@/components/atoms/Icon";
import { decodePathSegment, encodePathSegment } from "@/lib/utils";

/**
 * Entity detail page (`/wiki/:mundo/entity/*path`).
 *
 * Content-first layout: entity body rendered via `EntityDetail` in the main
 * area, sidebar with `TabBar` ([Asistente] | [Contexto]) for connections.
 *
 * States:
 * - 🟡 Loading worlds: Spinner
 * - 🔴 Missing params / world not found: EmptyState or error
 * - 🟢 No entity path: EmptyState "Seleccioná una entidad"
 * - 🟢 Ready: EntityDetail + sidebar connections
 */
export default function EntityPage() {
  const navigate = useNavigate();
  const { mundo, "*": splatPath } = useParams<{
    mundo: string;
    "*"?: string;
  }>();

  const entityName = splatPath ? decodePathSegment(splatPath) : undefined;

  // Sidebar tab — persisted in sessionStorage by TabBar
  const [sidebarTab, setSidebarTab] = useState<SidebarTab>(() => {
    if (typeof window === "undefined") return "asistente";
    const stored = sessionStorage.getItem("sidebar-tab");
    if (stored === "asistente" || stored === "contexto") return stored;
    return "asistente";
  });

  // World list for validation
  const { worlds, isLoading: worldsLoading } = useWorlds();

  const worldExists = worlds.some((w) => w.name === mundo);

  // Opening a valid route marks `mundo` as the active world (same-tab
  // localStorage) without navigating back.
  useEffect(() => {
    if (mundo && worldExists && getCurrentWorld() !== mundo) {
      setCurrentWorld(mundo);
    }
  }, [mundo, worldExists]);

  // Entity connections for Contexto tab
  const { links, isLoading: linksLoading } = useBacklinks(mundo, entityName);

  // Right panel content — always visible
  const rightPanelContent = (
    <div className="flex h-full flex-col">
      <TabBar onTabChange={setSidebarTab} />
      {sidebarTab === "asistente" ? (
        <AIAssistantSidebar mundo={mundo!} />
      ) : (
        <ConnectionsPanel
          mundo={mundo!}
          entityName={entityName}
          links={links}
          isLoading={linksLoading}
        />
      )}
    </div>
  );

  // --- Loading worlds ---
  if (worldsLoading) {
    return (
      <EditorLayout sidebar={null}>
        <div className="flex items-center justify-center py-24">
          <Spinner size="lg" />
        </div>
      </EditorLayout>
    );
  }

  // --- Missing mundo param ---
  if (!mundo) {
    return (
      <EditorLayout sidebar={null}>
        <EmptyState
          icon="error"
          message="Falta el parámetro de mundo. Seleccioná un mundo desde la página principal."
          actionLabel="Ir al inicio"
          onAction={() => navigate("/wiki")}
        />
      </EditorLayout>
    );
  }

  // --- World not found ---
  if (!worldExists) {
    return (
      <EditorLayout sidebar={null}>
        <div className="flex flex-col items-center justify-center gap-4 py-24">
          <div className="flex h-16 w-16 items-center justify-center rounded-full bg-surface-raised text-status-error">
            <Icon name="error" size={32} />
          </div>
          <h2 className="font-heading text-h3 text-primary">
            Mundo no encontrado
          </h2>
          <p className="text-body text-muted">
            No existe un mundo llamado "{mundo}".
          </p>
          <Button variant="secondary" onClick={() => navigate("/wiki")}>
            <Icon name="chevron-left" size={16} />
            Volver al inicio
          </Button>
        </div>
      </EditorLayout>
    );
  }

  // --- Ready ---
  return (
    <EditorLayout
      sidebar={null}
      rightPanel={rightPanelContent}
    >
      {!entityName ? (
        <EmptyState
          icon="search"
          message="Seleccioná una entidad para ver sus detalles."
          actionLabel="Ir al inicio"
          onAction={() => navigate("/wiki")}
        />
      ) : (
        <EntityDetail mundo={mundo} entityName={entityName} />
      )}
    </EditorLayout>
  );
}

// ---------------------------------------------------------------------------
// Connections Panel (Contexto tab content)
// ---------------------------------------------------------------------------

interface ConnectionsPanelProps {
  mundo: string;
  entityName?: string;
  links: { source: string; target: string; kind: string }[];
  isLoading: boolean;
}

/**
 * Renders entity connections inside the Contexto sidebar tab.
 *
 * States:
 * - 🟡 Loading: Spinner
 * - 🟢 No entity selected: EmptyState
 * - 🟢 No connections: EmptyState "Sin conexiones"
 * - 🟢 Ready: list of links with kind badges
 */
function ConnectionsPanel({
  mundo,
  entityName,
  links,
  isLoading,
}: ConnectionsPanelProps) {
  if (!entityName) {
    return (
      <div className="flex flex-1 items-center px-4">
        <EmptyState
          icon="search"
          message="Cargá una entidad para ver sus conexiones."
        />
      </div>
    );
  }

  if (isLoading) {
    return (
      <div className="flex flex-1 items-center justify-center">
        <Spinner size="sm" />
      </div>
    );
  }

  if (links.length === 0) {
    return (
      <div className="flex flex-1 items-center px-4">
        <EmptyState
          icon="search"
          message="Sin conexiones registradas."
        />
      </div>
    );
  }

  return (
    <div className="flex-1 overflow-y-auto px-3 py-2">
      <p className="mb-2 text-xs font-medium uppercase tracking-wider text-muted">
        Conexiones ({links.length})
      </p>
      <ul className="space-y-1">
        {links.map((link, i) => {
          const displayName =
            link.target === entityName ? link.source : link.target;
          const encoded = encodePathSegment(displayName);
          const linkUrl = `/wiki/${encodeURIComponent(mundo)}/entity/${encoded}`;

          return (
            <li key={`${link.source}-${link.target}-${link.kind}-${i}`}>
              <Link
                to={linkUrl}
                className="group flex items-center gap-2 rounded px-2 py-1.5 text-small text-primary hover:bg-surface-hover/50 transition-colors"
              >
                <Icon
                  name="file"
                  size={12}
                  className="flex-shrink-0 text-muted group-hover:text-icon-muted"
                />
                <span className="flex-1 truncate">{displayName}</span>
                {link.kind && (
                  <span className="flex-shrink-0 rounded bg-surface-raised px-1.5 py-0.5 text-xs text-muted uppercase">
                    {link.kind}
                  </span>
                )}
              </Link>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
