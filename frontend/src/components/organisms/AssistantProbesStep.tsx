import type { AssistantModelOption, AssistantProbeResult } from "@/api/types";
import { Button } from "@/components/atoms/Button";
import {
  bothProbesPassed,
  type Validation,
} from "@/components/organisms/assistantSettingsShared";
import { useAppLanguage } from "@/hooks/useAppLanguage";

/** Which probe is in flight, so the combined button can label itself honestly. */
export type RunningProbe = "text" | "vision" | null;

export interface AssistantProbesStepProps {
  selectedModel: AssistantModelOption | null;
  validation: Validation;
  textProbe: AssistantProbeResult | null;
  visionProbe: AssistantProbeResult | null;
  runningProbe: RunningProbe;
  busy: boolean;
  error: string | null;
  onRunProbes: () => void;
  onSave: () => void;
}

function probeOutcomeClass(outcome: AssistantProbeResult["outcome"]): string {
  return outcome === "passed" ? "text-status-success" : "text-status-error";
}

/**
 * Step 3 — run the text probe and, only when it passed, the causal vision
 * probe; then persist. Both results stay visible together.
 */
export function AssistantProbesStep({
  selectedModel,
  validation,
  textProbe,
  visionProbe,
  runningProbe,
  busy,
  error,
  onRunProbes,
  onSave,
}: AssistantProbesStepProps) {
  const { t } = useAppLanguage();
  const canRun = !busy && selectedModel !== null && validation === "validated";
  const canSave =
    !busy && selectedModel !== null && bothProbesPassed(textProbe, visionProbe);

  return (
    <section>
      <h4 className="font-heading text-body text-primary">
        {t("assistantSettings.probes")}
      </h4>
      <p className="mt-1 text-small text-muted">
        {t("assistantSettings.probesHint")}
      </p>
      <Button variant="secondary" onClick={onRunProbes} disabled={!canRun}>
        {runningProbe === "text"
          ? t("assistantSettings.probingText")
          : runningProbe === "vision"
            ? t("assistantSettings.probingVision")
            : t("assistantSettings.runProbes")}
      </Button>

      <div className="mt-3 space-y-3">
        <div>
          <p className="text-small text-muted">{t("assistantSettings.textProbe")}</p>
          {textProbe ? (
            <p
              aria-live="polite"
              className={`mt-1 text-small ${probeOutcomeClass(textProbe.outcome)}`}
            >
              {textProbe.outcome === "passed"
                ? t("assistantSettings.textProbePassed")
                : (textProbe.message ?? t("assistantSettings.textProbeFailed"))}
            </p>
          ) : (
            <p className="mt-1 text-small text-muted">
              {t("assistantSettings.notRun")}
            </p>
          )}
        </div>

        <div>
          <p className="text-small text-muted">{t("assistantSettings.visionProbe")}</p>
          {visionProbe ? (
            <p
              aria-live="polite"
              className={`mt-1 text-small ${probeOutcomeClass(visionProbe.outcome)}`}
            >
              {visionProbe.outcome === "passed"
                ? t("assistantSettings.visionProbePassed")
                : (visionProbe.message ?? t("assistantSettings.visionProbeFailed"))}
            </p>
          ) : textProbe && textProbe.outcome !== "passed" ? (
            <p aria-live="polite" className="mt-1 text-small text-muted">
              {t("assistantSettings.visionSkipped")}
            </p>
          ) : (
            <p className="mt-1 text-small text-muted">
              {t("assistantSettings.notRun")}
            </p>
          )}
        </div>
      </div>

      <Button
        variant="secondary"
        className="mt-4"
        onClick={onSave}
        disabled={!canSave}
      >
        {busy ? t("assistantSettings.saving") : t("assistantSettings.saveConfig")}
      </Button>
      {error && <p className="mt-2 text-small text-status-error">{error}</p>}
    </section>
  );
}
