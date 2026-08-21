import { Badge } from "@/components/atoms/Badge";
import { Button } from "@/components/atoms/Button";
import { Icon } from "@/components/atoms/Icon";
import { cn } from "@/lib/utils";
import type { VisionSuggestion } from "@/api/types";

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

/**
 * PR4 — one advisory vision suggestion card.
 *
 * Vision suggestions approve/reject the IMAGE: approved originals are
 * registered in the gallery at execute and the description becomes the
 * markdown alt-text. Review-time images live in the spool (pre-gallery),
 * so the card shows a placeholder — never a broken `<img>`. Uses the same
 * decisions endpoint + ID commitment as the text suggestion family.
 */
export function VisionSuggestionCard({
  candidateId,
  suggestion,
  decision,
  busy,
  onDecision,
}: VisionSuggestionCardProps) {
  const provider = suggestion.provenance?.provider ?? "vision";

  return (
    <li
      className={cn(
        "flex flex-col gap-2 rounded-md border p-3",
        "border-plata/40 bg-plata/5",
        decision === "approved" && "ring-1 ring-musgo/40",
        decision === "rejected" && "opacity-70",
      )}
      data-testid={`suggestion-${suggestion.id}`}
      data-suggestion-state={decision ?? "pending"}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant="info">visión</Badge>
          <span className="text-small font-medium text-pergamino">
            {suggestion.verdict}
          </span>
          {suggestion.tags.length > 0 && (
            <span className="flex flex-wrap gap-1">
              {suggestion.tags.map((tag) => (
                <Badge key={tag} variant="default">
                  #{tag}
                </Badge>
              ))}
            </span>
          )}
        </div>
        <span className="text-xs text-tinta-desvaida">
          Origen: {provider}
        </span>
      </div>

      {/* Review-time images live in the spool (pre-gallery) — a placeholder,
          never a broken <img>. */}
      <div
        className="flex items-center gap-2 rounded-md border border-dashed border-filio bg-madero/40 px-3 py-2 text-xs text-tinta-desvaida"
        role="img"
        aria-label="Imagen sin vista previa disponible"
      >
        <Icon name="image" size={16} />
        {suggestion.relative_media_path}
      </div>

      {suggestion.description && (
        <p className="text-small text-pergamino">{suggestion.description}</p>
      )}
      {suggestion.analysis && (
        <p className="text-xs text-tinta-desvaida">{suggestion.analysis}</p>
      )}

      <div className="flex justify-end gap-2">
        <Button
          variant={decision === "approved" ? "primary" : "secondary"}
          size="sm"
          disabled={busy || decision === "approved"}
          onClick={() => onDecision(candidateId, suggestion.id, "approve")}
          aria-label={`Aprobar sugerencia ${suggestion.id}`}
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
          aria-label={`Rechazar sugerencia ${suggestion.id}`}
          data-testid={`suggestion-reject-${suggestion.id}`}
        >
          <Icon name="close" size={14} />
          Rechazar
        </Button>
      </div>
      {decision === "rejected" && (
        <p className="text-xs text-tinta-desvaida">
          Sugerencia rechazada — no se aplicará al importar.
        </p>
      )}
    </li>
  );
}