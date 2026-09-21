import type { AssistantModelOption, AssistantSettingsStatus } from "@/api/types";
import { Button } from "@/components/atoms/Button";
import {
  stateContext,
  stateLabel,
} from "@/components/organisms/assistantSettingsShared";

export interface AssistantConfigurationSavedProps {
  status: AssistantSettingsStatus;
  provider: string;
  selectedModel: AssistantModelOption | null;
  onChangeConfiguration: () => void;
  onChangeModel: () => void;
  onNavigateWorkshop: () => void;
}

/**
 * Confirmation block rendered INSIDE the third step. The wizard and its
 * progress indicator stay mounted, so the sequence the user completed remains
 * visible instead of being replaced by a success card.
 */
export function AssistantConfigurationSaved({
  status,
  provider,
  selectedModel,
  onChangeConfiguration,
  onChangeModel,
  onNavigateWorkshop,
}: AssistantConfigurationSavedProps) {
  return (
    <div
      className="rounded-lg border border-status-success/30 bg-status-success/10 p-4"
      role="status"
      aria-live="polite"
    >
      <h4 className="font-heading text-body text-primary">
        Configuración guardada
      </h4>
      <p className="mt-1 text-small text-muted">
        La configuración se guardó correctamente en el servidor.
      </p>
      <dl className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-2">
        <div>
          <dt className="text-small text-muted">Proveedor</dt>
          <dd className="text-small text-primary">{provider}</dd>
        </div>
        <div>
          <dt className="text-small text-muted">Modelo</dt>
          <dd className="text-small text-primary">
            {selectedModel?.label ?? status.model}
          </dd>
        </div>
        <div>
          <dt className="text-small text-muted">Capacidad</dt>
          <dd className="text-small text-primary">
            Texto: superada · Visión: superada
          </dd>
        </div>
        <div>
          <dt className="text-small text-muted">Estado runtime</dt>
          <dd className="text-small text-primary">
            <strong>{stateLabel(status.runtime_state)}</strong>
            <span className="block text-small text-muted">
              {stateContext(status.runtime_state)}
            </span>
          </dd>
        </div>
      </dl>
      <div className="mt-4 flex flex-wrap gap-2">
        <Button variant="primary" onClick={onChangeModel}>
          Cambiar modelo
        </Button>
        <Button variant="secondary" onClick={onChangeConfiguration}>
          Cambiar configuración
        </Button>
        <Button variant="secondary" onClick={onNavigateWorkshop}>
          Volver al Taller de Mundos
        </Button>
      </div>
    </div>
  );
}
