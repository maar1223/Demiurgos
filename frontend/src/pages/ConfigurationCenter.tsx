import type { CardState, ReadinessSnapshot } from "@/api/types";

/**
 * Configuration Center (OC12) — shared surface contract.
 *
 * The standalone `/centro-configuracion` page no longer exists
 * (nav-restructure decision): the configuration surface lives inside the
 * Profile (`/perfil` → "Centro de Configuración" tab, with the legacy-folder
 * migration under "Mundos" and the idea-capture wizard — the single Telegram
 * surface — under "Integraciones"). This module stays as the single shared
 * exporter of the card definitions, the honest state helpers and the panel
 * that was exclusive to the standalone page, so the Profile tabs and this
 * module never drift.
 */

/** Panel relocated from the standalone page (ONB-4.3, WU-4c2). */
export { MigrationPanel } from "@/components/organisms/MigrationPanel";

export const STATE_META: Record<CardState, { label: string; badge: "default" | "success" | "warning" | "error" }> = {
  pending: { label: "Pendiente", badge: "default" },
  configured: { label: "Configurado", badge: "success" },
  requires_connection: { label: "Requiere conexión", badge: "warning" },
  error: { label: "Error", badge: "error" },
};

/**
 * Capabilities without a dedicated contract (ONB-3.1/ONB-3.5): their cards
 * can NEVER render as "Configurado", because only their dedicated contracts
 * may mark them configured. Defense in depth: even if a stale/buggy backend
 * reports "configured" for one of these keys, the UI forces the honest
 * pending state instead of overstating readiness.
 *
 * - backup: remote capability whose dedicated contract does not exist in
 *   this change (Drive consent stays separate from Google identity).
 * - import (ONB-3.5): the importer is a separate SDD; its card exposes
 *   entry/pending only and must never claim an import happened.
 *
 * NOTE (auth-google-vault R-ID1): identity is intentionally NOT in this set
 * anymore — its dedicated backend contract (`identity_configured` in
 * readiness.py) proves the "configured" state when DEMIURGOS_AUTH_MODE=google
 * AND GOOGLE_CLIENT_ID is set, so the card may truthfully render configured.
 *
 * NOTE (WU-3b1): telegram is intentionally NOT in this set either — ONB-3.3
 * gave it a dedicated backend contract whose `configured` state is proven by
 * a real server-side getMe check, so its card may truthfully render
 * configured.
 */
export const DEFERRED_CARD_KEYS: ReadonlySet<string> = new Set(["backup", "import"]);

/** Essential local readiness badges (OC11/OC21): World + local editor. */
export const ESSENTIAL_BADGES: { key: string; title: string }[] = [
  { key: "world", title: "Mundos" },
  { key: "editor", title: "Editor local" },
];

/** Remote capability labels shown in the offline card breakdown (OC5). */
export const REMOTE_LABELS: Record<string, string> = {
  identity: "Identidad",
  telegram: "Telegram",
  backup: "Respaldo",
  assistant: "Asistente (IA)",
};

interface CardAction {
  label: string;
  to: string;
}

interface CardDef {
  key: string;
  title: string;
  description: string;
  action: CardAction | null;
}

export const CARD_DEFS: CardDef[] = [
  { key: "identity", title: "Identidad", description: "Cuenta local / Google: revalidación online y recuperación autorizada.", action: { label: "Ir a Perfil", to: "/perfil" } },
  { key: "assistant", title: "IA texto y visión", description: "Modelo principal del Asistente (multimodal, validado).", action: { label: "Configurar", to: "/perfil" } },
  { key: "telegram", title: "Telegram", description: "Canal de mensajería para captura de ideas.", action: null },
  { key: "backup", title: "Respaldo y restauración", description: "Google Drive / rclone: respaldo y restauración, con consentimiento separado de la identidad.", action: null },
  { key: "locale", title: "Idioma, región y zona horaria", description: "Localización del paso 0, reconfigurable por separado.", action: { label: "Configurar", to: "/onboarding?step=step0" } },
  { key: "world", title: "Mundos", description: "Crear, importar o restaurar. Entrada al Taller de Mundo.", action: { label: "Abrir Taller de Mundo", to: "/taller-mundo" } },
  { key: "offline", title: "Offline / dispositivo", description: "Núcleo local (editor, ideas, grafo) sin conexión.", action: null },
  { key: "import", title: "Importar mundo", description: "Importar contenido a un mundo. El importador está operativo: iniciá una nueva importación o retomá una anterior desde el Taller de Mundo.", action: { label: "Ir al Taller de Mundo", to: "/taller-mundo" } },
];

/**
 * Honest per-card state (ONB-3.1/ONB-3.5): capabilities without a dedicated
 * contract can never be "configured" in this slice — their dedicated
 * contracts are the only path to configured, and none exists yet. Even if
 * the backend reports "configured" for such a key (stale/buggy state), the
 * UI renders the truthful pending state.
 *
 * Exported (pure) so the Profile page's configuration tab reuses the exact
 * same anti-overstatement guard instead of duplicating it.
 */
export function cardState(cards: Record<string, CardState>, key: string): CardState {
  const raw = cards[key] ?? "pending";
  if (DEFERRED_CARD_KEYS.has(key) && raw === "configured") return "pending";
  return raw as CardState;
}

/**
 * Per-card visible label. The assistant badge (OC19) reports
 * "Pendiente / no apto" when no multimodal model has passed the three
 * proofs — it never claims configured in that case.
 */
export function cardLabel(key: string, state: CardState): string {
  if (key === "assistant" && state === "pending") return "Pendiente / no apto";
  return STATE_META[state].label;
}

/** Essential World + editor badge truth (OC11/OC21), shared with Profile. */
export function essentialBadgeFor(
  readiness: ReadinessSnapshot | null,
  cards: Record<string, CardState>,
  key: string,
): { label: string; badge: "default" | "success" | "error" } {
  if (key === "editor") {
    return readiness?.local_editor.ok
      ? { label: "Listo", badge: "success" }
      : { label: "No disponible", badge: "error" };
  }
  return cardState(cards, "world") === "configured"
    ? { label: "Listo", badge: "success" }
    : { label: "Pendiente", badge: "default" };
}