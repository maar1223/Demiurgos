import { useCallback, useEffect, useState } from "react";
import {
  activateMethodology,
  createMethodologyDraft,
  getMethodologyStatus,
  importPackage,
  listQuarantine,
  publishMethodologyDraft,
  trustQuarantine,
} from "@/api/methodologies";
import { ApiError } from "@/api/types";
import type {
  MethodologyStatus,
  PackageVerdict,
  QuarantineRecord,
} from "@/api/types";
import { Button } from "@/components/atoms/Button";
import { Spinner } from "@/components/atoms/Spinner";
import { Badge } from "@/components/atoms/Badge";
import { EmptyState } from "@/components/organisms/EmptyState";
import { ErrorBanner } from "@/components/organisms/ErrorBanner";
import { TallerTree } from "@/components/organisms/TallerTree";
import { groupSkillsByState } from "@/lib/tallerStates";

function shortId(id: string): string {
  return id.length > 14 ? `${id.slice(0, 14)}…` : id;
}

/** Readable verdict badges for a quarantined package (REQ-IMP-3): checksum
 *  integrity, official signature state, and compiler pass/errors. `ok` is the
 *  server's full verdict; when integrity fails the compiler never ran, so the
 *  badge reads "sin revisar" instead of blaming the compiler. */
function VerdictBadges({ verdict }: { verdict: PackageVerdict }) {
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <Badge variant={verdict.checksum_valid ? "success" : "error"}>
        {verdict.checksum_valid ? "Checksum OK" : "Checksum corrupto"}
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
          ? "Firma verificada"
          : verdict.signature_present
            ? "Firma inválida"
            : "Sin firma"}
      </Badge>
      <Badge
        variant={verdict.ok ? "success" : verdict.checksum_valid ? "error" : "warning"}
      >
        {verdict.ok
          ? "Compilación OK"
          : verdict.checksum_valid
            ? "Errores de compilación"
            : "Compilación sin revisar"}
      </Badge>
    </div>
  );
}

/** Map a transfer action failure to Author-facing copy (REQ-IMP-6): the
 *  reserved Skill Madre id and the failed re-validation get specific messages;
 *  everything else falls back to the API message. */
function transferErrorMessage(cause: unknown): string {
  if (cause instanceof ApiError) {
    if (cause.code === "reserved_skill_id") {
      return "No se puede importar esta skill: su identidad está reservada por Demiurgos.";
    }
    if (cause.code === "trust_rejected") {
      return "El paquete no pasó la revisión de integridad: no se confió.";
    }
    return cause.message;
  }
  return "No se pudo completar la operación de importación.";
}

interface MethodologyLibraryProps {
  /** World to activate versions for (the selected Taller de Mundo world). */
  world?: string;
  /** Active Taller SHORT KEY (Herramientas | Mundo | Ideas) — drives the
   *  contextual tree via `groupSkillsByState` (spec REQ-TRE-3/5). */
  activeTaller: string;
}

/**
 * Taller de Herramientas — methodology library.
 *
 * Lists published methodology versions, lets the Author publish an editable
 * draft, and activates a published version for the selected world. Activation
 * is world-scoped: it governs NEW guided sessions in that world only; already
 * running sessions fail closed (server-enforced).
 */
