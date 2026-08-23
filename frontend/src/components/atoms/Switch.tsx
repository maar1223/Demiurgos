import { cn } from "@/lib/utils";

interface SwitchProps {
  checked: boolean;
  onChange: (checked: boolean) => void;
  "aria-label"?: string;
  "aria-labelledby"?: string;
  disabled?: boolean;
  className?: string;
}

/**
 * Accessible on/off switch (``role="switch"`` + keyboard support).
 *
 * The knob slides left (off) / right (on); the ON state uses the same
 * ``emerald`` track the rest of the app uses for "enabled". Used for the
 * importer's "analyze images" opt-out: right = with images, left = text-only.
 */
export function Switch({
  checked,
  onChange,
  disabled,
  className,
  ...rest
}: SwitchProps) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      onKeyDown={(e) => {
        if (e.key === " " || e.key === "Enter") {
          e.preventDefault();
          onChange(!checked);
        }
      }}
      className={cn(
        "relative inline-flex h-6 w-11 shrink-0 items-center rounded-full border transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-llamita/50",
        checked
          ? "border-emerald-500/40 bg-emerald-500"
          : "border-filio bg-cripta",
        disabled && "cursor-not-allowed opacity-50",
        className,
      )}
      {...rest}
    >
      <span
        className={cn(
          "inline-block h-4 w-4 transform rounded-full bg-white shadow transition-transform",
          checked ? "translate-x-6" : "translate-x-1",
        )}
      />
    </button>
  );
}
