import { useCallback, useEffect, useState } from "react";
import {
  importPackage,
  listQuarantine,
  trustQuarantine,
} from "@/api/methodologies";
import { ApiError } from "@/api/types";
import type { PackageVerdict, QuarantineRecord } from "@/api/types";
import { Button } from "@/components/atoms/Button";
import { Spinner } from "@/components/atoms/Spinner";
import { Badge } from "@/components/atoms/Badge";
import {
  CLASIFICACION_VARIANT,
  TRUST_VARIANT,
} from "@/components/molecules/InventoryRow";
import { useAppLanguage } from "@/hooks/useAppLanguage";
import type { TFunction } from "@/i18n/messages";

function shortId(id: string): string {
  return id.length > 14 ? `${id.slice(0, 14)}…` : id;
}

/** Readable verdict badges for a quarantined package (REQ-IMP-3): checksum
 *  integrity, official signature state, and compiler pass/errors. `ok` is the
 *  server's full verdict; when integrity fails the compiler never ran, so the
 *  badge reads "sin revisar" instead of blaming the compiler. */
function VerdictBadges({ verdict }: { verdict: PackageVerdict }) {
  const { t } = useAppLanguage();
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <Badge variant={verdict.checksum_valid ? "success" : "error"}>
        {verdict.checksum_valid
          ? t("skillImport.checksumOk")
          : t("skillImport.checksumCorrupt")}
      </Badge>
      <Badge
        variant={
          verdict.signature_valid === true
            ? "success"
            : verdict.signature_present
              ? "error"
              : "default"
        }
      >
        {verdict.signature_valid === true
          ? t("skillImport.signatureVerified")
          : verdict.signature_present
            ? t("skillImport.signatureInvalid")
            : t("skillImport.noSignature")}
      </Badge>
      <Badge
        variant={verdict.ok ? "success" : verdict.checksum_valid ? "error" : "warning"}
      >
        {verdict.ok
          ? t("skillImport.compileOk")
          : verdict.checksum_valid
            ? t("skillImport.compileErrors")
            : t("skillImport.compileNotReviewed")}
      </Badge>
    </div>
  );
}

/** Map a transfer action failure to Author-facing copy (REQ-IMP-6): the
 *  reserved Skill Madre id and the failed re-validation get specific messages;
 *  everything else falls back to the API message. */
function transferErrorMessage(cause: unknown, t: TFunction): string {
  if (cause instanceof ApiError) {
    if (cause.code === "reserved_skill_id") {
      return t("skillImport.reservedId");
    }
    if (cause.code === "trust_rejected") {
      return t("skillImport.trustRejected");
    }
    return cause.message;
  }
  return t("skillImport.transferFailed");
}

/**
 * Import authoring mode — .zip quarantine/trust block (REQ-CC-3).
 *
 * An outside-workshop skill only becomes usable after mandatory quarantine +
 * integrity review + explicit trust (REQ-IMP-2..5). World-agnostic: the import
 * flow never touches world or taller state.
 */
