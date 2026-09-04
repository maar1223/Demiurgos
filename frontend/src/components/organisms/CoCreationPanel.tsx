import { useState } from "react";
import type { UseCoCreationReturn } from "@/hooks/useCoCreation";
import type { CoCreationMilestone } from "@/api/types";
import { CORE_TALLERES } from "@/lib/constants";
import { Button } from "@/components/atoms/Button";
import { Badge } from "@/components/atoms/Badge";
import { Spinner } from "@/components/atoms/Spinner";
import { Icon } from "@/components/atoms/Icon";
import { cn } from "@/lib/utils";

/**
 * Co-creation surface for the Skill Madre (Fase 4 — MVP).
 *
 * The "Crear skill" section of the Taller de Herramientas splits the
 * co-creation experience across the three `EditorLayout` panes sharing ONE
 * `useCoCreation` hook instance (the backend is the authoritative session
 * store; localStorage is only a recovery hint):
 *
 * - `CoCreationMilestoneSidebar` (left): the six milestones with
 *   completado/actual/pendiente styling (REQ-CC-3) + session context.
 * - `CoCreationPanel` (center): one question per turn (REQ-CC-3), the
 *   materialization confirmation at Borrador listo (REQ-CC-5) and the
 *   minimal review/publish view (REQ-CC-6).
 * - `CoCreationContextPanel` (right): world context, draft preview and the
 *   compiler-issues validation panel (REQ-CC-5).
 *
 * Hermes boundary (REQ-CC-7): the panel never sends or renders authority-key
 * content; it only sends structured Author answers and renders backend
 * responses. Publish/Activate are explicit Author actions — Publish stays
 * disabled until the materialized draft has zero compiler issues.
 */

const MILESTONE_LABELS: Record<string, string> = {
  proposito: "Propósito",
  alcance: "Alcance",
  flujo_principal: "Flujo principal",
  ramas_reglas: "Ramas y reglas",
  borrador_listo: "Borrador listo",
  revision_publicacion: "Revisión y publicación",
};

const PHASE_LABELS: Record<string, string> = {
  conversation: "Conversación",
  materialized: "Materializado",
  review: "Revisión",
  complete: "Completo",
};

function milestoneLabel(name: string): string {
  return MILESTONE_LABELS[name] ?? name;
}

function phaseLabel(phase: string): string {
  return PHASE_LABELS[phase] ?? phase;
}

function shortId(id: string): string {
  return id.length > 14 ? `${id.slice(0, 14)}…` : id;
}

// ---------------------------------------------------------------------------
// Left pane — milestones + session context
// ---------------------------------------------------------------------------

interface CoCreationMilestoneSidebarProps {
  state: UseCoCreationReturn;
}

