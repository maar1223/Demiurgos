import { useEffect, useState } from "react";
import { cn } from "@/lib/utils";

interface ElapsedTimeProps {
  className?: string;
}

/**
 * Live `m:ss` counter for one in-flight terse operation (an assistant turn).
 *
 * It measures wall clock from mount, so a backgrounded or throttled tab still
 * reports real elapsed time instead of counting its own ticks. `role="timer"`
 * is deliberately not a live region: the elapsed value is visual feedback and
 * must never interrupt a screen reader on every tick.
 */
export function ElapsedTime({ className }: ElapsedTimeProps) {
  const [elapsedSeconds, setElapsedSeconds] = useState(0);

  useEffect(() => {
    const startedAt = Date.now();
    const interval = setInterval(() => {
      setElapsedSeconds(Math.floor((Date.now() - startedAt) / 1000));
    }, 1000);
    return () => clearInterval(interval);
  }, []);

  const minutes = Math.floor(elapsedSeconds / 60);
  const seconds = elapsedSeconds % 60;

  return (
    <span role="timer" className={cn("tabular-nums", className)}>
      {minutes}:{String(seconds).padStart(2, "0")}
    </span>
  );
}
