export const API_BASE_URL = import.meta.env.VITE_API_URL ?? "";

export const VALID_SECTIONS = ["lore", "personajes", "sagas"] as const;
export type Section = (typeof VALID_SECTIONS)[number];

export const SECTION_LABELS: Record<Section, string> = {
  lore: "Lore",
  personajes: "Personajes",
  sagas: "Sagas",
};

/**
 * Sections offered as move destinations in the "Mover a…" modal (decision
 * (b) of the proposal: `referencias` is a valid backend section and must be
 * selectable as a destination, even though it is NOT navigable in the
 * frontend — hence this constant is deliberately SEPARATE from
 * VALID_SECTIONS, which keeps driving the sidebar tabs and routing.
 */
export const MOVE_DESTINATION_SECTIONS = [
  "lore",
  "personajes",
  "sagas",
  "referencias",
] as const;
export type MoveDestinationSection =
  (typeof MOVE_DESTINATION_SECTIONS)[number];

export const MOVE_DESTINATION_LABELS: Record<MoveDestinationSection, string> = {
  lore: "Lore",
  personajes: "Personajes",
  sagas: "Sagas",
  referencias: "Referencias",
};

export const ROUTES = {
  HOME: "/wiki",
  TALLER_HERRAMIENTAS: "/taller-herramientas",
  TALLER_MUNDO: "/taller-mundo",
  ONBOARDING: "/onboarding",
  CENTRO_CONFIGURACION: "/centro-configuracion",
  ENTITY: "/wiki/:mundo/entity/*path",
  IMPORTER: "/wiki/:mundo/importer",
  EDITOR: "/wiki/:mundo/:section/*path",
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
 * exposes Taller de Mundo and Taller de Herramientas as `available` workshops,
 * plus the permanent Configuration Center (OC12). Every future/paid surface
 * collapses into ONE generic non-actionable "Próximamente" teaser — legacy
 * narrative phases (Personajes/Escritura/Planificar/Revisar) are never
 * presented as Core workshops. Taller de Publicación stays absent until it
 * exists/becomes available; when enabled it is marked `rightmost` and always
 * renders last.
 */
export const NAV_LINKS: readonly NavLink[] = [
  { label: "Taller de Herramientas", to: ROUTES.TALLER_HERRAMIENTAS, availability: "available" },
  { label: "Taller de Mundo", to: ROUTES.TALLER_MUNDO, availability: "available" },
  { label: "Centro de Configuración", to: ROUTES.CENTRO_CONFIGURACION, availability: "available" },
  { label: GENERIC_TEASER_LABEL, to: "#", availability: "teaser" },
];

export const PLACEHOLDER_TOAST =
  "Módulo en desarrollo — próximamente" as const;
export const AI_PLACEHOLDER_TOAST =
  "Asistente IA — próximamente" as const;
export const PROFILE_PLACEHOLDER_TOAST =
  "Perfil — próximamente" as const;
