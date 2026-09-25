import type { FichaStatus } from "@/api/types";
import type { MessageKey } from "@/i18n/messages";

/** Per-status visual metadata for a ficha's OKF state. */
export interface StatusMeta {
  /** Catalogue key for the status label; resolve with `t(...)`. */
  labelKey: MessageKey;
  chipClass: string;
  dotClass: string;
}

/**
 * Single source of truth for the ficha status look — the file-bar chip
 * (StatusBadge) and the section-card status dot BOTH consume these exact
 * tokens, so the two surfaces can never drift in color or label.
 */
export const STATUS_META: Record<FichaStatus, StatusMeta> = {
  draft: {
    labelKey: "status.draft",
    // Amber, dashed — work in progress
    chipClass:
      "border-dashed border-amber-400/50 bg-amber-400/10 text-amber-300",
    dotClass: "border-dashed border-amber-400/50 bg-amber-400/10",
  },
  stable: {
    labelKey: "status.stable",
    // Emerald, solid — settled canon
    chipClass:
      "border-solid border-emerald-500/60 bg-emerald-500/15 text-emerald-300",
    dotClass: "border-solid border-emerald-500/60 bg-emerald-500/15",
  },
};
