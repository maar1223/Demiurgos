import { FIRST_VALUE_HANDOFF_PENDING_KEY } from "@/lib/constants";

/** Worlds awaiting the one-time first-value handoff hero. Stored as a JSON
 *  string-array under FIRST_VALUE_HANDOFF_PENDING_KEY; malformed/missing
 *  values read as `[]`. */
export function getFirstValueHandoffPending(): string[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(FIRST_VALUE_HANDOFF_PENDING_KEY);
    if (!raw) return [];
    const parsed: unknown = JSON.parse(raw);
    return Array.isArray(parsed)
      ? parsed.filter((entry): entry is string => typeof entry === "string")
      : [];
  } catch {
    return [];
  }
}

/** Records `world` as pending the handoff. Idempotent add. */
export function markFirstValueHandoffPending(world: string): void {
  if (typeof window === "undefined") return;
  const pending = getFirstValueHandoffPending();
  if (pending.includes(world)) return;
  pending.push(world);
  window.localStorage.setItem(
    FIRST_VALUE_HANDOFF_PENDING_KEY,
    JSON.stringify(pending),
  );
}

/** True when `world` still awaits the first-value handoff. */
export function isFirstValueHandoffPending(world: string): boolean {
  return getFirstValueHandoffPending().includes(world);
}

/** Removes `world` from the pending set (dismissal or action choice).
 *  Idempotent remove. */
export function completeFirstValueHandoff(world: string): void {
  if (typeof window === "undefined") return;
  const pending = getFirstValueHandoffPending();
  if (!pending.includes(world)) return;
  window.localStorage.setItem(
    FIRST_VALUE_HANDOFF_PENDING_KEY,
    JSON.stringify(pending.filter((entry) => entry !== world)),
  );
}