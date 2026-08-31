import { useEffect, useRef, useState } from "react";
import { Icon } from "@/components/atoms/Icon";
import { cn, getErrorMessage } from "@/lib/utils";
import { STATUS_META } from "@/lib/status";
import { ApiError, type FichaStatus } from "@/api/types";

interface StatusBadgeProps {
  /** Current OKF status — Borrador (draft) or Canon (stable). */
  status: FichaStatus;
  /** Called with the selected status; the parent performs the mutation. */
  onStatusChange: (status: FichaStatus) => Promise<void> | void;
}

/**
 * File-bar chip showing a ficha's OKF status (Borrador/Canon). Clicking
 * opens a two-option radio dropdown; the mutation is instant and
 * reversible (no confirmation dialog). Loading disables the options; a
 * failed mutation shows the error inline and keeps the chip unchanged
 * (same contract as the setPortada flow in WikiEditor: state untouched
 * until the request succeeds). Closes on outside click and Escape.
 */
export function StatusBadge({ status, onStatusChange }: StatusBadgeProps) {
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  const meta = STATUS_META[status];
  const options: FichaStatus[] = ["draft", "stable"];

  // Global close: document mousedown outside the wrapper + Escape (same
  // pattern as CardMenu).
  useEffect(() => {
    if (!open) return;

    const handleMousedown = (e: MouseEvent) => {
      if (
        containerRef.current &&
        !containerRef.current.contains(e.target as Node)
      ) {
        setOpen(false);
      }
    };
    const handleKeydown = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };

    document.addEventListener("mousedown", handleMousedown);
    document.addEventListener("keydown", handleKeydown);
    return () => {
      document.removeEventListener("mousedown", handleMousedown);
      document.removeEventListener("keydown", handleKeydown);
    };
  }, [open]);

  const handleSelect = async (next: FichaStatus) => {
    if (next === status || loading) return;
    setLoading(true);
    setError(null);
    try {
      await onStatusChange(next);
      setOpen(false);
    } catch (err) {
      const apiErr = err as ApiError;
      setError(getErrorMessage(apiErr.status, apiErr.detail));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div ref={containerRef} className="relative inline-block">
      <button
        type="button"
        onClick={() => setOpen((prev) => !prev)}
        aria-label={`Estado: ${meta.label}`}
        aria-haspopup="menu"
        aria-expanded={open}
        className={cn(
          "flex h-8 shrink-0 items-center gap-1.5 rounded-md border px-2.5 text-xs font-medium transition-colors",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-action/50",
          meta.chipClass,
        )}
      >
        {loading ? (
          <Icon
            name="spinner"
            size={12}
            className="animate-spin"
            aria-hidden="true"
          />
        ) : (
          <span className="h-1.5 w-1.5 rounded-full bg-current" aria-hidden="true" />
        )}
        {meta.label}
        <Icon name="chevron-down" size={12} aria-hidden="true" />
      </button>

      {open && (
        <div
          role="menu"
          aria-label={`Estado: ${meta.label}`}
          className="absolute right-0 top-full z-20 mt-1 min-w-36 overflow-hidden rounded-lg border border-edge bg-surface-raised shadow-xl"
        >
          {error && (
            <div
              role="alert"
              className="border-b border-edge px-3 py-2 text-small text-status-error"
            >
              {error}
            </div>
          )}
          {options.map((option) => {
            const optionMeta = STATUS_META[option];
            const selected = option === status;
            return (
              <button
                key={option}
                type="button"
                role="menuitemradio"
                aria-checked={selected}
                disabled={loading}
                onClick={() => void handleSelect(option)}
                className={cn(
                  "flex w-full items-center gap-2 px-3 py-2 text-left text-small text-primary transition-colors",
                  "hover:bg-surface-hover hover:text-action focus-visible:outline-none",
                  "focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-action/50",
                  "disabled:cursor-not-allowed disabled:opacity-40",
                )}
              >
                <span
                  className={cn(
                    "h-2 w-2 shrink-0 rounded-full",
                    selected ? "bg-action" : "bg-muted",
                  )}
                  aria-hidden="true"
                />
                {optionMeta.label}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
