import {
  forwardRef,
  useEffect,
  useRef,
  useState,
  type ChangeEvent,
  type InputHTMLAttributes,
} from "react";
import { cn } from "@/lib/utils";

export interface SecretInputProps
  extends Omit<InputHTMLAttributes<HTMLInputElement>, "type"> {
  /** Show the copy button next to the reveal toggle. Default false. */
  copyable?: boolean;
  /** Accessible label for the reveal toggle button. Defaults to the
   *  state-derived "Mostrar"/"Ocultar". */
  toggleLabel?: string;
  /** Called when copying to the clipboard fails (e.g. clipboard unavailable). */
  onCopyError?: () => void;
}

const actionButtonClass =
  "shrink-0 rounded-md border border-edge bg-surface-raised px-2 py-1.5 " +
  "text-small text-icon-muted hover:text-primary " +
  "disabled:cursor-not-allowed disabled:opacity-50";

/**
 * A secret field (password / API key / token) with a Mostrar/Ocultar reveal
 * toggle and an optional Copiar button. Works both controlled (value +
 * onChange) and uncontrolled (like a plain input). The inner <input> is
 * exposed through forwardRef so callers can keep reading and clearing it
 * directly (e.g. the assistant panel's clear()/save()).
 */
export const SecretInput = forwardRef<HTMLInputElement, SecretInputProps>(
  function SecretInput(
    {
      copyable = false,
      toggleLabel,
      onCopyError,
      value,
      onChange,
      disabled,
      className,
      ...rest
    },
    ref,
  ) {
    const [revealed, setRevealed] = useState(false);
    const [copied, setCopied] = useState(false);
    // Uncontrolled mode only: tracks whether the field has content so the
    // action buttons can disable themselves on an empty field.
    const [typedValue, setTypedValue] = useState("");
    const inputRef = useRef<HTMLInputElement | null>(null);
    const copyTimer = useRef<number | undefined>(undefined);

    const controlled = value !== undefined;
    const hasValue = controlled ? value !== "" : typedValue !== "";

    // Uncontrolled mode: re-sync with the DOM value on every render so an
    // external clear through the ref (e.g. clear()/save() in the assistant
    // panel) also updates the button states and hides the revealed value.
    // Intentionally runs on every render (no dependency array).
    useEffect(() => {
      if (controlled) return;
      const current = inputRef.current?.value ?? "";
      setTypedValue((prev) => (prev === current ? prev : current));
      if (current === "" && revealed) setRevealed(false);
    });

    // Controlled mode: hide the value again once the field is emptied
    // (e.g. after a successful save).
    useEffect(() => {
      if (controlled && value === "" && revealed) setRevealed(false);
    }, [controlled, value, revealed]);

    const mergeRefs = (node: HTMLInputElement | null) => {
      inputRef.current = node;
      if (typeof ref === "function") {
        ref(node);
      } else if (ref) {
        ref.current = node;
      }
    };

    const handleChange = (event: ChangeEvent<HTMLInputElement>) => {
      if (!controlled) setTypedValue(event.target.value);
      if (copied) setCopied(false);
      onChange?.(event);
    };

    const handleCopy = async () => {
      const current = controlled ? String(value) : (inputRef.current?.value ?? "");
      if (!current) return;
      try {
        await navigator.clipboard.writeText(current);
        setCopied(true);
        window.clearTimeout(copyTimer.current);
        copyTimer.current = window.setTimeout(() => setCopied(false), 1500);
      } catch {
        onCopyError?.();
      }
    };

    const canAct = hasValue && !disabled;
    const revealLabel = toggleLabel ?? (revealed ? "Ocultar" : "Mostrar");

    return (
      <div className="flex items-center gap-2">
        <input
          {...rest}
          ref={mergeRefs}
          type={revealed ? "text" : "password"}
          value={value}
          onChange={handleChange}
          disabled={disabled}
          className={cn("min-w-0 flex-1", className)}
        />
        <button
          type="button"
          onClick={() => setRevealed((prev) => !prev)}
          disabled={!canAct}
          aria-label={revealLabel}
          className={actionButtonClass}
        >
          {revealed ? "Ocultar" : "Mostrar"}
        </button>
        {copyable && (
          <button
            type="button"
            onClick={() => void handleCopy()}
            disabled={!canAct}
            aria-label="Copiar"
            className={actionButtonClass}
          >
            {copied ? "Copiado" : "Copiar"}
          </button>
        )}
      </div>
    );
  },
);

SecretInput.displayName = "SecretInput";