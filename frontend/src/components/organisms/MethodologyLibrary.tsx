import { useCallback, useEffect, useState } from "react";
import {
  activateMethodology,
  getMethodologyStatus,
} from "@/api/methodologies";
import type { MethodologyStatus } from "@/api/types";
import { Button } from "@/components/atoms/Button";
import { Spinner } from "@/components/atoms/Spinner";
import { EmptyState } from "@/components/organisms/EmptyState";
import { ErrorBanner } from "@/components/organisms/ErrorBanner";
import { TallerTree } from "@/components/organisms/TallerTree";
import { groupSkillsByState } from "@/lib/tallerStates";

interface MethodologyLibraryProps {
  /** World to activate versions for (the selected Taller de Mundo world). */
  world?: string;
  /** Active Taller SHORT KEY (Herramientas | Mundo | Ideas) — drives the
   *  contextual tree via `groupSkillsByState` (spec REQ-TRE-3/5). */
  activeTaller: string;
}

/**
 * Taller de Herramientas — methodology library (operational view).
 *
 * Lists published methodology versions for the selected world and lets the
 * Author activate a published version. Activation is world-scoped: it governs
 * NEW guided sessions in that world only; already running sessions fail closed
 * (server-enforced). Draft authoring (manual form + zip import) lives in
 * `ManualSkillCreator` / `SkillImportPanel`.
 */
export function MethodologyLibrary({
  world,
  activeTaller,
}: MethodologyLibraryProps) {
  const [status, setStatus] = useState<MethodologyStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

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
    </section>
  );
}