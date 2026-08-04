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
  ENTITY: "/wiki/:mundo/entity/*path",
  EDITOR: "/wiki/:mundo/:section/*path",
  WILDCARD: "*",
} as const;

export const NAV_LINKS = [
  { label: "Wiki", to: "/wiki", active: true },
  { label: "Personajes", to: "#", active: false },
  { label: "Escritura", to: "#", active: false },
  { label: "Planificar", to: "#", active: false },
  { label: "Revisar", to: "#", active: false },
] as const;

export const PLACEHOLDER_TOAST =
  "Módulo en desarrollo — próximamente" as const;
export const AI_PLACEHOLDER_TOAST =
  "Asistente IA — próximamente" as const;
export const PROFILE_PLACEHOLDER_TOAST =
  "Perfil — próximamente" as const;
