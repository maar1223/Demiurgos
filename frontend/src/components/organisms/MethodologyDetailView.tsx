import { useEffect, useState } from "react";
import { getPublishedDetail } from "@/api/coCreation";
import { ApiError } from "@/api/types";
import type {
  MethodologyAdjunto,
  PublishedMethodologyDetail,
} from "@/api/types";
import { Badge } from "@/components/atoms/Badge";
import { Spinner } from "@/components/atoms/Spinner";
import { AdjuntoViewerModal } from "@/components/organisms/AdjuntoViewerModal";
import { EmptyState } from "@/components/organisms/EmptyState";
import { ErrorBanner } from "@/components/organisms/ErrorBanner";
import { MarkdownViewer } from "@/components/organisms/MarkdownViewer";

interface MethodologySelection {
  skill_id: string;
  version: string;
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

interface MethodologyDetailViewProps {
  /** Page-level selection (REQ-SB-5). Null renders the empty state. */
  selected: MethodologySelection | null;
}

/**
 * Shared read-only center body for the "Taller" EditorLayout (SC-SB-3).
 *
 * Renders a metadata header card, an optional attachments block (R23), and
 * the published `source` via `MarkdownViewer`, all from
 * `getPublishedDetail(skillId, version)`. Each attachment row is actionable
 * and opens the read-only `AdjuntoViewerModal` for that pinned exemplar. The
 * detail route is auth-required (it exposes the author `source`), so a 401
 * degrades gracefully to a metadata-only card — no source section, no error
 * (SC-SB-3.2). Any other failure shows an error banner with retry. Both
 * lenses render the same body; the only per-lens difference lives in the
 * right `MethodologyStatePanel`.
 */
export function MethodologyDetailView({
  selected,
}: MethodologyDetailViewProps) {
  const [detail, setDetail] = useState<PublishedMethodologyDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [unauthorized, setUnauthorized] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  /** The exemplar currently open in the viewer; `null` keeps it closed. */
  const [selectedAdjunto, setSelectedAdjunto] = useState<MethodologyAdjunto | null>(
    null,
  );

  useEffect(() => {
    // A new page selection invalidates any open viewer (spec: Selection
    // change): the modal belongs to the skill/version it was opened from.
    setSelectedAdjunto(null);

    if (!selected) {
      setDetail(null);
      setLoading(false);
      setUnauthorized(false);
      setError(null);
      return;
    }

    let cancelled = false;
    setLoading(true);
    setUnauthorized(false);
    setError(null);

    getPublishedDetail(selected.skill_id, selected.version)
      .then((nextDetail) => {
        if (cancelled) return;
        setDetail(nextDetail);
        setLoading(false);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setDetail(null);
        setLoading(false);
        if (err instanceof ApiError && err.status === 401) {
          setUnauthorized(true);
        } else {
          setError("No se pudo cargar el detalle de la metodología.");
        }
      });

    return () => {
      cancelled = true;
    };
  }, [selected?.skill_id, selected?.version, reloadKey]);

  if (!selected) {
    return (
      <EmptyState
        icon="empty"
        message="Seleccioná una metodología en el explorador para ver su detalle."
      />
    );
  }

  if (loading) {
    return (
      <div className="flex justify-center py-16">
        <Spinner size="lg" />
      </div>
    );
  }

  // 401 fallback: metadata-only card — identity + muted note, no error
  // styling and no source section (SC-SB-3.2).
  if (unauthorized) {
    return (
      <section
        aria-label="Detalle de metodología"
        className="space-y-6"
      >
        <div className="rounded-lg border border-edge bg-surface-raised p-4">
          <p className="font-heading text-h4 text-primary">
            {selected.skill_id}
          </p>
          <p className="mt-1 text-small text-muted">
            {selected.skill_id}@{selected.version}
          </p>
          <p className="mt-3 text-small text-muted">
            No se pudo cargar el contenido publicado (requiere autenticación).
          </p>
        </div>
      </section>
    );
  }

  if (error) {
    return (
      <ErrorBanner
        message={error}
        onRetry={() => setReloadKey((key) => key + 1)}
      />
    );
  }

  if (!detail) {
    return null;
  }

  const etiquetas = detail.etiquetas ?? [];
  const adjuntos = detail.adjuntos ?? [];

  return (
    <section aria-label="Detalle de metodología" className="space-y-6">
      <header className="rounded-lg border border-edge bg-surface-raised p-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <h2 className="font-heading text-h4 text-primary">{detail.name}</h2>
            <p className="mt-1 text-small text-muted">
              {detail.skill_id}@{detail.version}
            </p>
          </div>
          {etiquetas.length > 0 && (
            <div className="flex flex-wrap gap-1.5">
              {etiquetas.map((tag) => (
                <Badge key={tag} variant="info">
                  {tag}
                </Badge>
              ))}
            </div>
          )}
        </div>
        {detail.description && (
          <p className="mt-3 text-body text-muted">{detail.description}</p>
        )}
      </header>

      {adjuntos.length > 0 && (
        <section
          aria-label="Adjuntos"
          className="rounded-lg border border-edge bg-surface-raised p-4"
        >
          <h3 className="font-heading text-h4 text-primary">Adjuntos</h3>
          {/* Metadata only here (path + nivel + bytes); activating a row opens
              the viewer, which fetches and renders the carrier's markdown. */}
          <ul className="mt-3 space-y-2">
            {adjuntos.map((adjunto) => (
              <li key={adjunto.path}>
                <button
                  type="button"
                  onClick={() => setSelectedAdjunto(adjunto)}
                  aria-haspopup="dialog"
                  className="flex w-full flex-wrap items-baseline justify-between gap-2 rounded-md px-2 py-1 text-left transition-colors hover:bg-surface-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-action/50"
                >
                  <span className="min-w-0 break-all text-small text-primary">
                    {adjunto.path}
                  </span>
                  <span className="flex shrink-0 items-center gap-1.5">
                    <Badge variant="info">{adjunto.nivel}</Badge>
                    <span className="text-small text-muted">
                      {formatBytes(adjunto.bytes)}
                    </span>
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}

      <MarkdownViewer content={detail.source} />

      <AdjuntoViewerModal
        open={selectedAdjunto !== null}
        skillId={selected.skill_id}
        version={selected.version}
        adjunto={selectedAdjunto}
        onClose={() => setSelectedAdjunto(null)}
      />
    </section>
  );
}

export default MethodologyDetailView;