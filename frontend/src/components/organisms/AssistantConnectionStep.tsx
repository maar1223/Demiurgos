import type { RefObject } from "react";
import { Button } from "@/components/atoms/Button";
import { SecretInput } from "@/components/molecules/SecretInput";
import {
  inputClass,
  labelClass,
  providers,
  type Validation,
} from "@/components/organisms/assistantSettingsShared";
import { useAppLanguage } from "@/hooks/useAppLanguage";

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
  const { t } = useAppLanguage();
  return (
    <section>
      <h4 className="font-heading text-body text-primary">
        {t("assistantSettings.connection")}
      </h4>
      <label className={labelClass} htmlFor="assistant-provider">
        {t("assistantSettings.providerLabel")}
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
        {t("assistantSettings.providerHint")}
      </p>

      <label className={`${labelClass} mt-4`} htmlFor="assistant-base-url">
        {t("assistantSettings.endpointLabel")}
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
            {t("assistantSettings.apiKeyLabel")}
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
                ? t("assistantSettings.apiKeyPlaceholderConfigured")
                : t("assistantSettings.apiKeyPlaceholder")
            }
          />
          {keyConfigured && (
            <p className="mt-1 text-small text-muted">
              {t("assistantSettings.apiKeyStoredHint")}
            </p>
          )}
        </>
      )}

      <div className="mt-3 flex flex-wrap gap-2">
        <Button variant="secondary" onClick={onValidate} disabled={busy}>
          {busy ? t("assistantSettings.validating") : t("assistantSettings.validate")}
        </Button>
        {keyConfigured && (
          <Button variant="secondary" onClick={onClearKey} disabled={busy}>
            {t("assistantSettings.clearKey")}
          </Button>
        )}
      </div>

      {validation === "validated" && (
        <p className="mt-2 text-small text-status-success">
          {t("assistantSettings.validated")}
        </p>
      )}
      {error && <p className="mt-2 text-small text-status-error">{error}</p>}
    </section>
  );
}
