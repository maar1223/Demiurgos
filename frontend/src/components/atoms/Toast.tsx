import { Icon } from "@/components/atoms/Icon";
import { cn } from "@/lib/utils";

export type ToastKind = "success" | "error";

interface ToastProps {
  message: string;
  kind?: ToastKind;
}

/**
 * Transient toast for move feedback (DnD and move-to-section flows).
 *
 * Presentational-only: the owner keeps the message state and clears it after
 * a short delay, mirroring the "Guardado ✓" pattern in WikiEditor. Animates
 * in with the shared `fade-slide-in` utility; colors stick to the Demiurgos
 * palette (llamita for success, sangre for errors).
 */
export function Toast({ message, kind = "success" }: ToastProps) {
  return (
    <div
      role="status"
      aria-live="polite"
      className={cn(
        "fixed bottom-6 right-6 z-50 flex items-center gap-2.5 rounded-lg border bg-madero px-4 py-2.5 text-small shadow-xl fade-slide-in",
        kind === "success"
          ? "border-llamita/40 text-pergamino"
          : "border-sangre/50 text-sangre",
      )}
    >
      <Icon
        name={kind === "success" ? "check" : "error"}
        size={16}
        className={kind === "success" ? "text-llamita" : "text-sangre"}
      />
      <span>{message}</span>
    </div>
  );
}