export function CoCreationMilestoneSidebar({
  state,
}: CoCreationMilestoneSidebarProps) {
  const { session } = state;
  const milestones: CoCreationMilestone[] = session?.progress ?? [];

  return (
    <div className="flex h-full flex-col gap-4 px-3 py-4">
      <div>
        <h2 className="text-small font-medium uppercase tracking-wide text-muted">
          Progreso
        </h2>
        {milestones.length === 0 ? (
          <p className="mt-2 text-xs text-muted">
            Todavía no hay una sesión activa.
          </p>
        ) : (
          <ol className="mt-3 space-y-2">
            {milestones.map((milestone) => (
              <li
                key={milestone.name}
                aria-current={milestone.state === "actual" ? "step" : undefined}
                className={cn(
                  "flex items-start gap-2 rounded-md px-2 py-1.5 text-xs",
                  milestone.state === "completado" &&
                    "bg-status-success/10 text-status-success",
                  milestone.state === "actual" &&
                    "bg-action/10 text-action ring-1 ring-action/30",
                  milestone.state === "pendiente" && "text-muted",
                )}
              >
                <span className="mt-0.5">
                  {milestone.state === "completado" ? (
                    <Icon name="check" size={14} />
                  ) : milestone.state === "actual" ? (
                    <Icon name="lightbulb" size={14} />
                  ) : (
                    <span className="inline-block h-3.5 w-3.5 rounded-full border border-edge" />
                  )}
                </span>
                <span>{milestoneLabel(milestone.name)}</span>
              </li>
            ))}
          </ol>
        )}
      </div>

      {session && (
        <div className="rounded-lg border border-edge bg-surface px-3 py-3">
          <h3 className="text-xs font-medium text-muted">Sesión</h3>
          <dl className="mt-2 space-y-1.5 text-xs text-primary">
            <div className="flex items-center justify-between gap-2">
              <dt className="text-muted">Sesión</dt>
              <dd className="font-mono">{shortId(session.session_id)}</dd>
            </div>
            <div className="flex items-center justify-between gap-2">
              <dt className="text-muted">Fase</dt>
              <dd>
                <Badge variant={session.phase === "complete" ? "success" : "default"}>
                  {phaseLabel(session.phase)}
                </Badge>
              </dd>
            </div>
            <div className="flex items-center justify-between gap-2">
              <dt className="text-muted">Preguntas</dt>
              <dd>{session.question_count}</dd>
            </div>
            <div className="flex items-center justify-between gap-2">
              <dt className="text-muted">Mundo</dt>
              <dd>{session.world ?? "Transversal"}</dd>
            </div>
            {session.draft_id && (
              <div className="flex items-center justify-between gap-2">
                <dt className="text-muted">Borrador</dt>
                <dd className="font-mono">{shortId(session.draft_id)}</dd>
              </div>
            )}
          </dl>
        </div>
      )}

      <div className="mt-auto">
        <Button
          type="button"
          variant="ghost"
          size="sm"
          onClick={() => state.reset()}
          className="w-full"
        >
          Nueva sesión
        </Button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Center pane — chat (one question per turn) + materialize + review/publish
// ---------------------------------------------------------------------------

interface CoCreationPanelProps {
  state: UseCoCreationReturn;
  /** Available worlds for the world-specific scope selector and activation. */
  worlds: string[];
}

export function CoCreationPanel({ state, worlds }: CoCreationPanelProps) {
  const [input, setInput] = useState("");
  const [scopeWorld, setScopeWorld] = useState("");
  const [activateWorld, setActivateWorld] = useState("");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [taller, setTaller] = useState("");
  const [etiquetas, setEtiquetas] = useState("");
  const { session, isLoading, error } = state;
  const messages = session?.messages ?? [];
  const hasIssues =
    (session?.compile_issues?.length ?? 0) > 0;
  const canMaterialize =
    session?.milestone === "borrador_listo" && session.phase === "conversation";
  const inReview = session?.phase === "review";
  const complete = session?.phase === "complete";

  const submit = () => {
    if (!input.trim() || isLoading) return;
    void state.send(input);
    setInput("");
  };

  const start = () => {
    if (!input.trim() || isLoading) return;
    void state.create(input, scopeWorld || null);
    setInput("");
  };

  const materialize = () => {
    void state.materialize({
      name: name.trim() || undefined,
      description: description.trim() || undefined,
      taller: taller || undefined,
      etiquetas: etiquetas
        .split(",")
        .map((tag) => tag.trim())
        .filter(Boolean),
    });
  };

  const activeWorld = scopeWorld || session?.world || "";

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="border-b border-edge px-4 py-3">
        <h2 className="text-body font-medium text-primary">Co-crear una skill</h2>
        <p className="mt-1 text-xs text-muted">
          Una pregunta por vez, guiada por la Skill Madre. Vos aprobás cada
          paso.
        </p>
      </div>

      <div className="flex-1 overflow-y-auto px-4 py-3">
        {!session ? (
          <div className="mx-auto max-w-xl">
            <p className="text-sm text-primary">
              Describí la skill que querés crear. La Skill Madre te va guiando
              con una pregunta por vez, del propósito al borrador.
            </p>
            <label className="mt-4 block text-xs text-muted">
              Alcance de la skill
              <select
                value={scopeWorld}
                onChange={(event) => setScopeWorld(event.target.value)}
                className="mt-1 w-full rounded-lg border border-edge bg-surface px-3 py-2 text-sm text-primary focus:border-action focus:outline-none"
              >
                <option value="">Transversal (sin mundo)</option>
                {worlds.map((world) => (
                  <option key={world} value={world}>
                    Mundo específico: {world}
                  </option>
                ))}
              </select>
            </label>
          </div>
        ) : (
          <div className="space-y-2">
            {messages.map((message, index) => (
              <div
                key={`${message.role}-${index}`}
                className={cn(
                  "rounded-lg px-3 py-2 text-sm text-primary",
                  message.role === "assistant"
                    ? "bg-surface"
                    : "bg-action/10 text-action",
                )}
              >
                {message.content}
              </div>
            ))}
            {session.pending_question && (
              <div className="rounded-lg border border-action/30 bg-action/10 px-3 py-2 text-sm text-primary">
                <p>{session.pending_question}</p>
                {session.pending_options.length > 0 && (
                  <div className="mt-2 flex flex-wrap gap-2">
                    {session.pending_options.map((option) => (
                      <button
                        key={option}
                        type="button"
                        onClick={() => void state.send(option)}
                        disabled={isLoading}
                        className="rounded-md border border-edge bg-surface px-2.5 py-1.5 text-xs text-primary hover:bg-surface-hover disabled:opacity-50"
                      >
                        {option}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
        )}

        {canMaterialize && (
          <div className="mt-4 rounded-lg border border-edge bg-surface p-4">
            <h3 className="text-sm font-medium text-primary">
              Borrador listo — confirmá los datos
            </h3>
            <p className="mt-1 text-xs text-muted">
              La Skill Madre ya juntó propósito, alcance y flujo. Confirmá el
              nombre y los metadatos para materializar el borrador en la
              biblioteca (todavía no se publica nada).
            </p>
            <div className="mt-3 grid gap-3">
              <label className="block text-xs text-muted">
                Nombre
                <input
                  value={name}
                  onChange={(event) => setName(event.target.value)}
                  placeholder="Nombre de la skill"
                  className="mt-1 w-full rounded-lg border border-edge bg-surface px-3 py-2 text-sm text-primary placeholder:text-muted focus:border-action focus:outline-none"
                />
              </label>
              <label className="block text-xs text-muted">
                Descripción
                <textarea
                  value={description}
                  onChange={(event) => setDescription(event.target.value)}
                  placeholder="Descripción breve"
                  rows={2}
                  className="mt-1 w-full resize-none rounded-lg border border-edge bg-surface px-3 py-2 text-sm text-primary placeholder:text-muted focus:border-action focus:outline-none"
                />
              </label>
              <div className="grid grid-cols-2 gap-3">
                <label className="block text-xs text-muted">
                  Taller
                  <select
                    value={taller}
                    onChange={(event) => setTaller(event.target.value)}
                    className="mt-1 w-full rounded-lg border border-edge bg-surface px-3 py-2 text-sm text-primary focus:border-action focus:outline-none"
                  >
                    <option value="">Sin taller</option>
                    {CORE_TALLERES.map((core) => (
                      <option key={core} value={core}>
                        {core}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="block text-xs text-muted">
                  Etiquetas
                  <input
                    value={etiquetas}
                    onChange={(event) => setEtiquetas(event.target.value)}
                    placeholder="plot, narrativa"
                    className="mt-1 w-full rounded-lg border border-edge bg-surface px-3 py-2 text-sm text-primary placeholder:text-muted focus:border-action focus:outline-none"
                  />
                </label>
              </div>
            </div>
            <Button
              type="button"
              size="sm"
              onClick={materialize}
              disabled={isLoading}
              className="mt-4"
            >
              {isLoading ? <Spinner size="sm" /> : "Generar borrador"}
            </Button>
          </div>
        )}

        {(inReview || complete) && (
          <div className="mt-4 space-y-4">
            <div className="rounded-lg border border-edge bg-surface p-4">
              <h3 className="text-sm font-medium text-primary">
                Revisión y publicación
              </h3>
              <dl className="mt-3 space-y-2 text-sm">
                <div className="flex justify-between gap-3">
                  <dt className="text-muted">Nombre</dt>
                  <dd className="text-right text-primary">
                    {name.trim() || "Co-created skill"}
                  </dd>
                </div>
                <div className="flex justify-between gap-3">
                  <dt className="text-muted">Descripción</dt>
                  <dd className="text-right text-primary">
                    {description.trim() || "—"}
                  </dd>
                </div>
                <div className="flex justify-between gap-3">
                  <dt className="text-muted">Taller</dt>
                  <dd className="text-primary">{taller || "—"}</dd>
                </div>
                <div className="flex justify-between gap-3">
                  <dt className="text-muted">Etiquetas</dt>
                  <dd className="text-primary">
                    {etiquetas.trim() || "—"}
                  </dd>
                </div>
                {session.draft_id && (
                  <div className="flex justify-between gap-3">
                    <dt className="text-muted">Borrador</dt>
                    <dd className="font-mono text-xs text-primary">
                      {shortId(session.draft_id)}
                    </dd>
                  </div>
                )}
              </dl>
              {state.published && (
                <p className="mt-3 rounded-md border border-status-success/30 bg-status-success/10 px-3 py-2 text-xs text-status-success">
                  Publicada la versión {state.published.published.version} —{" "}
                  {state.published.published.skill_id}
                </p>
              )}
              {state.activation && (
                <p className="mt-2 rounded-md border border-status-success/30 bg-status-success/10 px-3 py-2 text-xs text-status-success">
                  Activada en «{state.activation.activation.world}» (versión{" "}
                  {state.activation.activation.version})
                </p>
              )}
            </div>

            {!complete && (
              <div className="flex flex-wrap items-center gap-3">
                <Button
                  type="button"
                  size="sm"
                  onClick={() => void state.publish()}
                  disabled={isLoading || hasIssues}
                  title={
                    hasIssues
                      ? "Corregí los errores de compilación antes de publicar."
                      : "Publicar la versión inmutable"
                  }
                >
                  {isLoading ? <Spinner size="sm" /> : "Publicar"}
                </Button>
                <label className="flex items-center gap-2 text-xs text-muted">
                  Activar en
                  <select
                    value={activateWorld || activeWorld}
                    onChange={(event) => setActivateWorld(event.target.value)}
                    disabled={isLoading || !state.published}
                    className="rounded-lg border border-edge bg-surface px-2 py-1.5 text-sm text-primary focus:border-action focus:outline-none disabled:opacity-50"
                  >
                    <option value="">Elegí un mundo</option>
                    {worlds.map((world) => (
                      <option key={world} value={world}>
                        {world}
                      </option>
                    ))}
                  </select>
                  <Button
                    type="button"
                    variant="secondary"
                    size="sm"
                    onClick={() =>
                      void state.activate(activateWorld || activeWorld)
                    }
                    disabled={
                      isLoading || !state.published || !(activateWorld || activeWorld)
                    }
                  >
                    Activar
                  </Button>
                </label>
              </div>
            )}
          </div>
        )}

        {error && (
          <div
            role="alert"
            className="mt-3 rounded-md border border-status-error/30 bg-status-error/10 px-3 py-2 text-xs text-status-error"
          >
            {error} No se guardó nada. Reintentá cuando quieras.
          </div>
        )}
      </div>

      <div className="border-t border-edge px-4 py-3">
        {!session ? (
          <div className="flex items-end gap-2">
            <textarea
              aria-label="Idea de skill"
              value={input}
              onChange={(event) => setInput(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey) {
                  event.preventDefault();
                  start();
                }
              }}
              disabled={isLoading}
              rows={2}
              placeholder="Describí la skill que querés crear..."
              className="min-w-0 flex-1 resize-none rounded-lg border border-edge bg-surface px-3 py-2 text-sm text-primary placeholder:text-muted focus:border-action focus:outline-none disabled:opacity-50"
            />
            <Button
              type="button"
              size="sm"
              onClick={start}
              disabled={isLoading || !input.trim()}
              className="h-9"
            >
              {isLoading ? <Spinner size="sm" /> : "Crear skill"}
            </Button>
          </div>
        ) : (
          <div className="flex items-end gap-2">
            <textarea
              aria-label="Respuesta de co-creación"
              value={input}
              onChange={(event) => setInput(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey) {
                  event.preventDefault();
                  submit();
                }
              }}
              disabled={isLoading || inReview || complete}
              rows={2}
              placeholder={
                inReview || complete
                  ? "La conversación está en revisión."
                  : "Respondé la pregunta..."
              }
              className="min-w-0 flex-1 resize-none rounded-lg border border-edge bg-surface px-3 py-2 text-sm text-primary placeholder:text-muted focus:border-action focus:outline-none disabled:opacity-50"
            />
            <Button
              type="button"
              size="sm"
              onClick={submit}
              disabled={isLoading || !input.trim() || inReview || complete}
              className="h-9"
            >
              {isLoading ? <Spinner size="sm" /> : "Enviar"}
            </Button>
          </div>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Right pane — world context + draft preview + validation panel
// ---------------------------------------------------------------------------

interface CoCreationContextPanelProps {
  state: UseCoCreationReturn;
}

export function CoCreationContextPanel({
  state,
}: CoCreationContextPanelProps) {
  const { session } = state;
  const issues = session?.compile_issues ?? [];

  return (
    <div className="flex h-full flex-col gap-4 overflow-y-auto px-3 py-4">
      <div className="rounded-lg border border-edge bg-surface px-3 py-3">
        <h3 className="text-xs font-medium text-muted">Contexto de mundo</h3>
        {session?.world ? (
          <p className="mt-2 text-sm text-primary">
            La sesión está ligada a «{session.world}»: la Skill Madre solo usa
            el contexto autorizado de ese mundo.
          </p>
        ) : (
          <p className="mt-2 text-sm text-primary">
            Skill transversal: sin vínculo a ningún mundo.
          </p>
        )}
      </div>

      {session?.draft_id && (
        <div className="rounded-lg border border-edge bg-surface px-3 py-3">
          <h3 className="text-xs font-medium text-muted">Borrador</h3>
          <p className="mt-2 font-mono text-xs text-primary">
            {session.draft_id}
          </p>
          <p className="mt-1 text-xs text-muted">
            Materializado por la Skill Madre desde las respuestas estructuradas.
          </p>
        </div>
      )}

      <div
        className={cn(
          "rounded-lg border px-3 py-3",
          issues.length > 0
            ? "border-status-error/30 bg-status-error/10"
            : "border-edge bg-surface",
        )}
      >
        <h3 className="text-xs font-medium text-muted">Validación</h3>
        {session?.compile_issues === null && (
          <p className="mt-2 text-xs text-muted">
            Todavía no se compiló ningún borrador.
          </p>
        )}
        {issues.length > 0 && (
          <>
            <p className="mt-2 text-xs text-status-error">
              El borrador tiene errores de compilación. Corregí la conversación
              y volvé a generar el borrador.
            </p>
            <ul className="mt-2 space-y-2">
              {issues.map((issue, index) => (
                <li
                  key={`${issue.code}-${index}`}
                  className="rounded-md border border-status-error/30 bg-surface px-2.5 py-2 text-xs"
                >
                  <p className="font-medium text-status-error">{issue.code}</p>
                  <p className="mt-0.5 text-primary">{issue.message}</p>
                  {issue.field && (
                    <p className="mt-0.5 font-mono text-muted">{issue.field}</p>
                  )}
                </li>
              ))}
            </ul>
          </>
        )}
        {issues.length === 0 && session?.compile_issues !== null && (
          <p className="mt-2 text-xs text-status-success">
            El borrador compila correctamente.
          </p>
        )}
      </div>
    </div>
  );
}