export function SkillImportPanel() {
  const { t } = useAppLanguage();
  const [quarantine, setQuarantine] = useState<QuarantineRecord[]>([]);
  const [importing, setImporting] = useState(false);
  const [trustingId, setTrustingId] = useState<string | null>(null);
  const [transferError, setTransferError] = useState<string | null>(null);

  const loadQuarantine = useCallback(async () => {
    try {
      const { entries } = await listQuarantine();
      setQuarantine(entries ?? []);
    } catch {
      // The quarantine panel stays empty on failure; the import action
      // reports its own errors.
    }
  }, []);

  useEffect(() => {
    void loadQuarantine();
  }, [loadQuarantine]);

  const handleImport = async (file: File | null) => {
    if (!file) return;
    setImporting(true);
    setTransferError(null);
    try {
      await importPackage(file);
      await loadQuarantine();
    } catch (cause) {
      setTransferError(transferErrorMessage(cause, t));
    } finally {
      setImporting(false);
    }
  };

  const handleTrust = async (packageId: string) => {
    setTrustingId(packageId);
    setTransferError(null);
    try {
      const trusted = await trustQuarantine(packageId);
      setQuarantine((prev) =>
        prev.map((record) =>
          record.package_id === packageId
            ? {
                ...record,
                trusted: true,
                draft_id: trusted.draft_id,
                clasificacion: trusted.clasificacion,
                trust_attributes: trusted.trust_attributes,
              }
            : record,
        ),
      );
    } catch (cause) {
      setTransferError(transferErrorMessage(cause, t));
    } finally {
      setTrustingId(null);
    }
  };

  return (
    <div className="rounded-lg border border-edge/20 bg-surface-raised/40 p-4">
      <h3 className="font-heading text-h4 text-primary">
        {t("skillImport.title")}
      </h3>
      <p className="mt-1 text-small text-muted">{t("skillImport.intro")}</p>
      <div className="mt-4 flex flex-wrap items-center gap-3">
        <label className="flex flex-col gap-1 text-small text-muted">
          {t("skillImport.packageLabel")}
          <input
            type="file"
            accept=".zip,application/zip"
            disabled={importing}
            onChange={(event) =>
              void handleImport(event.target.files?.[0] ?? null)
            }
            className="text-xs text-primary file:mr-3 file:rounded-md file:border file:border-edge file:bg-surface file:px-3 file:py-1.5 file:text-xs file:text-primary"
          />
        </label>
        {importing && <Spinner size="sm" />}
      </div>
      {transferError && (
        <p
          role="alert"
          className="mt-3 rounded-md border border-status-error/30 bg-status-error/10 px-3 py-2 text-xs text-status-error"
        >
          {transferError}
        </p>
      )}
      {quarantine.length > 0 && (
        <ul className="mt-4 space-y-2">
          {quarantine.map((record) => (
            <li
              key={record.package_id}
              className="rounded-md border border-edge bg-surface px-3 py-2"
            >
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="min-w-0">
                  <p className="font-mono text-xs text-primary">
                    {record.package_id}
                  </p>
                  <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
                    <VerdictBadges verdict={record.verdict} />
                    <Badge variant={record.trusted ? "success" : "warning"}>
                      {record.trusted
                        ? t("skillImport.trusted")
                        : t("skillImport.quarantined")}
                    </Badge>
                  </div>
                  {record.verdict.issues.length > 0 && (
                    <p className="mt-1.5 text-xs text-muted">
                      {record.verdict.issues.join(" · ")}
                    </p>
                  )}
                </div>
                {record.trusted ? (
                  <div className="flex flex-col items-end gap-2">
                    <p className="text-xs text-status-success">
                      {record.draft_id
                        ? t("skillImport.trustedDraft", { id: shortId(record.draft_id) })
                        : t("skillImport.trusted")}
                    </p>
                    {/* REQ-IMP-5 (scenario 2): the outside-workshop note also
                        appears in the advanced details of a trusted import,
                        framed as integrity — the Taller only executes the
                        compiled, validated version the Author trusted. */}
                    <details className="rounded-md border border-edge bg-surface-raised px-3 py-2">
                      <summary className="cursor-pointer text-xs font-medium text-muted">
                        {t("skillImport.advanced")}
                      </summary>
                      <div className="mt-2 space-y-1.5 text-xs">
                        <p className="text-muted">{t("skillImport.outsideNote")}</p>
                        <div className="flex flex-wrap items-center gap-1.5">
                          <Badge
                            variant={
                              CLASIFICACION_VARIANT[
                                record.clasificacion ?? ""
                              ] ?? "default"
                            }
                          >
                            {record.clasificacion ?? t("skillImport.noClassification")}
                          </Badge>
                          {record.trust_attributes.map((attr) => (
                            <Badge
                              key={attr}
                              variant={TRUST_VARIANT[attr] ?? "default"}
                            >
                              {attr}
                            </Badge>
                          ))}
                        </div>
                      </div>
                    </details>
                  </div>
                ) : (
                  <Button
                    type="button"
                    variant="secondary"
                    size="sm"
                    disabled={trustingId === record.package_id}
                    onClick={() => void handleTrust(record.package_id)}
                  >
                    {trustingId === record.package_id ? (
                      <Spinner size="sm" />
                    ) : (
                      t("skillImport.trust")
                    )}
                  </Button>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}