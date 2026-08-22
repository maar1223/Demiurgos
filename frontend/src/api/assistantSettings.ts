import { apiFetch } from "@/api/client";
import type {
  AssistantConnectionInput,
  AssistantDiscoveryResult,
  AssistantProbeInput,
  AssistantProbeResult,
  AssistantSettingsStatus,
  AssistantValidationResult,
  SaveAssistantConfigurationInput,
} from "@/api/types";

const CREDENTIALS = { credentials: "same-origin" as const };

/**
 * Assistant settings status is metadata-only: the write-only key is accepted
 * in request payloads but never returned, stored in frontend state, or logged.
 * Saves return Active, Pending restart/reload, or Saved-not-active; the API
 * reports that state but does not control Hermes or any process lifecycle.
 * The primary model is configured only after the text and causal-vision
 * probes pass and the Hermes runtime accepts the saved revision.
 */
export function getAssistantSettings(): Promise<AssistantSettingsStatus> {
  return apiFetch<AssistantSettingsStatus>("/api/profile/assistant", CREDENTIALS);
}

export function validateAssistantConnection(
  input: AssistantConnectionInput,
): Promise<AssistantValidationResult> {
  return apiFetch<AssistantValidationResult>("/api/profile/assistant/connection/validate", {
    method: "POST",
    body: JSON.stringify(input),
    ...CREDENTIALS,
    timeout: 15_000,
  });
}

export function discoverAssistantModels(
  input: AssistantConnectionInput,
): Promise<AssistantDiscoveryResult> {
  return apiFetch<AssistantDiscoveryResult>("/api/profile/assistant/models/discover", {
    method: "POST",
    body: JSON.stringify(input),
    ...CREDENTIALS,
    timeout: 15_000,
  });
}

export function runAssistantTextProbe(input: AssistantProbeInput): Promise<AssistantProbeResult> {
  return apiFetch<AssistantProbeResult>("/api/profile/assistant/probe/text", {
    method: "POST",
    body: JSON.stringify(input),
    ...CREDENTIALS,
    timeout: 90_000,
  });
}

export function runAssistantVisionProbe(input: AssistantProbeInput): Promise<AssistantProbeResult> {
  return apiFetch<AssistantProbeResult>("/api/profile/assistant/probe/vision", {
    method: "POST",
    body: JSON.stringify(input),
    ...CREDENTIALS,
    timeout: 180_000,
  });
}

export function saveAssistantConfiguration(
  input: SaveAssistantConfigurationInput,
): Promise<AssistantSettingsStatus> {
  return apiFetch<AssistantSettingsStatus>("/api/profile/assistant/configuration", {
    method: "PUT",
    body: JSON.stringify(input),
    ...CREDENTIALS,
    timeout: 240_000,
  });
}

export function clearAssistantKey(): Promise<AssistantSettingsStatus> {
  return apiFetch<AssistantSettingsStatus>("/api/profile/assistant/configuration/key", {
    method: "DELETE",
    ...CREDENTIALS,
  });
}
