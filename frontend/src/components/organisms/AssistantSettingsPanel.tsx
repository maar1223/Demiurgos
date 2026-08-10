import { useEffect, useRef, useState } from "react";
import {
  clearAssistantKey,
  discoverAssistantModels,
  getAssistantSettings,
  saveAssistantConfiguration,
  validateAssistantConnection,
} from "@/api/assistantSettings";
import type {
  AssistantModelOption,
  AssistantSettingsStatus,
} from "@/api/types";
import { Button } from "@/components/atoms/Button";
import { Spinner } from "@/components/atoms/Spinner";
import type { LocalAuthController } from "@/components/organisms/IdeaCapturePanel";

type Step = "provider" | "connection" | "models" | "confirmation";
type Validation = "idle" | "validated" | "failed";

const steps: { id: Step; label: string }[] = [
  { id: "provider", label: "Proveedor" },
  { id: "connection", label: "Conexión" },
  { id: "models", label: "Modelos" },
  { id: "confirmation", label: "Confirmación" },
];
const providers = [
  ["opencode-go", "OpenCode Go"],
  ["openai", "OpenAI"],
  ["openrouter", "OpenRouter"],
  ["compatible", "OpenAI-compatible"],
] as const;
const inputClass =
  "w-full rounded-md border border-filio bg-piedra py-1.5 px-3 text-small text-pergamino " +
  "placeholder:text-sombra focus:border-llamita focus:outline-none focus:ring-1 focus:ring-llamita/50";
const labelClass = "mb-1 block text-small text-tinta-desvaida";

function errorText(cause: unknown, fallback: string): string {
  return cause instanceof Error ? cause.message : fallback;
}

function stateLabel(state: AssistantSettingsStatus["runtime_state"]): string {
  return state === "active"
    ? "Activo"
    : state === "pending-reload"
      ? "Pendiente de reinicio/recarga"
      : "Guardado, no activo";
}

function modelDescription(model: AssistantModelOption | null): string {
  if (!model || model.capability === "unknown") return "Capacidad desconocida";
  return model.capability === "multimodal" ? "Multimodal" : "Solo texto";
}

