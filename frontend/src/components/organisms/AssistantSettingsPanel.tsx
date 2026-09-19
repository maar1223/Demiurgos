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
import { SecretInput } from "@/components/molecules/SecretInput";
import type { AuthSessionController } from "@/components/organisms/IdeaCapturePanel";

type Step = "provider" | "connection" | "models" | "capability" | "confirmation";
type Validation = "idle" | "validated" | "failed";

const steps: { id: Step; label: string }[] = [
  { id: "provider", label: "Proveedor" },
  { id: "connection", label: "Conexión" },
  { id: "models", label: "Modelos" },
  { id: "capability", label: "Capacidad" },
  { id: "confirmation", label: "Confirmación" },
];
const providers = [
  ["opencode-go", "OpenCode Go"],
  ["openai", "OpenAI"],
  ["openrouter", "OpenRouter"],
  ["compatible", "OpenAI-compatible"],
  ["ollama", "Ollama (local)"],
  ["lm-studio", "LM Studio (local)"],
] as const;
const defaultBaseUrls: Record<string, string> = {
  "opencode-go": "https://opencode.ai/zen/go/v1",
  openai: "https://api.openai.com/v1",
  openrouter: "https://openrouter.ai/api/v1",
  ollama: "http://127.0.0.1:11434",
  "lm-studio": "http://127.0.0.1:1234/v1",
};
const LOCAL_PROVIDERS = new Set(["ollama", "lm-studio"]);
const inputClass =
  "w-full rounded-md border border-edge bg-surface-raised py-1.5 px-3 text-small text-primary " +
  "placeholder:text-muted focus:border-action focus:outline-none focus:ring-1 focus:ring-action/50";
const labelClass = "mb-1 block text-small text-muted";

function errorText(cause: unknown, fallback: string): string {
  return cause instanceof Error ? cause.message : fallback;
}

function stateLabel(state: AssistantSettingsStatus["runtime_state"]): string {
  return state === "active"
    ? "Activo"
    : state === "pending-reload"
      ? "Guardado, pendiente de recarga"
      : "Guardado, no activo";
}

/** Contextual explanation for each runtime state, shown after a successful save. */
function stateContext(state: AssistantSettingsStatus["runtime_state"]): string {
  return state === "active"
    ? "La configuración ya está aplicada y el asistente la está usando."
    : state === "pending-reload"
      ? "La configuración se guardó, pero el asistente necesita recargarse o reiniciarse para aplicarla."
      : "La configuración se guardó, pero el asistente no está activo en este momento.";
}

function modelDescription(model: AssistantModelOption | null): string {
  if (!model || model.capability === "unknown") return "Capacidad desconocida";
  return model.capability === "multimodal" ? "Multimodal" : "Solo texto";
}

