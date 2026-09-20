import type { RefObject } from "react";
import { Button } from "@/components/atoms/Button";
import { SecretInput } from "@/components/molecules/SecretInput";
import {
  inputClass,
  labelClass,
  providers,
  type Validation,
} from "@/components/organisms/assistantSettingsShared";

export interface AssistantConnectionStepProps {
  provider: string;
  baseUrl: string;
  localProvider: boolean;
  keyConfigured: boolean;
  validation: Validation;
  busy: boolean;
  error: string | null;
  /** Owned by the panel so the transient key survives this step unmounting. */
  apiKeyInputRef: RefObject<HTMLInputElement>;
  onProviderChange: (provider: string) => void;
  onBaseUrlChange: (value: string) => void;
  onApiKeyChange: (value: string) => void;
  onValidate: () => void;
  onClearKey: () => void;
}

/**
 * Step 1 — one connection act: choose the provider, point the endpoint, paste
 * the transient key and validate. The provider and endpoint live together
 * because changing either invalidates the validation and both probes.
 */
export function AssistantConnectionStep({
  provider,
  baseUrl,
  localProvider,
  keyConfigured,
  validation,
  busy,
  error,
  apiKeyInputRef,
  onProviderChange,
  onBaseUrlChange,
  onApiKeyChange,
  onValidate,
  onClearKey,
}: AssistantConnectionStepProps) {
  return (
    <section>
      <h4 className="font-heading text-body text-primary">Conexión</h4>
      <label className={labelClass} htmlFor="assistant-provider">
        Elegí un proveedor
      </label>
      <select
        id="assistant-provider"
        className={inputClass}
        value={provider}
        onChange={(event) => onProviderChange(event.target.value)}
      >
        {providers.map(([id, label]) => (
          <option key={id} value={id}>
            {label}
          </option>
        ))}
      </select>
      <p className="mt-2 text-small text-muted">
        OpenCode Go es la opción recomendada. Ollama y LM Studio son locales y
        no requieren clave. Los endpoints compatibles requieren una URL propia.
      </p>

      <label className={`${labelClass} mt-4`} htmlFor="assistant-base-url">
        Endpoint
      </label>
      <input
        id="assistant-base-url"
        className={inputClass}
        value={baseUrl}
        onChange={(event) => onBaseUrlChange(event.target.value)}
        placeholder="https://..."
      />

      {!localProvider && (
        <>
          <label className={`${labelClass} mt-3`} htmlFor="assistant-api-key">
            Clave API
          </label>
          <SecretInput
            ref={apiKeyInputRef}
            copyable
            id="assistant-api-key"
            autoComplete="new-password"
            className={inputClass}
            onChange={(event) => onApiKeyChange(event.target.value)}
            placeholder={
              keyConfigured
                ? "Clave ya configurada — dejá vacío para usar la almacenada"
                : "Ingresá tu clave"
            }
          />
          {keyConfigured && (
            <p className="mt-1 text-small text-muted">
              Ya hay una clave guardada para este proveedor. Podés cambiar de
              modelo sin reescribirla.
            </p>
          )}
        </>
      )}

      <div className="mt-3 flex flex-wrap gap-2">
        <Button variant="secondary" onClick={onValidate} disabled={busy}>
          {busy ? "Validando…" : "Validar conexión"}
        </Button>
        {keyConfigured && (
          <Button variant="secondary" onClick={onClearKey} disabled={busy}>
            Eliminar clave
          </Button>
        )}
      </div>

      {validation === "validated" && (
        <p className="mt-2 text-small text-status-success">Conexión validada.</p>
      )}
      {error && <p className="mt-2 text-small text-status-error">{error}</p>}
    </section>
  );
}
