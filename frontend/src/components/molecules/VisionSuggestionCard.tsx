import { Badge } from "@/components/atoms/Badge";
import { Button } from "@/components/atoms/Button";
import { Icon } from "@/components/atoms/Icon";
import { cn } from "@/lib/utils";
import type { VisionSuggestion, VisionVerdict } from "@/api/types";

/**
 * Vision analysis card for one extracted image (sync-lore-in-importer, PR3+).
 *
 * Vision suggestions are ADVISORY: the verdict/description/analysis never
 * gate writes — only the reviewer's explicit approve/reject does, via the
 * same decisions endpoint as text suggestions. The approved description
 * becomes the markdown alt-text at execute time; the ORIGINAL spool bytes
 * are registered in the gallery (thumbnails are preview-only).
 *
 * Visual distinction: ``border-icon-muted/40 bg-surface`` keeps vision cards
 * apart from classification (status-success) and relationship (edge)
 * suggestions. The
 * thumbnail only renders when the server provides a servable
 * ``thumbnail_url`` — review-time images live in the job spool, which the
 * media endpoint does not serve, so a broken image is never rendered.
 */

const VERDICT_LABELS: Record<VisionVerdict, string> = {
  confirma: "confirma",
  rechaza: "rechaza",
  contradice: "contradice",
  no_aplica: "no aplica",
};

const VERDICT_VARIANTS: Record<
  VisionVerdict,
  "success" | "error" | "default"
> = {
  confirma: "success",
  rechaza: "error",
  contradice: "error",
  no_aplica: "default",
};

interface VisionSuggestionCardProps {
  candidateId: string;
  suggestion: VisionSuggestion;
  decision: "approved" | "rejected" | null;
  busy: boolean;
  onDecision: (
    candidateId: string,
    suggestionId: string,
    decision: "approve" | "reject",
  ) => void;
}

export function VisionSuggestionCard({
  candidateId,
  suggestion,
  decision,
  busy,
  onDecision,
}: VisionSuggestionCardProps) {
  const providerLabel = suggestion.provenance?.provider ?? "visión";
  const modelLabel = suggestion.provenance?.model ?? "";
  const confidencePct = Math.round((suggestion.confidence ?? 0) * 100);

  return (
    <li
      className={cn(
        "flex flex-col gap-2 rounded-md border border-icon-muted/40 bg-surface p-3",
        decision === "approved" && "ring-1 ring-status-success/40",
        decision === "rejected" && "opacity-70",
      )}
      data-testid={`suggestion-${suggestion.id}`}
      data-suggestion-state={decision ?? "pending"}
    >
      <div className="flex items-start gap-3">
        {/* Thumbnail: only when the server provides a servable preview URL.
            Review-time images live in the job spool (pre-gallery), so the
            fallback is an honest placeholder instead of a broken image. */}
        {suggestion.thumbnail_url ? (
          <div className="shrink-0 overflow-hidden rounded-md border border-edge bg-surface-raised">
            <img
              src={suggestion.thumbnail_url}
              alt={suggestion.description || suggestion.relative_media_path}
              className="h-20 w-20 object-cover"
            />
          </div>
        ) : (
          <div
            className="flex h-20 w-20 shrink-0 flex-col items-center justify-center gap-1 rounded-md border border-edge bg-surface-raised text-muted"
            aria-label="Imagen sin vista previa disponible"
          >
            <Icon name="image" size={20} />
            <span className="px-1 text-center text-[10px] leading-tight">
              spool
            </span>
          </div>
        )}

        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant={VERDICT_VARIANTS[suggestion.verdict]}>
              {VERDICT_LABELS[suggestion.verdict]}
            </Badge>
            <Badge variant="info">visión</Badge>
            <span
              className="truncate text-xs text-muted"
              title={suggestion.relative_media_path}
            >
              {suggestion.relative_media_path}
            </span>
            <span
              className="text-xs text-muted"
              title="confianza del asistente"
            >
              confianza {confidencePct}%
            </span>
          </div>
          <p className="mt-1 text-small font-medium text-primary">
            {suggestion.description || "(sin descripción)"}
          </p>
          {suggestion.analysis && (
            <p className="mt-0.5 text-xs text-muted">
              {suggestion.analysis}
            </p>
          )}
          {suggestion.tags.length > 0 && (
            <div className="mt-1 flex flex-wrap gap-1">
              {suggestion.tags.map((tag) => (
                <Badge key={tag} variant="default">
                  #{tag}
                </Badge>
              ))}
            </div>
          )}
        </div>
      </div>

      {suggestion.evidence && (
        <p className="text-xs text-muted">{suggestion.evidence}</p>
      )}

      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="text-xs text-muted">
          Origen: {providerLabel}
          {modelLabel && ` · ${modelLabel}`}
        </span>
        <div className="flex gap-2">
          <Button
            variant={decision === "approved" ? "primary" : "secondary"}
            size="sm"
            disabled={busy || decision === "approved"}
            onClick={() => onDecision(candidateId, suggestion.id, "approve")}
            aria-label={`Aprobar imagen ${suggestion.id}`}
            data-testid={`suggestion-approve-${suggestion.id}`}
          >
            <Icon name="check" size={14} />
            Aprobar
          </Button>
          <Button
            variant={decision === "rejected" ? "primary" : "ghost"}
            size="sm"
            disabled={busy || decision === "rejected"}
            onClick={() => onDecision(candidateId, suggestion.id, "reject")}
            aria-label={`Rechazar imagen ${suggestion.id}`}
            data-testid={`suggestion-reject-${suggestion.id}`}
          >
            <Icon name="close" size={14} />
            Rechazar
          </Button>
        </div>
      </div>
      {decision === "approved" && (
        <p className="text-xs text-muted">
          Imagen aprobada — la descripción se usará como texto alternativo al
          importar.
        </p>
      )}
      {decision === "rejected" && (
        <p className="text-xs text-muted">
          Imagen rechazada — no se registrará en la galería.
        </p>
      )}
    </li>
  );
}

VisionSuggestionCard.displayName = "VisionSuggestionCard";