export function AssistantSettingsPanel({ auth }: { auth: AuthSessionController }) {
  const navigate = useNavigate();
  const authenticated = auth.status?.authenticated ?? false;
  const [status, setStatus] = useState<AssistantSettingsStatus | null>(null);
  // Persisted confirmation: true only after a successful server save, so the
  // outcome is unambiguous and the save button can't be pressed twice.
  const [saved, setSaved] = useState(false);
  const [step, setStep] = useState<Step>("provider");
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

  if (auth.isLoading || loading) {
    return <div className="flex items-center gap-2 py-6 text-small text-muted"><Spinner size="sm" /> Cargando configuración…</div>;
  }
  if (auth.error) {
    return <p className="rounded-lg border border-edge bg-surface-raised p-4 text-small text-muted">No se pudo comprobar la sesión. Verifica la conexión con el servidor e intenta de nuevo.</p>;
  }
  if (auth.status?.enabled && !authenticated) {
    if (auth.status.mode === "local-dev") {
      return <div className="rounded-lg border border-edge bg-surface-raised p-4"><p className="text-small text-muted">Inicia la sesión local para configurar el asistente.</p><Button className="mt-3" onClick={() => void auth.start?.()}>Iniciar sesión local</Button></div>;
    }
    // Credentials vault mode: the login surface is the app-level AuthGate.
    return (
      <div className="rounded-lg border border-edge bg-surface-raised p-4">
        <p className="text-small text-muted">Tu sesión venció. Inicia sesión de nuevo para configurar el asistente.</p>
        <Button className="mt-3" onClick={() => navigate("/")}>Iniciar sesión</Button>
      </div>
    );
  }
  if (!status) return <p className="text-small text-status-error">{error ?? "No se pudo cargar la configuración"}</p>;

  const localProvider = LOCAL_PROVIDERS.has(provider);

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
    setStep("provider");
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
    if (next === "capability" && validation !== "validated") {
      setError("Validá la conexión antes de probar el modelo");
      return;
    }
    if (next === "confirmation" && (validation !== "validated" || textProbe?.outcome !== "passed" || visionProbe?.outcome !== "passed")) {
      setError("Completá la conexión y las pruebas de texto y visión antes de confirmar");
      return;
    }
    setStep(next);
  };
  const move = (direction: 1 | -1) => {
    const index = steps.findIndex((item) => item.id === step) + direction;
    if (index >= 0 && index < steps.length) goTo(steps[index].id);
  };

  return (
    <div className="rounded-lg border border-edge bg-surface-raised p-4">
      <h3 className="font-heading text-body text-primary">Asistente del Wiki</h3>
      <p className="mt-1 text-small text-muted">Configuración provider-neutral. Las claves solo se envían al backend autenticado.</p>
      {saved ? (
        <div className="mt-4 rounded-lg border border-status-success/30 bg-status-success/10 p-4" role="status" aria-live="polite">
          <h4 className="font-heading text-body text-primary">Configuración guardada</h4>
          <p className="mt-1 text-small text-muted">La configuración se guardó correctamente en el servidor.</p>
          <dl className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div>
              <dt className="text-small text-muted">Proveedor</dt>
              <dd className="text-small text-primary">{provider}</dd>
            </div>
            <div>
              <dt className="text-small text-muted">Modelo</dt>
              <dd className="text-small text-primary">{selectedModel?.label ?? status.model}</dd>
            </div>
            <div>
              <dt className="text-small text-muted">Capacidad</dt>
              <dd className="text-small text-primary">Texto: superada · Visión: superada</dd>
            </div>
            <div>
              <dt className="text-small text-muted">Estado runtime</dt>
              <dd className="text-small text-primary">
                <strong>{stateLabel(status.runtime_state)}</strong>
                <span className="block text-small text-muted">{stateContext(status.runtime_state)}</span>
              </dd>
            </div>
          </dl>
          <div className="mt-4 flex flex-wrap gap-2">
            <Button variant="primary" onClick={changeConfiguration}>Cambiar configuración</Button>
            <Button variant="secondary" onClick={() => navigate("/taller-mundo")}>Volver al Taller de Mundos</Button>
          </div>
        </div>
      ) : (
        <>
          <div className="mt-4 flex flex-wrap gap-1" aria-label="Pasos de configuración">
            {steps.map((item) => <Button key={item.id} variant={step === item.id ? "secondary" : "ghost"} size="sm" onClick={() => goTo(item.id)}>{item.label}</Button>)}
          </div>
          <p className="mt-3 text-small text-muted">Estado: <strong>{stateLabel(status.runtime_state)}</strong></p>
          <div className="mt-5 space-y-4">
            {step === "provider" && <section><h4 className="font-heading text-body text-primary">Proveedor</h4><label className={labelClass} htmlFor="assistant-provider">Elegí un proveedor</label><select id="assistant-provider" className={inputClass} value={provider} onChange={(event) => { const nextProvider = event.target.value; setProvider(nextProvider); setBaseUrl(defaultBaseUrls[nextProvider] ?? (provider === "compatible" ? baseUrl : "")); setValidation("idle"); setTextProbe(null); setVisionProbe(null); }} >{providers.map(([id, label]) => <option key={id} value={id}>{label}</option>)}</select><p className="mt-2 text-small text-muted">OpenCode Go es la opción recomendada. Ollama y LM Studio son locales y no requieren clave. Los endpoints compatibles requieren una URL propia.</p></section>}
            {step === "connection" && <section><h4 className="font-heading text-body text-primary">Conexión</h4><label className={labelClass} htmlFor="assistant-base-url">Endpoint</label><input id="assistant-base-url" className={inputClass} value={baseUrl} onChange={(event) => { setBaseUrl(event.target.value); setValidation("idle"); setTextProbe(null); setVisionProbe(null); }} placeholder="https://..." />{!localProvider && <><label className={`${labelClass} mt-3`} htmlFor="assistant-api-key">Clave API</label><SecretInput ref={apiKeyInputRef} copyable id="assistant-api-key" autoComplete="new-password" className={inputClass} onChange={(event) => { apiKeyValueRef.current = event.target.value; setValidation("idle"); setTextProbe(null); setVisionProbe(null); }} placeholder={status.key_configured ? "Clave ya configurada — dejá vacío para usar la almacenada" : "Ingresá tu clave"} />{status.key_configured && <p className="mt-1 text-small text-muted">Ya hay una clave guardada para este proveedor. Podés cambiar de modelo sin reescribirla.</p>}</>}<div className="mt-3 flex flex-wrap gap-2"><Button onClick={() => void validate()} disabled={busy}>{busy ? "Validando…" : "Validar conexión"}</Button>{status.key_configured && <Button variant="secondary" onClick={() => void clear()} disabled={busy}>Eliminar clave</Button>}</div>{validation === "validated" && <p className="mt-2 text-small text-status-success">Conexión validada.</p>}</section>}
            {step === "models" && <section><h4 className="font-heading text-body text-primary">Modelos</h4>{validation !== "validated" ? <p className="text-small text-muted">Validá la conexión para habilitar el descubrimiento.</p> : <><Button onClick={() => void discover()} disabled={busy}>{busy ? "Buscando…" : "Descubrir modelos"}</Button>{error && <p className="mt-2 text-small text-status-error">{error}</p>}{models.length > 0 && <select aria-label="Modelo descubierto" className={`${inputClass} mt-3`} value={selectedModel?.id ?? ""} onChange={(event) => { setSelectedModel(models.find((model) => model.id === event.target.value) ?? null); setTextProbe(null); setVisionProbe(null); }}>{models.map((model) => <option key={model.id} value={model.id}>{model.label}</option>)}</select>}<label className={`${labelClass} mt-3`} htmlFor="assistant-manual-model">ID de modelo manual</label><input id="assistant-manual-model" className={inputClass} value={manualModelId} onChange={(event) => setManualModelId(event.target.value)} placeholder="model-id" /><Button className="mt-2" variant="secondary" onClick={useManualModel}>Usar modelo manual</Button>{selectedModel && <p className="mt-3 text-small text-muted">{modelDescription(selectedModel)} · {selectedModel.pricing ? "Precio informado" : "Precio no disponible"}</p>}</>}</section>}
            {step === "capability" && <section><h4 className="font-heading text-body text-primary">Capacidad</h4><p className="mt-1 text-small text-muted">El modelo debe superar la prueba de texto y, si pasa, la prueba causal de visión (verifica que realmente ve la imagen, no que la memorizó).</p><Button onClick={() => void runCapabilityProbes()} disabled={busy || !selectedModel || validation !== "validated"}>{runningProbe === "text" ? "Probando texto…" : runningProbe === "vision" ? "Probando visión…" : "Probar texto + visión"}</Button><div className="mt-3 space-y-3"><div><p className="text-small text-muted">Prueba de texto</p>{textProbe ? <p aria-live="polite" className={`mt-1 text-small ${textProbe.outcome === "passed" ? "text-status-success" : "text-status-error"}`}>{textProbe.outcome === "passed" ? "Prueba de texto superada." : textProbe.message ?? "La prueba de texto no pasó."}</p> : <p className="mt-1 text-small text-muted">Sin ejecutar.</p>}</div><div><p className="text-small text-muted">Prueba de visión</p>{visionProbe ? <p aria-live="polite" className={`mt-1 text-small ${visionProbe.outcome === "passed" ? "text-status-success" : "text-status-error"}`}>{visionProbe.outcome === "passed" ? "Prueba de visión superada." : visionProbe.message ?? "La prueba de visión no pasó."}</p> : textProbe && textProbe.outcome !== "passed" ? <p aria-live="polite" className="mt-1 text-small text-muted">La visión no se ejecutó porque la prueba de texto no pasó.</p> : <p className="mt-1 text-small text-muted">Sin ejecutar.</p>}</div></div></section>}
            {step === "confirmation" && <section><h4 className="font-heading text-body text-primary">Confirmación</h4><p className="text-small text-muted">{provider} · {selectedModel?.label ?? "Sin modelo"}</p><p className="mt-2 text-small text-status-success">Prueba de texto: superada · Prueba de visión: superada</p><p className="mt-1 text-small text-muted">Al confirmar, el backend vuelve a ejecutar ambas pruebas antes de persistir.</p><Button className="mt-4" onClick={() => void save()} disabled={busy || saved || !selectedModel || textProbe?.outcome !== "passed" || visionProbe?.outcome !== "passed"}>{busy ? "Guardando…" : "Guardar configuración"}</Button></section>}
            {error && step !== "models" && <p className="text-small text-status-error">{error}</p>}
          </div>
          <div className="mt-5 flex gap-2"><Button variant="secondary" onClick={() => move(-1)} disabled={step === "provider"}>Atrás</Button><Button variant="secondary" onClick={() => move(1)} disabled={step === "confirmation" || (step === "connection" && validation !== "validated") || (step === "capability" && (validation !== "validated" || textProbe?.outcome !== "passed" || visionProbe?.outcome !== "passed"))}>Siguiente</Button></div>
        </>
      )}
    </div>
  );
}
