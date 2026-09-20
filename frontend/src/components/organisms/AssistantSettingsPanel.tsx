import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  clearAssistantKey,
  discoverAssistantModels,
  getAssistantSettings,
  runAssistantTextProbe,
  runAssistantVisionProbe,
  saveAssistantConfiguration,
  validateAssistantConnection,
} from "@/api/assistantSettings";
import type {
  AssistantModelOption,
  AssistantProbeResult,
  AssistantSettingsStatus,
} from "@/api/types";
import { Button } from "@/components/atoms/Button";
import { Spinner } from "@/components/atoms/Spinner";
import type { ConnectionStatusSummary } from "@/components/molecules/ConnectionsPanel";
import {
  WizardProgress,
  type WizardStepState,
} from "@/components/molecules/WizardProgress";
import type { AuthSessionController } from "@/components/organisms/IdeaCapturePanel";
import { AssistantConfigurationSaved } from "@/components/organisms/AssistantConfigurationSaved";
import { AssistantConnectionStep } from "@/components/organisms/AssistantConnectionStep";
import { AssistantModelStep } from "@/components/organisms/AssistantModelStep";
import { AssistantProbesStep } from "@/components/organisms/AssistantProbesStep";
import {
  LOCAL_PROVIDERS,
  bothProbesPassed,
  defaultBaseUrls,
  errorText,
  stateLabel,
  type Validation,
} from "@/components/organisms/assistantSettingsShared";

type Step = "connection" | "models" | "probes";

const steps: { id: Step; label: string }[] = [
  { id: "connection", label: "Conexión" },
  { id: "models", label: "Modelo" },
  { id: "probes", label: "Pruebas" },
];

/** Why the footer cannot advance yet. The honest reason belongs in the footer
 *  helper text (the idea-capture pattern), never in the error slot. */
const blockedReasons: Record<Step, string | null> = {
  connection: "Validá la conexión para continuar.",
  models: "Elegí o descubrí un modelo para continuar.",
  probes: null,
};

