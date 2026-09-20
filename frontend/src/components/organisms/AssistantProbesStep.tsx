import type { AssistantModelOption, AssistantProbeResult } from "@/api/types";
import { Button } from "@/components/atoms/Button";
import {
  bothProbesPassed,
  type Validation,
} from "@/components/organisms/assistantSettingsShared";

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
  const canRun = !busy && selectedModel !== null && validation === "validated";
  const canSave =
    !busy && selectedModel !== null && bothProbesPassed(textProbe, visionProbe);

  return (
    <section>
      <h4 className="font-heading text-body text-primary">Pruebas</h4>
      <p className="mt-1 text-small text-muted">
        El modelo debe superar la prueba de texto y, si pasa, la prueba causal
        de visión (verifica que realmente ve la imagen, no que la memorizó).
      </p>
      <Button variant="secondary" onClick={onRunProbes} disabled={!canRun}>
        {runningProbe === "text"
          ? "Probando texto…"
          : runningProbe === "vision"
            ? "Probando visión…"
            : "Probar texto + visión"}
      </Button>

      <div className="mt-3 space-y-3">
        <div>
          <p className="text-small text-muted">Prueba de texto</p>
          {textProbe ? (
            <p
              aria-live="polite"
              className={`mt-1 text-small ${probeOutcomeClass(textProbe.outcome)}`}
            >
              {textProbe.outcome === "passed"
                ? "Prueba de texto superada."
                : (textProbe.message ?? "La prueba de texto no pasó.")}
            </p>
          ) : (
            <p className="mt-1 text-small text-muted">Sin ejecutar.</p>
          )}
        </div>

        <div>
          <p className="text-small text-muted">Prueba de visión</p>
          {visionProbe ? (
            <p
              aria-live="polite"
              className={`mt-1 text-small ${probeOutcomeClass(visionProbe.outcome)}`}
            >
              {visionProbe.outcome === "passed"
                ? "Prueba de visión superada."
                : (visionProbe.message ?? "La prueba de visión no pasó.")}
            </p>
          ) : textProbe && textProbe.outcome !== "passed" ? (
            <p aria-live="polite" className="mt-1 text-small text-muted">
              La visión no se ejecutó porque la prueba de texto no pasó.
            </p>
          ) : (
            <p className="mt-1 text-small text-muted">Sin ejecutar.</p>
          )}
        </div>
      </div>

      <Button
        variant="secondary"
        className="mt-4"
        onClick={onSave}
        disabled={!canSave}
      >
        {busy ? "Guardando…" : "Guardar configuración"}
      </Button>
      {error && <p className="mt-2 text-small text-status-error">{error}</p>}
    </section>
  );
}
