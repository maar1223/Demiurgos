import { useCallback } from "react";
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
 * the flag before the second paint.
 */
export function useFirstValueHandoff(world: string | undefined): {
  visible: boolean;
  complete: () => void;
} {
  const visible = world !== undefined && isFirstValueHandoffPending(world);

  const complete = useCallback(() => {
    if (world !== undefined) completeFirstValueHandoff(world);
  }, [world]);

  return { visible, complete };
}