export function AssistantSettingsPanel({ auth }: { auth: LocalAuthController }) {
  const authenticated = auth.status?.authenticated ?? false;
  const [status, setStatus] = useState<AssistantSettingsStatus | null>(null);
  const [step, setStep] = useState<Step>("provider");
  const [provider, setProvider] = useState("opencode-go");
  const [baseUrl, setBaseUrl] = useState("");
  const [models, setModels] = useState<AssistantModelOption[]>([]);
  const [selectedModel, setSelectedModel] = useState<AssistantModelOption | null>(null);
  const [manualModelId, setManualModelId] = useState("");
  const [validation, setValidation] = useState<Validation>("idle");
  const [unknownAck, setUnknownAck] = useState(false);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
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
    return <div className="flex items-center gap-2 py-6 text-small text-tinta-desvaida"><Spinner size="sm" /> Cargando configuración…</div>;
  }
  if (!auth.status?.enabled) {
    return <p className="rounded-lg border border-filio bg-madero p-4 text-small text-tinta-desvaida">La configuración requiere la sesión local.</p>;
  }
  if (!authenticated) {
    return <div className="rounded-lg border border-filio bg-madero p-4"><p className="text-small text-tinta-desvaida">Iniciá la sesión local para configurar el asistente.</p><Button className="mt-3" onClick={() => void auth.start()}>Iniciar sesión local</Button></div>;
  }
  if (!status) return <p className="text-small text-sangre">{error ?? "No se pudo cargar la configuración"}</p>;

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
    } catch (cause) {
      setModels([]);
      setSelectedModel(null);
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
    setError(null);
  };

  const save = async () => {
    if (!selectedModel || validation !== "validated" || (selectedModel.capability === "unknown" && !unknownAck)) return;
    setBusy(true);
    setError(null);
    try {
      const next = await saveAssistantConfiguration({
        ...candidate(),
        model: selectedModel,
        revision: status.revision,
        unknown_ack: unknownAck,
      });
      setStatus(next);
      setSelectedModel(next.model_metadata);
      apiKeyValueRef.current = "";
      if (apiKeyInputRef.current) apiKeyInputRef.current.value = "";
    } catch (cause) {
      setError(errorText(cause, "No se pudo guardar la configuración"));
    } finally {
      setBusy(false);
    }
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
    if (next === "confirmation" && validation !== "validated") {
      setError("Validá la conexión antes de confirmar");
      return;
    }
    setStep(next);
  };
  const move = (direction: 1 | -1) => {
    const index = steps.findIndex((item) => item.id === step) + direction;
    if (index >= 0 && index < steps.length) goTo(steps[index].id);
  };

  return (
    <div className="rounded-lg border border-filio bg-madero p-4">
      <h3 className="font-heading text-body text-pergamino">Asistente del Wiki</h3>
      <p className="mt-1 text-small text-tinta-desvaida">Configuración provider-neutral. Las claves solo se envían al backend autenticado.</p>
      <div className="mt-4 flex flex-wrap gap-1" aria-label="Pasos de configuración">
        {steps.map((item) => <Button key={item.id} variant={step === item.id ? "primary" : "ghost"} size="sm" onClick={() => goTo(item.id)}>{item.label}</Button>)}
      </div>
      <p className="mt-3 text-small text-tinta-desvaida">Estado: <strong>{stateLabel(status.runtime_state)}</strong></p>
      <div className="mt-5 space-y-4">
        {step === "provider" && <section><h4 className="font-heading text-body text-pergamino">Proveedor</h4><label className={labelClass} htmlFor="assistant-provider">Elegí un proveedor</label><select id="assistant-provider" className={inputClass} value={provider} onChange={(event) => { setProvider(event.target.value); setValidation("idle"); }} >{providers.map(([id, label]) => <option key={id} value={id}>{label}</option>)}</select><p className="mt-2 text-small text-tinta-desvaida">OpenCode Go es la opción recomendada. Los endpoints compatibles requieren una URL propia.</p></section>}
        {step === "connection" && <section><h4 className="font-heading text-body text-pergamino">Conexión</h4><label className={labelClass} htmlFor="assistant-base-url">Endpoint</label><input id="assistant-base-url" className={inputClass} value={baseUrl} onChange={(event) => { setBaseUrl(event.target.value); setValidation("idle"); }} placeholder="https://..." /><label className={`${labelClass} mt-3`} htmlFor="assistant-api-key">Clave API</label><input ref={apiKeyInputRef} id="assistant-api-key" type="password" autoComplete="new-password" className={inputClass} onChange={(event) => { apiKeyValueRef.current = event.target.value; setValidation("idle"); }} placeholder={status.key_configured ? "Ingresá una clave para validar" : "Ingresá tu clave"} /><div className="mt-3 flex flex-wrap gap-2"><Button onClick={() => void validate()} disabled={busy}>{busy ? "Validando…" : "Validar conexión"}</Button>{status.key_configured && <Button variant="secondary" onClick={() => void clear()} disabled={busy}>Eliminar clave</Button>}</div>{validation === "validated" && <p className="mt-2 text-small text-musgo">Conexión validada.</p>}</section>}
        {step === "models" && <section><h4 className="font-heading text-body text-pergamino">Modelos</h4>{validation !== "validated" ? <p className="text-small text-tinta-desvaida">Validá la conexión para habilitar el descubrimiento.</p> : <><Button onClick={() => void discover()} disabled={busy}>{busy ? "Buscando…" : "Descubrir modelos"}</Button>{error && <p className="mt-2 text-small text-sangre">{error}</p>}{models.length > 0 && <select aria-label="Modelo descubierto" className={`${inputClass} mt-3`} value={selectedModel?.id ?? ""} onChange={(event) => setSelectedModel(models.find((model) => model.id === event.target.value) ?? null)}>{models.map((model) => <option key={model.id} value={model.id}>{model.label}</option>)}</select>}<label className={`${labelClass} mt-3`} htmlFor="assistant-manual-model">ID de modelo manual</label><input id="assistant-manual-model" className={inputClass} value={manualModelId} onChange={(event) => setManualModelId(event.target.value)} placeholder="model-id" /><Button className="mt-2" variant="secondary" onClick={useManualModel}>Usar modelo manual</Button>{selectedModel && <p className="mt-3 text-small text-tinta-desvaida">{modelDescription(selectedModel)} · {selectedModel.pricing ? "Precio informado" : "Precio no disponible"}</p>}</>}</section>}
        {step === "confirmation" && <section><h4 className="font-heading text-body text-pergamino">Confirmación</h4><p className="text-small text-tinta-desvaida">{provider} · {selectedModel?.label ?? "Sin modelo"}</p><p className="mt-2 text-small text-tinta-desvaida">{modelDescription(selectedModel)} · {selectedModel?.pricing ? "Precio informado" : "Precio no disponible"}</p>{selectedModel?.capability === "unknown" && <label className="mt-3 flex gap-2 text-small text-tinta-desvaida"><input type="checkbox" checked={unknownAck} onChange={(event) => setUnknownAck(event.target.checked)} /> Acepto continuar con capacidad desconocida</label>}<Button className="mt-4" onClick={() => void save()} disabled={busy || !selectedModel || (selectedModel.capability === "unknown" && !unknownAck)}>{busy ? "Guardando…" : "Guardar configuración"}</Button></section>}
        {error && step !== "models" && <p className="text-small text-sangre">{error}</p>}
      </div>
      <div className="mt-5 flex gap-2"><Button variant="secondary" onClick={() => move(-1)} disabled={step === "provider"}>Atrás</Button><Button variant="secondary" onClick={() => move(1)} disabled={step === "confirmation" || (step === "connection" && validation !== "validated")}>Siguiente</Button></div>
    </div>
  );
}
