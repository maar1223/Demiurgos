import { FormEvent, useEffect, useState } from "react";
import { getLocale } from "@/api/config";
import { submitStep0 } from "@/api/onboarding";
import { ApiError, type LocaleInput, type OnboardingStatus } from "@/api/types";
import { Button } from "@/components/atoms/Button";
import { ErrorBanner } from "@/components/organisms/ErrorBanner";

const LANGUAGE_OPTIONS = [
  { value: "es", label: "Español" },
  { value: "en", label: "English" },
];

const COMMON_TIMEZONES = [
  "UTC",
  "America/Argentina/Buenos_Aires",
  "America/Mexico_City",
  "America/New_York",
  "Europe/Madrid",
  "Asia/Kolkata",
  "Asia/Shanghai",
];

/** A gated write that answers 401 means the session expired (fail closed). */
export function authHint(error: unknown): string | null {
  if (error instanceof ApiError && error.status === 401) {
    return "La sesión expiró. Inicia sesión e intenta de nuevo.";
  }
  return null;
}

interface LocaleFormProps {
  /** Called after a successful save, with the server-authoritative status. */
  onSaved?: (next: OnboardingStatus) => void;
  /** External busy state that also disables submission. */
  busy?: boolean;
  /** Idle submit label — the onboarding step says "Continuar", the inline
   *  Preferencias form says "Guardar". */
  submitLabel?: string;
}

/**
 * The G7/OC3 locale form (REQ-PIA-12) — six independent fields persisted by
 * POST /api/onboarding/step0. Shared by Onboarding step 0 and the inline
 * Preferencias section so the field states live in exactly one place. The
 * saved locale (GET /api/locale) is loaded on mount and prefills the fields;
 * an unavailable read fails open to the defaults so the form stays usable.
 * Each consumer supplies its own heading and card chrome.
 */
export function LocaleForm({
  onSaved,
  busy = false,
  submitLabel = "Guardar",
}: LocaleFormProps) {
  const [uiLang, setUiLang] = useState("es");
  const [conversationLang, setConversationLang] = useState("es");
  const [contentLang, setContentLang] = useState("es");
  const [region, setRegion] = useState("");
  const [regionExplicit, setRegionExplicit] = useState(false);
  const [timezone, setTimezone] = useState("UTC");
  const [saving, setSaving] = useState(false);
  const [writeError, setWriteError] = useState<unknown>(null);

  useEffect(() => {
    let alive = true;
    void getLocale()
      .then((locale) => {
        if (!alive) return;
        setUiLang(locale.ui);
        setConversationLang(locale.conversation);
        setContentLang(locale.content);
        setRegion(locale.region ?? "");
        setRegionExplicit(locale.region_explicit);
        setTimezone(locale.iana_timezone);
      })
      .catch(() => {
        // Fail open to the defaults: a failed locale read must not block the form.
      });
    return () => {
      alive = false;
    };
  }, []);

  const handleSubmit = (event: FormEvent) => {
    event.preventDefault();
    setSaving(true);
    setWriteError(null);
    const locale: LocaleInput = {
      ui: uiLang,
      conversation: conversationLang,
      content: contentLang,
      region: region.trim() ? region.trim() : null,
      region_explicit: regionExplicit,
      iana_timezone: timezone.trim(),
    };
    void submitStep0(locale)
      .then((next) => {
        setSaving(false);
        onSaved?.(next);
      })
      .catch((cause: unknown) => {
        setWriteError(cause);
        setSaving(false);
      });
  };

  const hint = authHint(writeError);

  return (
    <form onSubmit={handleSubmit}>
      <p className="mt-1 text-small text-muted">
        Cada lenguaje se configura de forma independiente; la región solo
        sugiere valores y nunca se aplica en silencio.
      </p>

      <div className="mt-5 grid gap-4">
        <label htmlFor="locale-ui-lang" className="flex flex-col gap-1 text-small text-primary">
          Idioma de la interfaz
          <select
            id="locale-ui-lang"
            value={uiLang}
            onChange={(e) => setUiLang(e.target.value)}
            className="rounded-lg border border-edge bg-surface px-3 py-2 text-body text-primary"
          >
            {LANGUAGE_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>
        </label>

        <label htmlFor="locale-conversation-lang" className="flex flex-col gap-1 text-small text-primary">
          Idioma de conversación (asistente)
          <select
            id="locale-conversation-lang"
            value={conversationLang}
            onChange={(e) => setConversationLang(e.target.value)}
            className="rounded-lg border border-edge bg-surface px-3 py-2 text-body text-primary"
          >
            {LANGUAGE_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>
        </label>

        <label htmlFor="locale-content-lang" className="flex flex-col gap-1 text-small text-primary">
          Idioma de contenido (prosa del mundo)
          <select
            id="locale-content-lang"
            value={contentLang}
            onChange={(e) => setContentLang(e.target.value)}
            className="rounded-lg border border-edge bg-surface px-3 py-2 text-body text-primary"
          >
            {LANGUAGE_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>
        </label>

        <label htmlFor="locale-region" className="flex flex-col gap-1 text-small text-primary">
          Región (opcional; sugiere valores, nunca impone dialecto)
          <input
            id="locale-region"
            value={region}
            onChange={(e) => setRegion(e.target.value)}
            className="rounded-lg border border-edge bg-surface px-3 py-2 text-body text-primary"
            placeholder="AR, MX, US…"
          />
        </label>

        <label className="flex items-center gap-2 text-small text-primary">
          <input
            type="checkbox"
            checked={regionExplicit}
            onChange={(e) => setRegionExplicit(e.target.checked)}
            className="h-4 w-4"
          />
          Confirmo la región de forma explícita (override)
        </label>

        <label htmlFor="locale-timezone" className="flex flex-col gap-1 text-small text-primary">
          Zona horaria (identificador IANA; los timestamps se guardan en UTC)
          <input
            id="locale-timezone"
            list="locale-timezones"
            value={timezone}
            onChange={(e) => setTimezone(e.target.value)}
            className="rounded-lg border border-edge bg-surface px-3 py-2 text-body text-primary"
          />
          <datalist id="locale-timezones">
            {COMMON_TIMEZONES.map((tz) => (
              <option key={tz} value={tz} />
            ))}
          </datalist>
        </label>
      </div>

      {hint && <ErrorBanner message={hint} onRetry={() => setWriteError(null)} className="mt-4" />}

      <div className="mt-6 flex items-center justify-end">
        <Button type="submit" disabled={busy || saving}>
          {busy || saving ? "Guardando…" : submitLabel}
        </Button>
      </div>
    </form>
  );
}