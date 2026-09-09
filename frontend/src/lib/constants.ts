export const API_BASE_URL = import.meta.env.VITE_API_URL ?? "";

export const VALID_SECTIONS = ["lore", "personajes", "referencias"] as const;
export type Section = (typeof VALID_SECTIONS)[number];

export const SECTION_LABELS: Record<Section, string> = {
  lore: "Lore",
  personajes: "Personajes",
  referencias: "Referencias",
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

export const MOVE_DESTINATION_LABELS: Record<MoveDestinationSection, string> = {
  lore: "Lore",
  personajes: "Personajes",
  referencias: "Referencias",
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
  label: string;
  to: string;
  /** `available` surfaces navigate; `teaser` modules are future/paid and
   * render as non-actionable "Próximamente" items. */
  availability: NavAvailability;
  /** Rendered rightmost regardless of array order (Taller de Publicación). */
  rightmost?: boolean;
}

/** Label of the single generic future-module teaser in the Core navbar. */
export const GENERIC_TEASER_LABEL = "Próximamente" as const;

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
  { label: "Taller de Herramientas", to: ROUTES.TALLER_HERRAMIENTAS, availability: "available" },
  { label: "Taller de Ideas", to: ROUTES.IDEAS, availability: "available" },
  { label: "Taller de Mundo", to: ROUTES.TALLER_MUNDO, availability: "available" },
];

/**
 * Curated Core Talleres (taller-selector-tree-states spec REQ-TRE-1): the
 * selector exposes exactly these; skills with `taller` null or not in this
 * list land in the "Sin taller" bucket.
 */
export const CORE_TALLERES = ["Herramientas", "Mundo", "Ideas"] as const;
export type CoreTaller = (typeof CORE_TALLERES)[number];

/** localStorage key persisting the active Taller (REQ-TRE-2). */
export const ACTIVE_TALLER_STORAGE_KEY = "demiurgos-active-taller";

/** localStorage key persisting the worlds that already received the companion
 *  first-activation latency notice (R-UI notice): JSON string-array of world
 *  names — the notice shows once per world, never again. */
export const COMPANION_LATENCY_NOTIFIED_KEY =
  "demiurgos-companion-latency-notified";

/**
 * Default active Taller shown before any explicit selection (REQ-TRE-1).
 * Value is a `CORE_TALLERES` short key (matching the `taller` field a skill
 * carries), NOT a display label — the label is derived at render time.
 */
export const DEFAULT_TALLER: CoreTaller = "Herramientas";

/** Human-readable label for a Core Taller key (display-only). */
export const CORE_TALLER_LABELS: Record<CoreTaller, string> = {
  Herramientas: "Taller de Herramientas",
  Mundo: "Taller de Mundo",
  Ideas: "Taller de Ideas",
};

export const PLACEHOLDER_TOAST =
  "Módulo en desarrollo — próximamente" as const;
export const AI_PLACEHOLDER_TOAST =
  "Asistente IA — próximamente" as const;
export const PROFILE_PLACEHOLDER_TOAST =
  "Perfil — próximamente" as const;
