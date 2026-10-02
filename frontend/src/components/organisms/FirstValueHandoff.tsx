import { Button } from "@/components/atoms/Button";
import { useAppLanguage } from "@/hooks/useAppLanguage";

export interface FirstValueHandoffProps {
  worldName: string;
  onImport: () => void;
  onWriteNote: () => void;
  onSetupAssistant: () => void;
  onDismiss: () => void;
}

/**
 * One-time "your world is ready" hero (first-value-handoff spec).
 *
 * Presentational: owns markup and copy only. Navigation and completion
 * belong to the page container (WikiWorld) via the callbacks — this
 * organism never navigates and never touches the pending flag.
 */
export function FirstValueHandoff({
  worldName,
  onImport,
  onWriteNote,
  onSetupAssistant,
  onDismiss,
}: FirstValueHandoffProps) {
  const { t } = useAppLanguage();

  return (
    <section
      aria-label={t("firstValueHandoff.aria")}
      className="rounded-xl border border-edge bg-surface-raised p-6"
    >
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="font-heading text-h4 text-primary">
            {t("firstValueHandoff.title")}
          </h2>
          <p className="mt-1 text-small text-muted">{worldName}</p>
        </div>
        <Button variant="ghost" size="sm" onClick={onDismiss}>
          {t("firstValueHandoff.dismiss")}
        </Button>
      </div>

      <p className="mt-3 text-body text-muted">
        {t("firstValueHandoff.intro")}
      </p>

      <div className="mt-5 grid grid-cols-1 gap-3 tablet:grid-cols-3">
        <div className="flex flex-col items-start gap-2 rounded-lg border border-edge bg-surface p-4">
          <Button variant="secondary" size="sm" onClick={onImport}>
            {t("firstValueHandoff.import")}
          </Button>
          <p className="text-small text-muted">
            {t("firstValueHandoff.importHint")}
          </p>
        </div>
        <div className="flex flex-col items-start gap-2 rounded-lg border border-edge bg-surface p-4">
          <Button variant="secondary" size="sm" onClick={onWriteNote}>
            {t("firstValueHandoff.writeNote")}
          </Button>
          <p className="text-small text-muted">
            {t("firstValueHandoff.writeNoteHint")}
          </p>
        </div>
        <div className="flex flex-col items-start gap-2 rounded-lg border border-edge bg-surface p-4">
          <Button variant="secondary" size="sm" onClick={onSetupAssistant}>
            {t("firstValueHandoff.setupAssistant")}
          </Button>
          <p className="text-small text-muted">
            {t("firstValueHandoff.setupAssistantHint")}
          </p>
        </div>
      </div>
    </section>
  );
}