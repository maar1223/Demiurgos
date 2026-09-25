import { FormEvent, useEffect, useMemo, useState } from "react";
import { getLocale } from "@/api/config";
import { submitStep0 } from "@/api/onboarding";
import { ApiError, type LocaleInput, type OnboardingStatus } from "@/api/types";
import { Button } from "@/components/atoms/Button";
import { ErrorBanner } from "@/components/organisms/ErrorBanner";
import { useLocale } from "@/i18n/LocaleProvider";
import type { TFunction } from "@/i18n/messages";

const LANGUAGE_OPTIONS = [
  { value: "es", label: "Español" },
  { value: "en", label: "English" },
];

/**
 * Curated fallback used only when the runtime lacks
 * `Intl.supportedValuesOf("timeZone")`, so the control never regresses to a
 * free-text field. The primary source is the full IANA set (~400 zones).
 */
const FALLBACK_TIMEZONES = [
  "UTC",
  "Africa/Cairo",
  "Africa/Johannesburg",
  "America/Argentina/Buenos_Aires",
  "America/Bogota",
  "America/Chicago",
  "America/Los_Angeles",
  "America/Mexico_City",
  "America/New_York",
  "America/Sao_Paulo",
  "Asia/Dubai",
  "Asia/Kolkata",
  "Asia/Shanghai",
  "Asia/Tokyo",
  "Atlantic/Canary",
  "Australia/Sydney",
  "Europe/Berlin",
  "Europe/Lisbon",
  "Europe/London",
  "Europe/Madrid",
  "Europe/Paris",
  "Pacific/Auckland",
];

/** Catch-all group for zones without an area segment (e.g. UTC). */
const OTHER_REGION = "Otros";

/** Last IANA path segment, de-slugged: `Buenos_Aires` → `Buenos Aires`. */
function timeZoneCity(zone: string): string {
  const segment = zone.split("/").pop() ?? zone;
  return segment.replace(/_/g, " ");
}

function timeZoneRegion(zone: string): string {
  const slash = zone.indexOf("/");
  return slash === -1 ? OTHER_REGION : zone.slice(0, slash);
}

/** `Europe/Madrid` → `Europe/Madrid - Madrid`; a cityless `UTC` stays `UTC`. */
function timeZoneLabel(zone: string): string {
  const city = timeZoneCity(zone);
  return city === zone ? zone : `${zone} - ${city}`;
}

function supportedTimeZones(): string[] {
  const intl = Intl as typeof Intl & {
    supportedValuesOf?: (key: "timeZone") => string[];
  };
  if (typeof intl.supportedValuesOf === "function") {
    try {
      const zones = intl.supportedValuesOf("timeZone");
      if (zones.length > 0) return zones;
    } catch {
      // Some engines expose the method but throw; fall through to the list.
    }
  }
  return FALLBACK_TIMEZONES;
}

interface TimeZoneGroup {
  region: string;
  zones: string[];
}

/**
 * Groups the ~400 IANA zones by area and sorts them so the option order never
 * shifts between renders. A stored value the runtime does not list (UTC, a
 * retired alias) is injected so it stays selectable and selected instead of
 * being silently dropped.
 */
function buildTimeZoneGroups(current: string): TimeZoneGroup[] {
  const zones = new Set(supportedTimeZones());
  const stored = current.trim();
  if (stored) zones.add(stored);

  const byRegion = new Map<string, string[]>();
  for (const zone of [...zones].sort()) {
    const region = timeZoneRegion(zone);
    const list = byRegion.get(region);
    if (list) list.push(zone);
    else byRegion.set(region, [zone]);
  }

  return [...byRegion.entries()]
    .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))
    .map(([region, regionZones]) => ({ region, zones: regionZones }));
}

