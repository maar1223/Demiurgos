import type {
  AssistantModelOption,
  AssistantProbeResult,
  AssistantSettingsStatus,
} from "@/api/types";

/** Outcome of the connection-validation call, owned by the panel. */
export type Validation = "idle" | "validated" | "failed";

/** Provider choices for the connection step. The label is user copy. */
export const providers = [
  ["opencode-go", "OpenCode Go"],
  ["openai", "OpenAI"],
  ["openrouter", "OpenRouter"],
  ["compatible", "OpenAI-compatible"],
  ["ollama", "Ollama (local)"],
  ["lm-studio", "LM Studio (local)"],
] as const;

/** Endpoint suggested when a provider is selected. */
export const defaultBaseUrls: Record<string, string> = {
  "opencode-go": "https://opencode.ai/zen/go/v1",
  openai: "https://api.openai.com/v1",
  openrouter: "https://openrouter.ai/api/v1",
  ollama: "http://127.0.0.1:11434",
  "lm-studio": "http://127.0.0.1:1234/v1",
};

/** Local runtimes need no API key. */
export const LOCAL_PROVIDERS = new Set(["ollama", "lm-studio"]);

export const inputClass =
  "w-full rounded-md border border-edge bg-surface-raised py-1.5 px-3 text-small text-primary " +
  "placeholder:text-muted focus:border-action focus:outline-none focus:ring-1 focus:ring-action/50";

export const labelClass = "mb-1 block text-small text-muted";

export function errorText(cause: unknown, fallback: string): string {
  return cause instanceof Error ? cause.message : fallback;
}

/**
 * Whether both capability probes passed. Single source for the Pruebas
 * completion gate and the save gate, so the indicator and the button cannot
 * drift apart.
 */
export function bothProbesPassed(
  text: AssistantProbeResult | null,
  vision: AssistantProbeResult | null,
): boolean {
  return text?.outcome === "passed" && vision?.outcome === "passed";
}

export function stateLabel(
  state: AssistantSettingsStatus["runtime_state"],
): string {
  return state === "active"
    ? "Activo"
    : state === "pending-reload"
      ? "Guardado, sin verificar"
      : "Guardado, no activo";
}

/** Contextual explanation for each runtime state, shown after a successful save. */
export function stateContext(
  state: AssistantSettingsStatus["runtime_state"],
): string {
  return state === "active"
    ? "La configuración ya está aplicada y el asistente la está usando."
    : state === "pending-reload"
      ? "La configuración se guardó, pero el asistente todavía no la confirmó para esta versión."
      : "La configuración se guardó, pero el asistente no está activo en este momento.";
}

export function modelDescription(model: AssistantModelOption | null): string {
  if (!model || model.capability === "unknown") return "Capacidad desconocida";
  return model.capability === "multimodal" ? "Multimodal" : "Solo texto";
}
