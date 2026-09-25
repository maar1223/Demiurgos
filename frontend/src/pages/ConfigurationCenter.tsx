import type { CardState, ReadinessSnapshot } from "@/api/types";
import type { MessageKey, TFunction } from "@/i18n/messages";

/**
 * Configuration Center (OC12) — shared surface contract.
 *
 * The standalone `/centro-configuracion` page no longer exists
 * (nav-restructure decision): the configuration surface lives inside the
 * Profile (`/perfil` → "Preferencias", which hosts the inline locale form —
 * REQ-PIA-12), the legacy-folder migration lives under "Mundos", and the
 * idea-capture wizard — the single Telegram surface — lives under
 * "Conexiones". This module stays as the single shared exporter of the card
 * definitions, the honest state helpers and the panel that was exclusive to
 * the standalone page, so the Profile sections and this module never drift.
 */

/** Panel relocated from the standalone page (ONB-4.3, WU-4c2). */
export { MigrationPanel } from "@/components/organisms/MigrationPanel";

export const STATE_META: Record<CardState, { labelKey: MessageKey; badge: "default" | "success" | "warning" | "error" }> = {
  pending: { labelKey: "configCenter.state.pending", badge: "default" },
  configured: { labelKey: "configCenter.state.configured", badge: "success" },
  requires_connection: { labelKey: "configCenter.state.requiresConnection", badge: "warning" },
  error: { labelKey: "configCenter.state.error", badge: "error" },
};

/**
 * Capabilities without a dedicated contract (ONB-3.1/ONB-3.5): their cards
 * can NEVER render as "Configurado", because only their dedicated contracts
 * may mark them configured. Defense in depth: even if a stale/buggy backend
 * reports "configured" for one of these keys, the UI forces the honest
 * pending state instead of overstating readiness.
 *
 * - import (ONB-3.5): the importer is a separate SDD; its card exposes
 *   entry/pending only and must never claim an import happened.
 *
 * NOTE (auth-vault-credentials R-ID1): identity is intentionally NOT in this
 * set anymore — its dedicated backend contract (`identity_configured` in
 * readiness.py) proves the "configured" state when a local account exists
 * (or credentials mode is active), so the card may truthfully render
 * configured.
 *
 * NOTE (WU-3b1): telegram is intentionally NOT in this set either — ONB-3.3
 * gave it a dedicated backend contract whose `configured` state is proven by
 * a real server-side getMe check, so its card may truthfully render
 * configured.
 *
 * NOTE (portable-data-root-drive-backup, REQ-CC-2/SC-CC-2.2): `backup` left
 * this set — the modern backup/restore flow is delivered by this change and
 * `backup_state()` derives the card from REAL local evidence (a persisted
 * folder AND a recorded successful local write). The BackupSection still
 * refuses to render "Configurado" without that evidence.
 */
export const DEFERRED_CARD_KEYS: ReadonlySet<string> = new Set(["import"]);

/** Essential local readiness badges (OC11/OC21): World + local editor.
 *  No longer rendered by the Profile Preferencias surface (product-owner
 *  decision): kept exported for the shared contract tests. */
export const ESSENTIAL_BADGES: { key: string; titleKey: MessageKey }[] = [
  { key: "world", titleKey: "configCenter.essential.world" },
  { key: "editor", titleKey: "configCenter.essential.editor" },
];

interface CardAction {
  labelKey: MessageKey;
  to: string;
}

interface CardDef {
  key: string;
  titleKey: MessageKey;
  descriptionKey: MessageKey;
  action: CardAction | null;
}

export const CARD_DEFS: CardDef[] = [
  { key: "identity", titleKey: "configCenter.card.identity.title", descriptionKey: "configCenter.card.identity.description", action: { labelKey: "configCenter.card.identity.action", to: "/perfil" } },
  { key: "assistant", titleKey: "configCenter.card.assistant.title", descriptionKey: "configCenter.card.assistant.description", action: { labelKey: "configCenter.card.assistant.action", to: "/perfil" } },
  { key: "telegram", titleKey: "configCenter.card.telegram.title", descriptionKey: "configCenter.card.telegram.description", action: null },
  { key: "locale", titleKey: "configCenter.card.locale.title", descriptionKey: "configCenter.card.locale.description", action: { labelKey: "configCenter.card.locale.action", to: "/perfil?tab=preferencias" } },
  { key: "world", titleKey: "configCenter.card.world.title", descriptionKey: "configCenter.card.world.description", action: { labelKey: "configCenter.card.world.action", to: "/taller-mundo" } },
  { key: "import", titleKey: "configCenter.card.import.title", descriptionKey: "configCenter.card.import.description", action: { labelKey: "configCenter.card.import.action", to: "/taller-mundo" } },
];

/**
 * Honest per-card state (ONB-3.1/ONB-3.5). Only the keys still in
 * {@link DEFERRED_CARD_KEYS} are forced to `pending`: their dedicated
 * contracts are the only path to configured, and none exists yet. Even if
 * the backend reports "configured" for such a key (stale/buggy state), the
 * UI renders the truthful pending state.
 *
 * A key that left the deferred set — `backup` after
 * portable-data-root-drive-backup — is no longer forced: its dedicated
 * contract (`backup_state()` in readiness.py) proves configured from real
 * local evidence, so the gate must not downgrade a truthful claim. The
 * BackupSection independently re-checks that evidence before showing
 * "Configurado".
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
export function cardLabelKey(key: string, state: CardState): MessageKey {
  if (key === "assistant" && state === "pending") {
    return "configCenter.state.pendingNotSuitable";
  }
  return STATE_META[state].labelKey;
}

/** Localized visible label for a card. Kept alongside {@link cardLabelKey} so
 *  callers that already own a translation function render through the
 *  catalogue instead of a module-level literal. */
export function cardLabel(
  key: string,
  state: CardState,
  t: TFunction,
): string {
  return t(cardLabelKey(key, state));
}

/**
 * Essential World + editor badge truth (OC11/OC21). Retained as the shared
 * contract helper; the Profile Preferencias surface no longer renders it
 * (product-owner decision), so only the contract tests exercise it today.
 */
export function essentialBadgeFor(
  readiness: ReadinessSnapshot | null,
  cards: Record<string, CardState>,
  key: string,
  t: TFunction,
): { label: string; badge: "default" | "success" | "error" } {
  if (key === "editor") {
    return readiness?.local_editor.ok
      ? { label: t("configCenter.state.ready"), badge: "success" }
      : { label: t("configCenter.state.unavailable"), badge: "error" };
  }
  return cardState(cards, "world") === "configured"
    ? { label: t("configCenter.state.ready"), badge: "success" }
    : { label: t("configCenter.state.pending"), badge: "default" };
}