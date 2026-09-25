import type { MessageKey } from "@/i18n/messages";

export const API_BASE_URL = import.meta.env.VITE_API_URL ?? "";

export const VALID_SECTIONS = ["lore", "personajes", "referencias"] as const;
export type Section = (typeof VALID_SECTIONS)[number];

/** Section → catalogue key. Resolve with `t(...)` at render time so the label
 *  follows the active locale. */
export const SECTION_LABELS: Record<Section, MessageKey> = {
  lore: "section.lore",
  personajes: "section.personajes",
  referencias: "section.referencias",
};

/**
 * Sections offered as move destinations in the "Mover a…" modal (decision
 * (b) of the proposal: `referencias` is a valid backend section and must be
 * selectable as a destination). Mirrors VALID_SECTIONS now that Referencias
 * is navigable in the frontend.
 */
export const MOVE_DESTINATION_SECTIONS = [
  "lore",
  "personajes",
  "referencias",
] as const;
export type MoveDestinationSection =
  (typeof MOVE_DESTINATION_SECTIONS)[number];

/** Move-destination → catalogue key; resolve with `t(...)`. */
export const MOVE_DESTINATION_LABELS: Record<
  MoveDestinationSection,
  MessageKey
> = {
  lore: "section.lore",
  personajes: "section.personajes",
  referencias: "section.referencias",
};

export const ROUTES = {
  HOME: "/wiki",
  TALLER_HERRAMIENTAS: "/taller-herramientas",
  TALLER_MUNDO: "/taller-mundo",
  IDEAS: "/ideas",
  ONBOARDING: "/onboarding",
  ENTITY: "/wiki/:mundo/entity/*path",
  IMPORTER: "/wiki/:mundo/importer",
  EDITOR: "/wiki/:mundo/:section/*path",
  RELACIONES_CANON: "/taller-mundo/:mundo/relaciones-canon",
  WILDCARD: "*",
} as const;

export type NavAvailability = "available" | "teaser";

export interface NavLink {
  /** Catalogue key for the visible label; resolve with `t(...)`. */
  label: MessageKey;
  to: string;
  /** `available` surfaces navigate; `teaser` modules are future/paid and
   * render as non-actionable "Próximamente" items. */
  availability: NavAvailability;
  /** Rendered rightmost regardless of array order (Taller de Publicación). */
  rightmost?: boolean;
}

/** Catalogue key of the single generic future-module teaser. */
export const GENERIC_TEASER_KEY: MessageKey = "nav.soon";

/**
 * Core-only navigation contract (workshop-navigation spec): the free Core
 * exposes Taller de Mundo, Taller de Herramientas and Taller de Ideas as
 * `available` workshops. The Configuration Center is NOT a navbar item
 * anymore: it lives inside the Profile page ("Perfil" → "Centro de
 * Configuración" tab), with Telegram under "Integraciones" and the
 * legacy-folder migration under "Mundos"; there is no standalone
 * `/centro-configuracion` route. There is NO generic "Próximamente" teaser in
 * the Core navbar — a workshop only appears once it is a real, `available`
 * link; legacy narrative phases (Personajes/Escritura/Planificar/Revisar) are
 * never presented as Core workshops. Taller de Publicación stays absent until
 * it exists/becomes available; when enabled it is marked `rightmost` and
 * always renders last.
 */
export const NAV_LINKS: readonly NavLink[] = [
  { label: "nav.links.tallerHerramientas", to: ROUTES.TALLER_HERRAMIENTAS, availability: "available" },
  { label: "nav.links.tallerIdeas", to: ROUTES.IDEAS, availability: "available" },
  { label: "nav.links.tallerMundo", to: ROUTES.TALLER_MUNDO, availability: "available" },
];

/**
 * Operational Talleres (operational-taller-context spec OC-1): the selector,
 * the persistence guard and the tree derivation all key on exactly this list.
 * Herramientas is NEVER a member — it is the management/co-creation surface,
 * not a selectable runtime context. Skills with `taller` null or not in this
 * list land in the "Sin taller" bucket (OC-4).
 */
export const OPERATIONAL_TALLERES = ["Mundo", "Ideas"] as const;
export type OperationalTaller = (typeof OPERATIONAL_TALLERES)[number];

/** localStorage key persisting the active Taller (REQ-TRE-2). */
export const ACTIVE_TALLER_STORAGE_KEY = "demiurgos-active-taller";

/** localStorage key persisting the worlds that already received the companion
 *  first-activation latency notice (R-UI notice): JSON string-array of world
 *  names — the notice shows once per world, never again. */
export const COMPANION_LATENCY_NOTIFIED_KEY =
  "demiurgos-companion-latency-notified";

/**
 * Default active Taller shown before any explicit selection (REQ-TRE-1).
 * Value is an `OPERATIONAL_TALLERES` short key (matching the `taller` field a
 * skill carries), NOT a display label — the label is derived at render time.
 */
export const DEFAULT_TALLER: OperationalTaller = "Mundo";

/** Catalogue key for an Operational Taller display label; resolve with
 *  `t(...)` at render time. */
export const OPERATIONAL_TALLER_LABELS: Record<OperationalTaller, MessageKey> = {
  Mundo: "nav.links.tallerMundo",
  Ideas: "nav.links.tallerIdeas",
};

/** Membership guard (OC-1 S1): only operational talleres pass — Herramientas
 *  is a management surface, never a selectable runtime context. */
export function isOperationalTaller(
  taller: string | null | undefined,
): taller is OperationalTaller {
  return (
    taller != null &&
    (OPERATIONAL_TALLERES as readonly string[]).includes(taller)
  );
}

/** Catalogue keys for the placeholder toasts; resolve with `t(...)`. */
export const PLACEHOLDER_TOAST: MessageKey = "nav.placeholder";
export const AI_PLACEHOLDER_TOAST: MessageKey = "nav.placeholderAi";
export const PROFILE_PLACEHOLDER_TOAST: MessageKey = "nav.placeholderProfile";