/** A gated write that answers 401 means the session expired (fail closed). */
export function authHint(error: unknown, t: TFunction): string | null {
  if (error instanceof ApiError && error.status === 401) {
    return t("error.sessionExpired");
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
 *
 * AD-7: the conversation and content selects lead with an "inherit" option
 * (neutral "Igual que la interfaz" / "Same as interface"). Selecting it
 * persists `*_explicit: false` plus the current `ui` value, so the domain
 * follows the interface; any other selection persists an explicit override.
 * After a successful save the provider refreshes the backend-authoritative
 * locale so the whole chrome follows the selection instantly (UI-REQ-3).
 */
export function LocaleForm({
  onSaved,
  busy = false,
  submitLabel,
}: LocaleFormProps) {
  const { t, refreshLocale } = useLocale();
  const [uiLang, setUiLang] = useState("es");
  // "" means "inherit" (AD-7): the persisted explicit flag decides whether the
  // raw domain value is stored and honored.
  const [conversationLang, setConversationLang] = useState("");
  const [contentLang, setContentLang] = useState("");
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
        setConversationLang(locale.conversation_explicit ? locale.conversation : "");
        setContentLang(locale.content_explicit ? locale.content : "");
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

  // Rebuilt when the value changes so a stored zone the runtime does not
  // list keeps its own option and stays selected.
  const timeZoneGroups = useMemo(() => buildTimeZoneGroups(timezone), [timezone]);

  const handleSubmit = (event: FormEvent) => {
    event.preventDefault();
    setSaving(true);
    setWriteError(null);
    const locale: LocaleInput = {
      ui: uiLang,
      // AD-7: an "inherit" selection resolves to the ui value with explicit=false.
      conversation: conversationLang === "" ? uiLang : conversationLang,
      content: contentLang === "" ? uiLang : contentLang,
      conversation_explicit: conversationLang !== "",
      content_explicit: contentLang !== "",
      region: region.trim() ? region.trim() : null,
      region_explicit: regionExplicit,
      iana_timezone: timezone.trim(),
    };
    void submitStep0(locale)
      .then((next) => {
        setSaving(false);
        // Re-read the backend-authoritative locale so every chrome consumer
        // follows the saved selection without a reload (UI-REQ-3/4).
        void refreshLocale();
        onSaved?.(next);
      })
      .catch((cause: unknown) => {
        setWriteError(cause);
        setSaving(false);
      });
  };

  const hint = authHint(writeError, t);

  return (
    <form onSubmit={handleSubmit}>
      <p className="mt-1 text-small text-muted">{t("locale.form.intro")}</p>

      <div className="mt-5 grid gap-4">
        <label htmlFor="locale-ui-lang" className="flex flex-col gap-1 text-small text-primary">
          {t("locale.ui")}
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
          {t("locale.conversation")}
          <select
            id="locale-conversation-lang"
            value={conversationLang}
            onChange={(e) => setConversationLang(e.target.value)}
            className="rounded-lg border border-edge bg-surface px-3 py-2 text-body text-primary"
          >
            <option value="">{t("locale.inherit")}</option>
            {LANGUAGE_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>
        </label>

        <label htmlFor="locale-content-lang" className="flex flex-col gap-1 text-small text-primary">
          {t("locale.content")}
          <select
            id="locale-content-lang"
            value={contentLang}
            onChange={(e) => setContentLang(e.target.value)}
            className="rounded-lg border border-edge bg-surface px-3 py-2 text-body text-primary"
          >
            <option value="">{t("locale.inherit")}</option>
            {LANGUAGE_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>
        </label>

        <label htmlFor="locale-region" className="flex flex-col gap-1 text-small text-primary">
          {t("locale.region")}
          <input
            id="locale-region"
            value={region}
            onChange={(e) => setRegion(e.target.value)}
            className="rounded-lg border border-edge bg-surface px-3 py-2 text-body text-primary"
            placeholder={t("locale.regionPlaceholder")}
          />
        </label>

        <label className="flex items-center gap-2 text-small text-primary">
          <input
            type="checkbox"
            checked={regionExplicit}
            onChange={(e) => setRegionExplicit(e.target.checked)}
            className="h-4 w-4"
          />
          {t("locale.regionExplicit")}
        </label>

        <label htmlFor="locale-timezone" className="flex flex-col gap-1 text-small text-primary">
          {t("locale.timezone")}
          <select
            id="locale-timezone"
            value={timezone}
            onChange={(e) => setTimezone(e.target.value)}
            className="rounded-lg border border-edge bg-surface px-3 py-2 text-body text-primary"
          >
            {timeZoneGroups.map((group) => (
              <optgroup key={group.region} label={group.region}>
                {group.zones.map((zone) => (
                  <option key={zone} value={zone}>
                    {timeZoneLabel(zone)}
                  </option>
                ))}
              </optgroup>
            ))}
          </select>
        </label>
      </div>

      {hint && <ErrorBanner message={hint} onRetry={() => setWriteError(null)} className="mt-4" />}

      <div className="mt-6 flex items-center justify-end">
        <Button type="submit" disabled={busy || saving}>
          {busy || saving ? t("common.saving") : (submitLabel ?? t("common.save"))}
        </Button>
      </div>
    </form>
  );
}