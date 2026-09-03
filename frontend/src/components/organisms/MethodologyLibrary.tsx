import { useCallback, useEffect, useState } from "react";
import {
  activateMethodology,
  createMethodologyDraft,
  getMethodologyStatus,
  publishMethodologyDraft,
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
    </section>
  );
}