export function MethodologyLibrary({
  world,
  activeTaller,
}: MethodologyLibraryProps) {
  const [status, setStatus] = useState<MethodologyStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // -- Skill transfer (REQ-IMP-2..4): import → quarantine → trust ----------

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
      setTransferError(transferErrorMessage(cause));
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
      setTransferError(transferErrorMessage(cause));
    } finally {
      setTrustingId(null);
    }
  };

  const [skillId, setSkillId] = useState("");
  const [version, setVersion] = useState("");
  const [name, setName] = useState("");
  const [source, setSource] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setStatus(await getMethodologyStatus());
    } catch {
      setError("No se pudo cargar la biblioteca de metodologías.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const handlePublish = async () => {
    if (!skillId.trim() || !version.trim() || !name.trim() || !source.trim()) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const draft = await createMethodologyDraft({
        skill_id: skillId.trim(),
        version: version.trim(),
        name: name.trim(),
        source,
      });
      await publishMethodologyDraft(draft.draft_id);
      setSkillId("");
      setVersion("");
      setName("");
      setSource("");
      await load();
    } catch {
      setError("La metodología no pasó la validación del compilador.");
    } finally {
      setBusy(false);
    }
  };

  const handleActivate = async (skill: string, ver: string) => {
    if (!world) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await activateMethodology(world, skill, ver);
      await load();
    } catch {
      setError("No se pudo activar la versión para este mundo.");
    } finally {
      setBusy(false);
    }
  };

  if (loading) {
    return (
      <div className="flex justify-center py-16">
        <Spinner size="lg" />
      </div>
    );
  }

  const published = status?.published ?? [];
  const active = world && status ? status.activations[world] : undefined;
  const groups = groupSkillsByState(
    published,
    activeTaller,
    world,
    status?.activations ?? {},
  );

  return (
    <section className="space-y-6">
      <div className="flex items-baseline justify-between gap-4">
        <div>
          <h2 className="font-heading text-h4 text-primary">
            Bibliotecas de metodologías
          </h2>
          <p className="mt-1 text-small text-muted">
            Publicá borradores validados y activá una versión inmutable por
            mundo. La activación solo afecta sesiones nuevas.
          </p>
        </div>
        <Button variant="ghost" size="sm" onClick={load}>
          Actualizar
        </Button>
      </div>

      {error && <ErrorBanner message={error} onRetry={load} />}

      {published.length === 0 ? (
        <EmptyState
          icon="empty"
          message="Todavía no hay metodologías publicadas. Escribí un borrador y publicalo para activarlo por mundo."
        />
      ) : (
        <TallerTree
          groups={groups}
          world={world}
          activeTaller={activeTaller}
          active={active}
          onActivate={handleActivate}
          busy={busy}
        />
      )}

      <div className="rounded-lg border border-edge/20 bg-surface-raised/40 p-4">
        <h3 className="font-heading text-h4 text-primary">
          Publicar un borrador
        </h3>
        <form
          className="mt-4 space-y-3"
          onSubmit={(event) => {
            event.preventDefault();
            void handlePublish();
          }}
        >
          <div className="grid gap-3 sm:grid-cols-3">
            <label className="flex flex-col gap-1 text-small text-muted">
              Skill ID
              <input
                className="rounded-lg bg-surface px-3 py-2 text-body text-primary outline-none focus:ring-2 focus:ring-action/50"
                value={skillId}
                onChange={(event) => setSkillId(event.target.value)}
              />
            </label>
            <label className="flex flex-col gap-1 text-small text-muted">
              Versión
              <input
                className="rounded-lg bg-surface px-3 py-2 text-body text-primary outline-none focus:ring-2 focus:ring-action/50"
                value={version}
                onChange={(event) => setVersion(event.target.value)}
              />
            </label>
            <label className="flex flex-col gap-1 text-small text-muted">
              Nombre
              <input
                className="rounded-lg bg-surface px-3 py-2 text-body text-primary outline-none focus:ring-2 focus:ring-action/50"
                value={name}
                onChange={(event) => setName(event.target.value)}
              />
            </label>
          </div>
          <label className="flex flex-col gap-1 text-small text-muted">
            Fuente (Markdown)
            <textarea
              className="min-h-24 rounded-lg bg-surface px-3 py-2 text-body text-primary outline-none focus:ring-2 focus:ring-action/50"
              value={source}
              onChange={(event) => setSource(event.target.value)}
            />
          </label>
          <Button type="submit" size="sm" disabled={busy}>
            Publicar borrador
          </Button>
        </form>
      </div>

      {/* Skill transfer (REQ-IMP-2..5): an outside-workshop skill only becomes
          usable after mandatory quarantine + integrity review + explicit
          trust. Framed as integrity, not punishment (REQ-IMP-5). */}
      <div className="rounded-lg border border-edge/20 bg-surface-raised/40 p-4">
        <h3 className="font-heading text-h4 text-primary">
          Importar una skill
        </h3>
        <p className="mt-1 text-small text-muted">
          La Skill creada fuera del Taller no se ejecuta como válida: entra en
          cuarentena y recién se habilita cuando pasa la revisión de integridad
          y vos la confiás.
        </p>
        <div className="mt-4 flex flex-wrap items-center gap-3">
          <label className="flex flex-col gap-1 text-small text-muted">
            Paquete (.zip)
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
                        {record.trusted ? "Confiable" : "En cuarentena"}
                      </Badge>
                    </div>
                    {record.verdict.issues.length > 0 && (
                      <p className="mt-1.5 text-xs text-muted">
                        {record.verdict.issues.join(" · ")}
                      </p>
                    )}
                  </div>
                  {record.trusted ? (
                    <p className="text-xs text-status-success">
                      {record.draft_id
                        ? `Confiable — borrador ${shortId(record.draft_id)}`
                        : "Confiable"}
                    </p>
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
                        "Confiar"
                      )}
                    </Button>
                  )}
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}