export function AssistantSettingsPanel({
  auth,
  onStatus,
}: {
  auth: AuthSessionController;
  /** Reports the connection status to the shell. Keyed on the primitive
   *  `runtime_state` so a fresh object every render cannot loop the parent. */
  onStatus?: (status: ConnectionStatusSummary) => void;
}) {
  const navigate = useNavigate();
  const authenticated = auth.status?.authenticated ?? false;
  const [status, setStatus] = useState<AssistantSettingsStatus | null>(null);
  // Persisted confirmation: true only after a successful server save, so the
  // outcome is unambiguous and the save button can't be pressed twice.
  const [saved, setSaved] = useState(false);
  const [step, setStep] = useState<Step>("connection");
  const [provider, setProvider] = useState("opencode-go");
  const [baseUrl, setBaseUrl] = useState("");
  const [models, setModels] = useState<AssistantModelOption[]>([]);
  const [selectedModel, setSelectedModel] = useState<AssistantModelOption | null>(null);
  const [manualModelId, setManualModelId] = useState("");
  const [validation, setValidation] = useState<Validation>("idle");
  const [textProbe, setTextProbe] = useState<AssistantProbeResult | null>(null);
  const [visionProbe, setVisionProbe] = useState<AssistantProbeResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Which probe is in flight, so the combined button can label itself honestly.
  const [runningProbe, setRunningProbe] = useState<"text" | "vision" | null>(null);
  const busyRef = useRef(false);
  const apiKeyInputRef = useRef<HTMLInputElement>(null);
  // Keep the transient key outside React state so it survives step unmounts without persistence.
  const apiKeyValueRef = useRef("");

  useEffect(() => {
    if (!authenticated) return;
    let active = true;
    setLoading(true);
    void getAssistantSettings()
      .then((next) => {
        if (!active) return;
        setStatus(next);
        setProvider(next.provider || "opencode-go");
        setBaseUrl(next.base_url || "");
        setModels(next.models);
        setSelectedModel(next.model_metadata);
      })
      .catch((cause: unknown) => active && setError(errorText(cause, "No se pudo cargar la configuración")))
      .finally(() => active && setLoading(false));
    return () => {
      active = false;
    };
  }, [authenticated]);

  // Report the runtime state to the shell as a row badge. Keyed on the
  // primitive `runtime_state` (never on the `status` object) so the effect
  // only fires on a real change.
  const runtimeState = status?.runtime_state;
  useEffect(() => {
    if (!onStatus) return;
    onStatus(
      runtimeState === "active"
        ? { label: "Activo", variant: "success" }
        : runtimeState === "pending-reload"
          ? { label: "Pendiente de recarga", variant: "warning" }
          : { label: "No activo", variant: "info" },
    );
  }, [onStatus, runtimeState]);

  if (auth.isLoading || loading) {
    return <div className="flex items-center gap-2 py-6 text-small text-muted"><Spinner size="sm" /> Cargando configuración…</div>;
  }
  if (auth.error) {
    return <p className="text-small text-muted">No se pudo comprobar la sesión. Verifica la conexión con el servidor e intenta de nuevo.</p>;
  }
  if (auth.status?.enabled && !authenticated) {
    if (auth.status.mode === "local-dev") {
      return <div><p className="text-small text-muted">Inicia la sesión local para configurar el asistente.</p><Button className="mt-3" variant="secondary" onClick={() => void auth.start?.()}>Iniciar sesión local</Button></div>;
    }
    // Credentials vault mode: the login surface is the app-level AuthGate.
    return (
      <div>
        <p className="text-small text-muted">Tu sesión venció. Inicia sesión de nuevo para configurar el asistente.</p>
        <Button className="mt-3" variant="secondary" onClick={() => navigate("/")}>Iniciar sesión</Button>
      </div>
    );
  }
  if (!status) return <p className="text-small text-status-error">{error ?? "No se pudo cargar la configuración"}</p>;

  const localProvider = LOCAL_PROVIDERS.has(provider);

  // Field changes invalidate the transient state they depend on. The
  // validation covers provider/endpoint/key; a model change only invalidates
  // the probes (the connection itself still holds).
  const changeProvider = (next: string) => {
    setProvider(next);
    setBaseUrl(
      defaultBaseUrls[next] ?? (provider === "compatible" ? baseUrl : ""),
    );
    setValidation("idle");
    setTextProbe(null);
    setVisionProbe(null);
  };

  const changeBaseUrl = (value: string) => {
    setBaseUrl(value);
    setValidation("idle");
    setTextProbe(null);
    setVisionProbe(null);
  };

  const changeApiKey = (value: string) => {
    apiKeyValueRef.current = value;
    setValidation("idle");
    setTextProbe(null);
    setVisionProbe(null);
  };

  const selectModel = (id: string) => {
    setSelectedModel(models.find((model) => model.id === id) ?? null);
    setTextProbe(null);
    setVisionProbe(null);
  };

  const candidate = () => ({
    provider,
    ...(baseUrl.trim() ? { base_url: baseUrl.trim() } : {}),
    api_key: apiKeyValueRef.current.trim(),
  });

  const validate = async () => {
    setBusy(true);
    setError(null);
    try {
      const result = await validateAssistantConnection(candidate());
      if (result.outcome !== "validated") throw new Error(result.message ?? "No se pudo validar la conexión");
      setValidation("validated");
      setTextProbe(null);
      setVisionProbe(null);
    } catch (cause) {
      setValidation("failed");
      setError(errorText(cause, "No se pudo validar la conexión"));
    } finally {
      setBusy(false);
    }
  };

  const discover = async () => {
    if (validation !== "validated") return;
    setBusy(true);
    setError(null);
    try {
      const result = await discoverAssistantModels(candidate());
      if (result.outcome !== "discovered" || !result.models.length) {
        throw new Error(result.message ?? "No usable models were returned");
      }
      setModels(result.models);
      setSelectedModel(result.models[0]);
      setTextProbe(null);
      setVisionProbe(null);
    } catch (cause) {
      setModels([]);
      setSelectedModel(null);
      setTextProbe(null);
      setVisionProbe(null);
      setError(errorText(cause, "No usable models were returned"));
    } finally {
      setBusy(false);
    }
  };

  const useManualModel = () => {
    const id = manualModelId.trim();
    if (!id) return;
    setSelectedModel({ id, label: id, capability: "unknown", pricing: null });
    setModels([]);
    setTextProbe(null);
    setVisionProbe(null);
    setError(null);
  };

  const probePayload = () => ({
    ...candidate(),
    ...(selectedModel ? { model: selectedModel } : {}),
  });

  // Both probes stay separate on the backend; this single handler runs text
  // first and only runs vision when text passed, without weakening the server
  // contract enforced by the probe endpoints.
  const runCapabilityProbes = async () => {
    if (busyRef.current) return;
    if (!selectedModel || validation !== "validated") return;
    busyRef.current = true;
    setBusy(true);
    setError(null);
    setTextProbe(null);
    setVisionProbe(null);
    try {
      setRunningProbe("text");
      const text = await runAssistantTextProbe(probePayload());
      setTextProbe(text);
      if (text.outcome === "passed") {
        setRunningProbe("vision");
        try {
          setVisionProbe(await runAssistantVisionProbe(probePayload()));
        } catch (cause) {
          setVisionProbe({
            outcome: "provider_failure",
            oracle: "causal-vision",
            message: errorText(cause, "No se pudo probar la visión"),
          });
        }
      }
    } catch (cause) {
      setTextProbe({
        outcome: "provider_failure",
        oracle: "text-marker",
        message: errorText(cause, "No se pudo probar el modelo"),
      });
    } finally {
      setRunningProbe(null);
      busyRef.current = false;
      setBusy(false);
    }
  };

  const save = async () => {
    if (saved) return;
    if (!selectedModel || validation !== "validated" || textProbe?.outcome !== "passed" || visionProbe?.outcome !== "passed") return;
    setBusy(true);
    setError(null);
    try {
      const next = await saveAssistantConfiguration({
        ...candidate(),
        model: selectedModel,
        revision: status.revision,
      });
      setStatus(next);
      setSelectedModel(next.model_metadata);
      apiKeyValueRef.current = "";
      if (apiKeyInputRef.current) apiKeyInputRef.current.value = "";
      setSaved(true);
    } catch (cause) {
      setError(errorText(cause, "No se pudo guardar la configuración"));
    } finally {
      setBusy(false);
    }
  };

  /** Return to the editable flow and clear the persisted confirmation. */
  const changeConfiguration = () => {
    setSaved(false);
    setValidation("idle");
    setTextProbe(null);
    setVisionProbe(null);
    setStep("connection");
    setError(null);
  };

  const clear = async () => {
    setBusy(true);
    setError(null);
    try {
      setStatus(await clearAssistantKey());
      apiKeyValueRef.current = "";
      if (apiKeyInputRef.current) apiKeyInputRef.current.value = "";
    } catch (cause) {
      setError(errorText(cause, "No se pudo eliminar la clave"));
    } finally {
      setBusy(false);
    }
  };

  const goTo = (next: Step) => {
    setError(null);
    setStep(next);
  };

  const currentIndex = steps.findIndex((item) => item.id === step);

  // Honest completion, derived from real state — never from how far the user
  // walked. This is the single source of the navigation preconditions.
  const connectionDone = validation === "validated";
  // The GET seeds `selectedModel` from `model_metadata`, which the backend can
  // return with an EMPTY id when nothing is configured yet — a non-null object
  // is therefore not proof that a model was chosen. Require a real id, or the
  // step would read "done" on a fresh profile before the user acts.
  const modelDone = selectedModel !== null && selectedModel.id !== "";
  const probesDone = bothProbesPassed(textProbe, visionProbe);

  /** Whether `index` is unlocked by the real state of the steps before it. */
  const canReachStep = (index: number): boolean => {
    if (index <= 0) return true;
    if (index === 1) return connectionDone;
    return connectionDone && modelDone;
  };

  const canAdvance =
    currentIndex < steps.length - 1 && canReachStep(currentIndex + 1);
  const blockedReason = canAdvance ? null : blockedReasons[step];
  // A completed or current step stays revisitable; a future one does not.
  // `saved` locks the sequence so the confirmation cannot be navigated away.
  const canSelect = (index: number) =>
    !saved && (index === currentIndex || canReachStep(index));

  const stepStates: WizardStepState[] = steps.map((_entry, index) => {
    if (saved) return "done";
    const done =
      index === 0 ? connectionDone : index === 1 ? modelDone : probesDone;
    if (done) return "done";
    return index === currentIndex ? "current" : "todo";
  });

  // A blocked advance is explained in the footer, not thrown at the user as an
  // error. On the last step the hint explains the save gate instead.
  const footerHint = saved
    ? null
    : currentIndex < steps.length - 1
      ? blockedReason
      : probesDone
        ? null
        : "Ejecutá las pruebas de texto y visión para guardar.";

  const move = (direction: 1 | -1) => {
    if (saved) return;
    const next = currentIndex + direction;
    if (next < 0 || next >= steps.length) return;
    if (direction === 1 && !canAdvance) return;
    goTo(steps[next].id);
  };

  return (
    <div>
      <WizardProgress
        steps={steps}
        current={currentIndex}
        ariaLabel="Pasos de configuración"
        states={stepStates}
        onSelect={(index) => goTo(steps[index].id)}
        canSelect={canSelect}
      />
      <p className="mt-3 text-small text-muted">
        Estado: <strong>{stateLabel(status.runtime_state)}</strong>
      </p>

      <div className="mt-5 space-y-4">
        {step === "connection" && (
          <AssistantConnectionStep
            provider={provider}
            baseUrl={baseUrl}
            localProvider={localProvider}
            keyConfigured={status.key_configured}
            validation={validation}
            busy={busy}
            error={error}
            apiKeyInputRef={apiKeyInputRef}
            onProviderChange={changeProvider}
            onBaseUrlChange={changeBaseUrl}
            onApiKeyChange={changeApiKey}
            onValidate={() => void validate()}
            onClearKey={() => void clear()}
          />
        )}
        {step === "models" && (
          <AssistantModelStep
            validated={connectionDone}
            busy={busy}
            error={error}
            models={models}
            selectedModel={selectedModel}
            manualModelId={manualModelId}
            onManualModelIdChange={setManualModelId}
            onDiscover={() => void discover()}
            onSelectModel={selectModel}
            onUseManualModel={useManualModel}
          />
        )}
        {step === "probes" &&
          (saved ? (
            <AssistantConfigurationSaved
              status={status}
              provider={provider}
              selectedModel={selectedModel}
              onChangeConfiguration={changeConfiguration}
              onNavigateWorkshop={() => navigate("/taller-mundo")}
            />
          ) : (
            <AssistantProbesStep
              selectedModel={selectedModel}
              validation={validation}
              textProbe={textProbe}
              visionProbe={visionProbe}
              runningProbe={runningProbe}
              busy={busy}
              error={error}
              onRunProbes={() => void runCapabilityProbes()}
              onSave={() => void save()}
            />
          ))}
      </div>

      <div className="mt-5 flex items-start justify-between gap-3">
        <Button
          variant="ghost"
          onClick={() => move(-1)}
          disabled={currentIndex === 0 || busy || saved}
        >
          Atrás
        </Button>
        <div className="flex flex-col items-end gap-1">
          {currentIndex < steps.length - 1 && (
            <Button
              variant="secondary"
              onClick={() => move(1)}
              disabled={!canAdvance || busy}
              aria-describedby={footerHint ? "assistant-footer-hint" : undefined}
            >
              Siguiente
            </Button>
          )}
          {footerHint && (
            <span id="assistant-footer-hint" className="text-small text-muted">
              {footerHint}
            </span>
          )}
        </div>
      </div>
    </div>
  );
}
