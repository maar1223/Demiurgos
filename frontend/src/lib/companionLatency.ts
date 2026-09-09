import { COMPANION_LATENCY_NOTIFIED_KEY } from "@/lib/constants";

/** Worlds that already received the first-activation latency notice (R-UI
 *  notice). Stored as a JSON string-array under
 *  COMPANION_LATENCY_NOTIFIED_KEY; malformed/missing values read as `[]`. */
export function getCompanionLatencyNotified(): string[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(COMPANION_LATENCY_NOTIFIED_KEY);
    if (!raw) return [];
    const parsed: unknown = JSON.parse(raw);
    return Array.isArray(parsed)
      ? parsed.filter((entry): entry is string => typeof entry === "string")
      : [];
  } catch {
    return [];
  }
}

/** Records `world` as notified. Returns true ONLY the first time — the
 *  notice-once contract: later activations in the same world stay silent. */
export function markCompanionLatencyNotified(world: string): boolean {
  if (typeof window === "undefined") return false;
  const notified = getCompanionLatencyNotified();
  if (notified.includes(world)) return false;
  notified.push(world);
  window.localStorage.setItem(
    COMPANION_LATENCY_NOTIFIED_KEY,
    JSON.stringify(notified),
  );
  return true;
}