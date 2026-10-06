import { Badge } from "@/components/atoms/Badge";
import { Button } from "@/components/atoms/Button";
import type { TriggerApproval } from "@/api/types";
import { useAppLanguage } from "@/hooks/useAppLanguage";
import {
  TRIGGER_INTAKE_LIMIT,
  TRIGGER_RENDER_LIMIT,
  boundTrigger,
  isTriggerApproved,
  normalizeTrigger,
} from "@/lib/triggerBound";

/**
 * TriggerApprovalBlock — the visible, editable, explicitly approvable trigger
 * (Etapa 2, D3/D6). One shared surface mounted by every publish path.
 *
 * Presentation rules:
 * - The trigger is editable with a ≤60 authored-bound counter and a ≤57 live
 *   preview carrying a VISIBLE truncation marker.
 * - The approval state is a badge: "Aprobado" / "Pendiente de aprobación".
 * - Exactly ONE approve action is rendered (one question per turn, D6); the
 *   block never batches the trigger with other review questions.
 * - Approve is disabled while the trigger is empty or over the authored bound.
 * - The client mirrors the server bound for UX only; the server stays
 *   authoritative (an over-bound submit is refused with `trigger_invalid`).
 *
 * Edit-after-approve (D7): the badge derives its state from whether the
 * recorded approval still matches the current (normalized) value, so any real
 * edit reverts the surface to "Pendiente de aprobación" and re-gates publish.
 */
export interface TriggerApprovalBlockProps {
  /** Current trigger text (controlled). */
  value: string;
  onChange: (value: string) => void;
  /** Server-recorded approval for this draft/skill, or null when unapproved. */
  approval: TriggerApproval | null | undefined;
  /** The Author's explicit approval action — the single question of the block. */
  onApprove: (description: string) => void | Promise<unknown>;
  /** Disables the whole surface (e.g. a request is in flight). */
  disabled?: boolean;
  /** Gates only the approve action (e.g. the form is not yet complete). */
  approveDisabled?: boolean;
  /** Only the approve action is in flight (spinner/label level). */
  busy?: boolean;
  /** Localized error to surface under the approve action. */
  error?: string | null;
  className?: string;
}

export function TriggerApprovalBlock({
  value,
  onChange,
  approval,
  onApprove,
  disabled = false,
  approveDisabled = false,
  busy = false,
  error = null,
  className,
}: TriggerApprovalBlockProps) {
  const { t } = useAppLanguage();
  const count = normalizeTrigger(value).length;
  const overBound = count > TRIGGER_INTAKE_LIMIT;
  const empty = count === 0;
  const approved = isTriggerApproved(approval, value);
  const preview = boundTrigger(value);
  const canApprove =
    !empty && !overBound && !disabled && !approveDisabled && !busy;

  return (
    <section
      aria-label={t("triggerApproval.aria")}
      data-testid="trigger-approval-block"
      className={`rounded-lg border border-edge bg-surface p-4 ${className ?? ""}`}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-sm font-medium text-primary">
          {t("triggerApproval.title")}
        </h3>
        <span data-testid="trigger-approval-badge">
          <Badge variant={approved ? "success" : "warning"}>
            {approved
              ? t("triggerApproval.badgeApproved")
              : t("triggerApproval.badgePending")}
          </Badge>
        </span>
      </div>
      <p className="mt-1 text-xs text-muted">{t("triggerApproval.help")}</p>

      <label className="mt-3 flex flex-col gap-1 text-small text-muted">
        {t("triggerApproval.label")}
        <input
          aria-label={t("triggerApproval.inputAria")}
          className="rounded-lg bg-surface px-3 py-2 text-body text-primary outline-none focus:ring-2 focus:ring-action/50 disabled:opacity-50"
          value={value}
          onChange={(event) => onChange(event.target.value)}
          disabled={disabled}
        />
      </label>

      <div className="mt-1 flex flex-wrap items-center justify-between gap-2 text-xs">
        <span className="text-muted" data-testid="trigger-approval-counter">
          {t("triggerApproval.counter", {
            count,
            limit: TRIGGER_INTAKE_LIMIT,
          })}
        </span>
        {overBound && (
          <span
            className="text-status-error"
            data-testid="trigger-approval-over"
          >
            {t("triggerApproval.overBound", { limit: TRIGGER_INTAKE_LIMIT })}
          </span>
        )}
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-2 text-xs">
        <span className="text-muted">
          {t("triggerApproval.previewLabel")}
        </span>
        <code
          className="rounded bg-surface-raised px-2 py-0.5 font-mono text-primary"
          data-testid="trigger-approval-preview"
        >
          {preview.value}
        </code>
        {preview.truncated && (
          <span
            className="text-action"
            data-testid="trigger-approval-truncated"
          >
            {t("triggerApproval.truncated", { limit: TRIGGER_RENDER_LIMIT })}
          </span>
        )}
      </div>

      {/* Exactly ONE approve affordance (D6): the trigger is the only question
          this surface presents; it is never batched with other questions. */}
      <div className="mt-3">
        <Button
          type="button"
          size="sm"
          data-testid="trigger-approve"
          disabled={!canApprove}
          onClick={() => void onApprove(value)}
        >
          {approved
            ? t("triggerApproval.reapprove")
            : t("triggerApproval.approve")}
        </Button>
      </div>

      {error && (
        <p
          role="alert"
          className="mt-3 rounded-md border border-status-error/30 bg-status-error/10 px-3 py-2 text-xs text-status-error"
        >
          {error}
        </p>
      )}
    </section>
  );
}

export default TriggerApprovalBlock;
