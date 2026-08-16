import { useCallback, useEffect, useState } from "react";
import {
  getCurrentWorld,
  setCurrentWorld,
  subscribeCurrentWorld,
} from "@/lib/currentWorld";

export function useCurrentWorld() {
  const [world, setWorld] = useState<string | null>(() => getCurrentWorld());

  useEffect(() => {
    return subscribeCurrentWorld(() => setWorld(getCurrentWorld()));
  }, []);

  const selectWorld = useCallback((next: string) => {
    setCurrentWorld(next);
  }, []);

  return { world, selectWorld };
}