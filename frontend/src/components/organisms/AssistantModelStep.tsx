import type { AssistantModelOption } from "@/api/types";
import { Button } from "@/components/atoms/Button";
import {
  inputClass,
  labelClass,
  modelDescription,
} from "@/components/organisms/assistantSettingsShared";
import { useAppLanguage } from "@/hooks/useAppLanguage";

export interface AssistantModelStepProps {
  /** The connection step completed, so discovery is unlocked. */
  validated: boolean;
  /** A validated connection backed by an already-stored key. */
  usingStoredKey: boolean;
  busy: boolean;
  error: string | null;
  models: AssistantModelOption[];
  selectedModel: AssistantModelOption | null;
  manualModelId: string;
  onManualModelIdChange: (value: string) => void;
  onDiscover: () => void;
  onSelectModel: (id: string) => void;
  onUseManualModel: () => void;
}

/**
 * Step 2 — discover the provider catalog and choose a model, with a manual-ID
 * fallback for providers whose discovery endpoint is unavailable.
 */
export function AssistantModelStep({
  validated,
  usingStoredKey,
  busy,
  error,
  models,
  selectedModel,
  manualModelId,
  onManualModelIdChange,
  onDiscover,
  onSelectModel,
  onUseManualModel,
}: AssistantModelStepProps) {
  const { t } = useAppLanguage();
  // The active model is always selectable, even when the server catalog does
  // not list it (the live Zen Go catalog drifts from the bundled one).
  const options =
    selectedModel && selectedModel.id && !models.some((model) => model.id === selectedModel.id)
      ? [selectedModel, ...models]
      : models;

  return (
    <section>
      <h4 className="font-heading text-body text-primary">
        {t("assistantSettings.model")}
      </h4>

      {!validated ? (
        <p className="text-small text-muted">
          {t("assistantSettings.validateToDiscover")}
        </p>
      ) : (
        <>
          {usingStoredKey && (
            <p className="mb-3 text-small text-muted">
              {t("assistantSettings.usingStoredKey")}
            </p>
          )}
          <Button variant="secondary" onClick={onDiscover} disabled={busy}>
            {busy ? t("assistantSettings.discovering") : t("assistantSettings.discover")}
          </Button>
          {error && <p className="mt-2 text-small text-status-error">{error}</p>}

          {options.length > 0 && (
            <select
              aria-label={t("assistantSettings.modelAria")}
              className={`${inputClass} mt-3`}
              value={selectedModel?.id ?? ""}
              onChange={(event) => onSelectModel(event.target.value)}
            >
              {options.map((model) => (
                <option key={model.id} value={model.id}>
                  {model.label}
                </option>
              ))}
            </select>
          )}

          <label
            className={`${labelClass} mt-3`}
            htmlFor="assistant-manual-model"
          >
            {t("assistantSettings.manualModelLabel")}
          </label>
          <input
            id="assistant-manual-model"
            className={inputClass}
            value={manualModelId}
            onChange={(event) => onManualModelIdChange(event.target.value)}
            placeholder="model-id"
          />
          <Button
            className="mt-2"
            variant="secondary"
            onClick={onUseManualModel}
          >
            {t("assistantSettings.useManualModel")}
          </Button>

          {selectedModel && (
            <p className="mt-3 text-small text-muted">
              {modelDescription(selectedModel, t)} ·{" "}
              {selectedModel.pricing
                ? t("assistantSettings.pricingReported")
                : t("assistantSettings.pricingUnavailable")}
            </p>
          )}
        </>
      )}
    </section>
  );
}
