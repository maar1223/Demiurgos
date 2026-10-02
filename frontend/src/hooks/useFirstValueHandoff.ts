import { useCallback, useState } from "react";
import {
  completeFirstValueHandoff,
  isFirstValueHandoffPending,
} from "@/lib/firstValueHandoff";

/**
 * One-time first-value handoff visibility for a world (first-value-handoff
 * spec).
 *
 * `visible` is a PURE read (`isFirstValueHandoffPending`) during render;
 * mutation (`complete`) happens only on a user interaction (dismiss/action),
 * never in an effect — StrictMode-safe: the dev double-mount cannot clear
 * the flag before the second paint. `complete` also flips local state so a
 * same-page dismissal hides the hero without remounting.
 */
export function useFirstValueHandoff(world: string | undefined): {
  visible: boolean;
  complete: () => void;
} {
  const [completed, setCompleted] = useState(false);

  const visible =
    world !== undefined &&
    !completed &&
    isFirstValueHandoffPending(world);

  const complete = useCallback(() => {
    if (world === undefined) return;
    completeFirstValueHandoff(world);
    setCompleted(true);
  }, [world]);

  return { visible, complete };
}