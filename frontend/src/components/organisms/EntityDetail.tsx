import { useNavigate } from "react-router-dom";
import { useEntity } from "@/hooks/useEntity";
import { MarkdownViewer } from "@/components/organisms/MarkdownViewer";
import { EmptyState } from "@/components/organisms/EmptyState";
import { ErrorBanner } from "@/components/organisms/ErrorBanner";
import { Spinner } from "@/components/atoms/Spinner";
import { Icon } from "@/components/atoms/Icon";

interface EntityDetailProps {
  /** Current world name */
  mundo: string;
  /** Raw entity name from the URL path (e.g. "Kaelen" or "personajes/Kaelen") */
  entityName: string;
}

/**
 * Content-first entity detail view.
 *
 * Fetches entity data via `useEntity` and renders:
 * - Header with entity name + type badge
 * - Metadata bar (type label, link count)
 * - Entity body via `MarkdownViewer` (with wikilink support)
 *
 * States:
 * - 🟡 Loading: Spinner
 * - 🔴 Error (non-404): ErrorBanner with retry
 * - 🔴 Not found (404): EmptyState with "Crear entidad" button
 * - 🟢 Ready: header + metadata + prose content
 */
export function EntityDetail({ mundo, entityName }: EntityDetailProps) {
  const navigate = useNavigate();
  const { entity, isLoading, error, mutate } = useEntity(mundo, entityName);

  // --- Loading ---
  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-24">
        <Spinner size="lg" />
      </div>
    );
  }

  // --- Error (generic) ---
  if (error && !isNotFoundError(error)) {
    return (
      <div className="px-4 py-8">
        <ErrorBanner
          message={error.message || "Error al cargar la entidad."}
          onRetry={() => mutate()}
        />
      </div>
    );
  }

  // --- Not found (404) ---
  if (error && isNotFoundError(error)) {
    return (
      <EmptyState
        icon="search"
        message={`Entidad "${entityName}" no encontrada.`}
        actionLabel="Volver al inicio"
        onAction={() => navigate("/wiki")}
      />
    );
  }

  // --- Ready (entity loaded) ---
  if (entity) {
    const totalLinks =
      entity.forward_links.length +
      entity.backlinks.length +
      entity.relaciones.length;

    return (
      <div>
        {/* Header: name + type badge */}
        <div className="mb-6">
          <div className="mb-1 flex flex-wrap items-baseline gap-3">
            <h1 className="font-heading text-h2 text-pergamino">
              {entity.name}
            </h1>
            <span className="inline-flex items-center rounded-full bg-llamita/10 px-3 py-0.5 text-xs font-medium text-llamita">
              {capitalize(entity.type)}
            </span>
          </div>

          {/* Metadata bar */}
          <div className="flex flex-wrap gap-4 text-small text-tinta-desvaida">
            <span className="inline-flex items-center gap-1">
              <Icon name="file" size={14} />
              {capitalize(entity.type)}
            </span>
            <span className="inline-flex items-center gap-1">
              <Icon name="file" size={14} />
              {totalLinks} {totalLinks === 1 ? "conexión" : "conexiones"}
            </span>
            {entity.forward_links.length > 0 && (
              <span className="inline-flex items-center gap-1">
                <Icon name="chevron-right" size={14} />
                {entity.forward_links.length} referencias
              </span>
            )}
            {entity.backlinks.length > 0 && (
              <span className="inline-flex items-center gap-1">
                <Icon name="chevron-left" size={14} />
                {entity.backlinks.length} menciones
              </span>
            )}
          </div>
        </div>

        {/* Divider */}
        <hr className="mb-6 border-filio" />

        {/* Entity body content */}
        <MarkdownViewer content={entity.content} mundo={mundo} />
      </div>
    );
  }

  // Fallback (shouldn't reach here)
  return null;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Detects 404 from ApiError or generic fetch Error. */
function isNotFoundError(error: Error): boolean {
  if ("status" in error && (error as { status: number }).status === 404) {
    return true;
  }
  if (error.message?.includes("404") || error.message?.includes("not found")) {
    return true;
  }
  return false;
}

/** Capitalises the first letter of a string. */
function capitalize(s: string): string {
  if (!s) return s;
  return s.charAt(0).toUpperCase() + s.slice(1);
}
