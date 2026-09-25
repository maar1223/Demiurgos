import { Badge } from "@/components/atoms/Badge";
import { useAppLanguage } from "@/hooks/useAppLanguage";
import type { DerivedFrom } from "@/api/types";
import { cn } from "@/lib/utils";

interface ProvenanceBadgeProps {
  /** Server-injected provenance from a co-creation session (TW14). */
  derivedFrom?: DerivedFrom | null;
  /** Alternative source: parent fields on a published/draft record
   *  (REQ-CC-21). Used when the row carries `parent_skill_id`/`parent_version`
   *  instead of a session-derived `DerivedFrom`. */
  parentSkillId?: string | null;
  parentVersion?: string | null;
  className?: string;
}

/** Resolve whichever provenance source is present (session-derived first,
 *  then the record parent fields). Returns null when neither is set. */
function resolveSource(
  derivedFrom: DerivedFrom | null | undefined,
  parentSkillId: string | null | undefined,
  parentVersion: string | null | undefined,
): DerivedFrom | null {
  if (derivedFrom) return derivedFrom;
  if (parentSkillId && parentVersion) {
    return { skill_id: parentSkillId, version: parentVersion };
  }
  return null;
}

/**
 * TW14 provenance badge: "Deriva de {skill_id}@{version}".
 *
 * The provenance is ALWAYS displayed from backend-injected data (REQ-CC-20) —
 * this component never fabricates or sends it; it only renders what the server
 * exposed on the session (`derived_from`) or on a published/draft record
 * (`parent_skill_id`/`parent_version`). Renders nothing when absent, so it is
 * safe to mount on any draft/review/published row.
 */
export function ProvenanceBadge({
  derivedFrom,
  parentSkillId,
  parentVersion,
  className,
}: ProvenanceBadgeProps) {
  const { t } = useAppLanguage();
  const source = resolveSource(derivedFrom, parentSkillId, parentVersion);
  if (!source) return null;

  return (
    <Badge variant="info" className={cn("gap-1", className)}>
      {t("cocreation.provenance", {
        skillId: source.skill_id,
        version: source.version,
      })}
    </Badge>
  );
}

export default ProvenanceBadge;