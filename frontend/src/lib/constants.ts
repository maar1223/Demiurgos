export const API_BASE_URL = import.meta.env.VITE_API_URL ?? "";

export const VALID_SECTIONS = ["lore", "personajes", "sagas"] as const;
export type Section = (typeof VALID_SECTIONS)[number];

export const ROUTES = {
  HOME: "/wiki",
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
