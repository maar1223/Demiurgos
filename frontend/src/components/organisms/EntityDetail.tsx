import { useNavigate } from "react-router-dom";
import { useEntity } from "@/hooks/useEntity";
import { MarkdownViewer } from "@/components/organisms/MarkdownViewer";
import { ErrorBanner } from "@/components/organisms/ErrorBanner";
import { Spinner } from "@/components/atoms/Spinner";
import { Button } from "@/components/atoms/Button";
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
    // Extract section prefix from entityName (e.g. "personajes/Kaelen" → "personajes")
    // Default to "personajes" if no slash present.
    const slashIdx = entityName.indexOf("/");
    const section = slashIdx >= 0 ? entityName.slice(0, slashIdx) : "personajes";
    const slug = slashIdx >= 0 ? entityName.slice(slashIdx + 1) : entityName;
    const editorPath = `/wiki/${mundo}/${section}/${slug}`;

    return (
      <div className="flex flex-col items-center justify-center gap-4 py-16 text-center">
        <div className="flex h-16 w-16 items-center justify-center rounded-full bg-surface-raised text-icon-muted/50">
          <Icon name="search" size={32} />
        </div>
        <div>
          <p className="text-body text-muted">Entidad no encontrada</p>
          <p className="mt-1 text-small text-muted">&ldquo;{entityName}&rdquo;</p>
        </div>
        <Button
          variant="secondary"
          size="sm"
          onClick={() => navigate(editorPath)}
        >
          Crear entidad
        </Button>
      </div>
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
            <h1 className="font-heading text-h2 text-primary">
              {entity.name}
            </h1>
            <span className="inline-flex items-center rounded-full bg-action/10 px-3 py-0.5 text-xs font-medium text-action">
              {capitalize(entity.type)}
            </span>
          </div>

          {/* Metadata bar */}
          <div className="flex flex-wrap gap-4 text-small text-muted">
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
        <hr className="mb-6 border-edge" />

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
