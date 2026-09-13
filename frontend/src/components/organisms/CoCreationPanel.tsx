import { useState } from "react";
import type { UseCoCreationReturn } from "@/hooks/useCoCreation";
import type {
  CoCreationMilestone,
  DraftPayload,
  PendingQuestion,
  PublishedMethodologyDetail,
  WarningState,
} from "@/api/types";
import {
  DEFAULT_TALLER,
  OPERATIONAL_TALLERES,
} from "@/lib/constants";
import { Button } from "@/components/atoms/Button";
import { Badge } from "@/components/atoms/Badge";
import { Spinner } from "@/components/atoms/Spinner";
import { Icon } from "@/components/atoms/Icon";
import { MarkdownViewer } from "@/components/organisms/MarkdownViewer";
import { ManualSkillCreator } from "@/components/organisms/ManualSkillCreator";
import { SkillImportPanel } from "@/components/organisms/SkillImportPanel";
import { CoCreationCanvas } from "@/components/organisms/CoCreation/CoCreationCanvas";
import {
  normalizePendingQuestion,
  WARNING_STATE_LABELS,
  WARNING_STATE_VARIANT,
} from "@/components/organisms/CoCreation/CoCreationCanvas";
import { DraftHistoryPanel } from "@/components/organisms/CoCreation/DraftHistoryPanel";
import { AdaptationComparePanel } from "@/components/organisms/CoCreation/AdaptationComparePanel";
import { ProvenanceBadge } from "@/components/organisms/CoCreation/ProvenanceBadge";
import { cn } from "@/lib/utils";

/**
 * Co-creation surface for the Skill Madre (Fase 4 — MVP + Fase 5a TW12/TW13).
 *
 * The "Crear skill" section of the Taller de Herramientas splits the
 * co-creation experience across the three `EditorLayout` panes sharing ONE
 * `useCoCreation` hook instance (the backend is the authoritative session
 * store; localStorage is only a recovery hint):
 *
 * - `CoCreationMilestoneSidebar` (left): the six milestones with
 *   completado/actual/pendiente styling (REQ-CC-3) + session context.
 * - `CoCreationPanel` (center): tab between the chat (one question per turn,
 *   REQ-CC-3; materialization confirmation at Borrador listo, REQ-CC-5;
 *   review/publish, REQ-CC-6) and the TW12 editable canvas (per-section
 *   structured draft + undo/redo + debounced autosave + history restore,
 *   REQ-CC-11/15). The TW13 adaptation compare + provenance badge (TW14)
 *   surface here for derived sessions.
 * - `CoCreationContextPanel` (right): world context, draft preview, the
 *   compiler-issues validation panel, the 3-state warnings list (REQ-CC-13),
 *   and the chat-owned pending questions with Author-only transitions
 *   (REQ-CC-14).
 *
 * Hermes boundary (REQ-CC-7): the panel never sends or renders authority-key
 * content; canvas edits are Author-originated structured payloads only.
 * Publish/Activate remain the ONLY canonical mutations; validation only
 * renders/compiles. Provenance is always displayed from backend-injected data
 * (REQ-CC-20) — the frontend never fabricates `derived_from`.
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

/** TW16 review projection (REQ-TW16-1): the review block renders ONLY from
 *  `session.draft_payload` (server-authoritative, refresh-safe) — never from
 *  local component state. The typed `DraftPayload` is a projection of the
 *  wire dict: at materialization the server folds the Author-confirmed
 *  metadata (`taller`/`etiquetas`/`skill_id`/`version`) and the manifest
 *  compatibility list (`talleres_compatibles`) into the payload, so those
 *  keys are read defensively here. Render-only — no new envelope keys, no
 *  authority-adjacent writes (REQ-CC-7/22 safe). */
type ReviewPayload = DraftPayload & {
  taller?: string | null;
  etiquetas?: string[] | null;
  talleres_compatibles?: string[] | null;
  skill_id?: string | null;
  version?: string | null;
};

/** TW16 attribution (REQ-TW16-3): the review projection lists the coarse
 *  `DraftPayload` section keys. A section the Author touched in the canvas
 *  reads "decidido"; untouched sections read "propuesto". Kernel invariants
 *  (permisos/dependencias) always read "exigido". */
const REVIEW_SECTIONS: { key: keyof ReviewPayload; label: string }[] = [
  { key: "name", label: "Nombre" },
  { key: "description", label: "Descripción" },
  { key: "purpose", label: "Propósito" },
  { key: "scope", label: "Alcance" },
  { key: "main_flow", label: "Flujo principal" },
  { key: "branches", label: "Ramas" },
  { key: "rules", label: "Reglas" },
  { key: "taller", label: "Taller" },
  { key: "etiquetas", label: "Etiquetas" },
];

/** Full legend phrases (canonical copy — the per-row badges show the short
 *  "Decidido"/"Propuesto"/"Exigido" forms). */
const ATTRIBUTION_LABELS = {
  decidido: "decidido por el Autor",
  propuesto: "propuesto por el Asistente",
  exigido: "exigido por Demiurgos",
} as const;

/** Render one review value: lists join compactly, blanks read "—". */
function renderReviewValue(value: unknown): string {
  if (Array.isArray(value)) {
    return value.length > 0 ? value.join(", ") : "—";
  }
  if (typeof value === "string" && value.trim()) {
    return value;
  }
  return "—";
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
          <div className="flex items-center justify-between gap-2">
            <h3 className="text-xs font-medium text-muted">Sesión</h3>
            <ProvenanceBadge derivedFrom={session.derived_from} />
          </div>
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
// Center pane — chat (one question per turn) + canvas (TW12) + review/publish
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
  const [taller, setTaller] = useState<string>(DEFAULT_TALLER);
  const [etiquetas, setEtiquetas] = useState("");
  /** TW12 center-pane surface: chat (intention) or canvas (structure). */
  const [centerView, setCenterView] = useState<"chat" | "canvas">("chat");
  /** Authoring sub-mode (REQ-CC-1): guided chat+canvas (default), manual
   *  markdown draft form, or .zip import/quarantine. Orthogonal to centerView:
   *  the chat/canvas toggle only applies when authoringMode === "guided"
   *  (SC-CC-1.4). */
  const [authoringMode, setAuthoringMode] = useState<
    "guided" | "manual" | "import"
  >("guided");
  const [historyOpen, setHistoryOpen] = useState(false);
  const [compareOpen, setCompareOpen] = useState(false);
  const [originalDetail, setOriginalDetail] =
    useState<PublishedMethodologyDetail | null>(null);
  const { session, isLoading, error } = state;
  const messages = session?.messages ?? [];
  const hasIssues =
    (session?.compile_issues?.length ?? 0) > 0;
  const canMaterialize =
    session?.milestone === "borrador_listo" && session.phase === "conversation";
  const inReview = session?.phase === "review";
  const complete = session?.phase === "complete";
  const canvasDisabled = inReview || complete;

  /** TW16 review projection source (REQ-TW16-1): the server-authoritative
   *  `draft_payload` — never the local materialize-form state (refresh-lossy). */
  const reviewPayload = (session?.draft_payload ?? {}) as ReviewPayload;
  const touched = state.touchedSections;
  const compatibles = reviewPayload.talleres_compatibles ?? [];
  const dependencies = [
    ...(compatibles.length > 0 ? [compatibles.join(", ")] : []),
    ...(session?.world ? [`Mundo: ${session.world}`] : []),
  ];
  const dependenciesText =
    dependencies.length > 0 ? dependencies.join(" · ") : "ninguna";

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

  const openHistory = () => {
    void state.loadHistory();
    setHistoryOpen(true);
  };

  const openCompare = async () => {
    const df = session?.derived_from;
    if (!df) return;
    setCompareOpen(true);
    try {
      setOriginalDetail(await state.getPublishedDetail(df.skill_id, df.version));
    } catch {
      setOriginalDetail(null);
    }
  };

  /** TW13 "Adaptar" on a published row: derive a new editable draft (the ONLY
   *  path for `clasificacion="Oficiales"` — published versions are immutable,
   *  REQ-CC-16). The server injects provenance (REQ-CC-20) and opens the
   *  adaptation session bound to the derived draft (REQ-CC-17). */
  const adaptPublished = () => {
    const published = state.published?.published;
    if (!published) return;
    void state.derive(published.skill_id, published.version, session?.world ?? null);
  };

  const activeWorld = scopeWorld || session?.world || "";

  /** Shared canvas wiring used in the center pane AND the compare panel
   *  (TW13: the derived side of the compare IS the editable canvas). */
  const canvas = session ? (
    <CoCreationCanvas
      payload={state.draftPayload}
      onChange={(patch) => state.editCanvas(patch)}
      canUndo={state.canUndo}
      canRedo={state.canRedo}
      onUndo={state.undo}
      onRedo={state.redo}
      isSaving={state.isSavingCanvas}
      saveError={state.canvasError}
      onPendingQuestionStatus={(index, st) =>
        void state.setPendingQuestionStatus(index, st)
      }
      onUploadAdjunto={state.uploadAdjunto}
      onRemoveAdjunto={state.removeAdjunto}
      isUploadingAdjunto={state.isUploadingAdjunto}
      disabled={canvasDisabled}
    />
  ) : null;

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="border-b border-edge px-4 py-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <p className="text-xs text-muted">
            {authoringMode === "guided"
              ? "Una pregunta por vez, guiada por el Co-creador de skills. Vos aprobás cada paso."
              : authoringMode === "manual"
                ? "Escribí el markdown de tu skill directamente."
                : "Importá un .zip para revisión y cuarentena."}
          </p>
          {session && authoringMode === "guided" && (
            <div
              role="tablist"
              aria-label="Superficie de co-creación"
              className="inline-flex gap-1 rounded-lg border border-edge bg-surface-raised p-1"
            >
              <button
                type="button"
                role="tab"
                aria-selected={centerView === "chat"}
                onClick={() => setCenterView("chat")}
                className={cn(
                  "rounded-md px-3 py-1.5 text-small transition-colors",
                  centerView === "chat"
                    ? "bg-action text-action-text"
                    : "text-muted hover:bg-surface-hover hover:text-primary",
                )}
              >
                Conversación
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={centerView === "canvas"}
                onClick={() => setCenterView("canvas")}
                className={cn(
                  "rounded-md px-3 py-1.5 text-small transition-colors",
                  centerView === "canvas"
                    ? "bg-action text-action-text"
                    : "text-muted hover:bg-surface-hover hover:text-primary",
                )}
              >
                Lienzo
              </button>
            </div>
          )}
        </div>
        {/* Authoring sub-mode toggle (REQ-CC-1): guided chat+canvas (default),
            manual markdown draft form, or .zip import/quarantine. The
            chat/canvas toggle above only applies in guided mode (SC-CC-1.4). */}
        <div
          role="tablist"
          aria-label="Modo de creación"
          className="mt-3 inline-flex gap-1 rounded-lg border border-edge bg-surface-raised p-1"
        >
          <button
            type="button"
            role="tab"
            aria-selected={authoringMode === "guided"}
            onClick={() => setAuthoringMode("guided")}
            className={cn(
              "rounded-md px-3 py-1.5 text-small transition-colors",
              authoringMode === "guided"
                ? "bg-action text-action-text"
                : "text-muted hover:bg-surface-hover hover:text-primary",
            )}
          >
            Guiada
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={authoringMode === "manual"}
            onClick={() => setAuthoringMode("manual")}
            className={cn(
              "rounded-md px-3 py-1.5 text-small transition-colors",
              authoringMode === "manual"
                ? "bg-action text-action-text"
                : "text-muted hover:bg-surface-hover hover:text-primary",
            )}
          >
            Manual
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={authoringMode === "import"}
            onClick={() => setAuthoringMode("import")}
            className={cn(
              "rounded-md px-3 py-1.5 text-small transition-colors",
              authoringMode === "import"
                ? "bg-action text-action-text"
                : "text-muted hover:bg-surface-hover hover:text-primary",
            )}
          >
            Importar
          </button>
        </div>
      </div>

      {authoringMode === "guided" ? (
        session && centerView === "canvas" ? (
        <>
          <div className="flex flex-wrap items-center justify-between gap-2 border-b border-edge px-4 py-2">
            <ProvenanceBadge derivedFrom={session.derived_from} />
            <div className="flex items-center gap-2">
              {session.derived_from && (
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  onClick={() => void openCompare()}
                  title="Comparar el borrador derivado con la versión publicada original"
                >
                  <Icon name="diff" size={14} />
                  Comparar con el original
                </Button>
              )}
              <Button
                type="button"
                variant="ghost"
                size="sm"
                onClick={openHistory}
                title="Ver los autoguardados del lienzo"
              >
                <Icon name="history" size={14} />
                Historial
              </Button>
            </div>
          </div>
          <div className="min-h-0 flex-1 overflow-hidden">{canvas}</div>
        </>
        ) : (
        <>
          <div className="flex-1 overflow-y-auto px-4 py-3">
            {!session ? (
              <div className="mx-auto max-w-xl">
                <p className="text-sm text-primary">
                  Describí la skill que querés crear. El Co-creador de skills te va guiando
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
                  El Co-creador de skills ya juntó propósito, alcance y flujo. Confirmá el
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
                        {OPERATIONAL_TALLERES.map((operational) => (
                          <option key={operational} value={operational}>
                            {operational}
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
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <h3 className="text-sm font-medium text-primary">
                      Revisión y publicación
                    </h3>
                    <ProvenanceBadge derivedFrom={session?.derived_from} />
                  </div>
                  <p className="mt-1 text-xs text-muted">
                    Revisá el borrador tal como quedó: esto es exactamente lo
                    que se publica al aprobar.
                  </p>
                  {/* TW16 attribution legend (REQ-TW16-3): decidido = the
                      Author edited the section in the canvas; propuesto =
                      untouched; exigido = kernel invariants Demiurgos
                      enforces. */}
                  <div className="mt-3 flex flex-wrap items-center gap-2 text-xs">
                    <Badge variant="success">{ATTRIBUTION_LABELS.decidido}</Badge>
                    <Badge variant="default">{ATTRIBUTION_LABELS.propuesto}</Badge>
                    <Badge variant="info">{ATTRIBUTION_LABELS.exigido}</Badge>
                  </div>
                  <dl className="mt-3 space-y-2 text-sm">
                    {REVIEW_SECTIONS.map(({ key, label }) => {
                      const decided = touched.has(key);
                      return (
                        <div
                          key={key}
                          className="flex items-center justify-between gap-3"
                        >
                          <dt className="text-muted">{label}</dt>
                          <dd className="flex min-w-0 items-center gap-2 text-right">
                            <span className="truncate text-primary">
                              {renderReviewValue(reviewPayload[key])}
                            </span>
                            <Badge variant={decided ? "success" : "default"}>
                              {decided ? "Decidido" : "Propuesto"}
                            </Badge>
                          </dd>
                        </div>
                      );
                    })}
                    <div className="flex items-center justify-between gap-3">
                      <dt className="text-muted">Permisos</dt>
                      <dd className="flex items-center gap-2 text-right text-primary">
                        No puede declarar permisos: el sistema lo impide
                        <Badge variant="info">Exigido</Badge>
                      </dd>
                    </div>
                    <div className="flex items-center justify-between gap-3">
                      <dt className="text-muted">Dependencias</dt>
                      <dd className="text-right text-primary">
                        {dependenciesText}
                      </dd>
                    </div>
                  </dl>
                  {/* TW16 hide internals (REQ-TW16-6): draft/manifest identity
                      stays out of the default view, under "Detalles
                      avanzados". */}
                  <details className="mt-3 rounded-md border border-edge bg-surface-raised px-3 py-2">
                    <summary className="cursor-pointer text-xs font-medium text-muted">
                      Detalles avanzados
                    </summary>
                    <dl className="mt-2 space-y-1.5 text-xs">
                      {session.draft_id && (
                        <div className="flex items-center justify-between gap-3">
                          <dt className="text-muted">Borrador</dt>
                          <dd className="font-mono text-primary">
                            {shortId(session.draft_id)}
                          </dd>
                        </div>
                      )}
                      {reviewPayload.skill_id && (
                        <div className="flex items-center justify-between gap-3">
                          <dt className="text-muted">Identificador</dt>
                          <dd className="font-mono text-primary">
                            {reviewPayload.skill_id}
                          </dd>
                        </div>
                      )}
                      {reviewPayload.version && (
                        <div className="flex items-center justify-between gap-3">
                          <dt className="text-muted">Versión</dt>
                          <dd className="font-mono text-primary">
                            {reviewPayload.version}
                          </dd>
                        </div>
                      )}
                    </dl>
                  </details>
                  {state.published && (
                    <div className="mt-3 flex flex-wrap items-center justify-between gap-2 rounded-md border border-status-success/30 bg-status-success/10 px-3 py-2 text-xs text-status-success">
                      <span>
                        Publicada la versión {state.published.published.version} —{" "}
                        {state.published.published.skill_id}
                      </span>
                      <Button
                        type="button"
                        variant="secondary"
                        size="sm"
                        onClick={adaptPublished}
                        disabled={isLoading}
                        title="Derivar una versión editable de esta publicación (obligatorio para skills Oficiales)"
                      >
                        Adaptar
                      </Button>
                    </div>
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
        </>
        )
      ) : authoringMode === "manual" ? (
        <div className="min-h-0 flex-1 overflow-y-auto px-4 py-3">
          <ManualSkillCreator />
        </div>
      ) : (
        <div className="min-h-0 flex-1 overflow-y-auto px-4 py-3">
          <SkillImportPanel />
        </div>
      )}

      {historyOpen && session && (
        <DraftHistoryPanel
          entries={state.historyEntries}
          currentRevision={session.revision}
          isOpen={historyOpen}
          onClose={() => setHistoryOpen(false)}
          onRestore={(revision) => state.restoreSnapshot(revision)}
          isRestoring={state.isRestoring}
          isLoading={state.isLoadingHistory}
          error={state.restoreError}
          onRefresh={() => void state.loadHistory()}
        />
      )}

      {compareOpen && session?.derived_from && (
        <AdaptationComparePanel
          original={originalDetail}
          derivedPayload={state.draftPayload}
          derivedFrom={session.derived_from}
          isOpen={compareOpen}
          onClose={() => setCompareOpen(false)}
          canvas={canvas}
        />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Right pane — world context + draft preview + validation panel + warnings
// ---------------------------------------------------------------------------

interface CoCreationContextPanelProps {
  state: UseCoCreationReturn;
}

/** Normalize pending-question entries (legacy plain strings) for display. */
function questionEntries(payload: unknown): PendingQuestion[] {
  if (!payload || typeof payload !== "object") return [];
  const raw = (payload as { pending_questions?: unknown })
    .pending_questions;
  if (!Array.isArray(raw)) return [];
  return raw.map(normalizePendingQuestion);
}

export function CoCreationContextPanel({
  state,
}: CoCreationContextPanelProps) {
  const { session } = state;
  const issues = session?.compile_issues ?? [];
  const warnings = session?.warnings ?? [];
  const questions = questionEntries(session?.draft_payload);

  const transitionWarning = (idx: number, next: WarningState) => {
    void state.setWarningStatus(idx, next);
  };

  const transitionQuestion = (idx: number, next: WarningState) => {
    void state.setPendingQuestionStatus(idx, next);
  };

  return (
    <div className="flex h-full flex-col gap-4 overflow-y-auto px-3 py-4">
      <div className="rounded-lg border border-edge bg-surface px-3 py-3">
        <h3 className="text-xs font-medium text-muted">Contexto de mundo</h3>
        {session?.world ? (
          <p className="mt-2 text-sm text-primary">
            La sesión está ligada a «{session.world}»: el Co-creador de skills solo usa
            el contexto autorizado de ese mundo.
          </p>
        ) : (
          <p className="mt-2 text-sm text-primary">
            Skill transversal: sin vínculo a ningún mundo.
          </p>
        )}
      </div>

      {/* TW16 hide internals (REQ-TW16-6): the draft identity + compiler
          codes + compiled contract collapse under "Detalles avanzados"; the
          Author-relevant panels (world context, warnings, pending questions)
          stay visible. */}
      <details className="rounded-lg border border-edge bg-surface px-3 py-2">
        <summary className="cursor-pointer text-xs font-medium text-muted">
          Detalles avanzados
        </summary>
        <div className="mt-3 space-y-3">
          {session?.draft_id && (
            <div className="rounded-lg border border-edge bg-surface px-3 py-3">
              <h3 className="text-xs font-medium text-muted">Borrador</h3>
              <p className="mt-2 font-mono text-xs text-primary">
                {session.draft_id}
              </p>
              <p className="mt-1 text-xs text-muted">
                Materializado por el Co-creador de skills desde las respuestas
                estructuradas.
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
            <div className="flex items-center justify-between gap-2">
              <h3 className="text-xs font-medium text-muted">Validación</h3>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                onClick={() => void state.validateCanvas()}
                disabled={!session?.draft_payload || state.isValidating}
                title="Renderizar y compilar el lienzo (no crea ni publica nada)"
              >
                {state.isValidating ? <Spinner size="sm" /> : "Validar"}
              </Button>
            </div>
            {session?.compile_issues === null && !state.validation && (
              <p className="mt-2 text-xs text-muted">
                Todavía no se compiló ningún borrador.
              </p>
            )}
            {issues.length > 0 && (
              <>
                <p className="mt-2 text-xs text-status-error">
                  El borrador tiene errores de compilación. Corregí la
                  conversación y volvé a generar el borrador.
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
                        <p className="mt-0.5 font-mono text-muted">
                          {issue.field}
                        </p>
                      )}
                    </li>
                  ))}
                </ul>
              </>
            )}
            {issues.length === 0 &&
              session?.compile_issues !== null &&
              !state.validation && (
                <p className="mt-2 text-xs text-status-success">
                  El borrador compila correctamente.
                </p>
              )}
            {state.validation && (
              <div className="mt-2 space-y-2">
                {state.validation.issues.length > 0 ? (
                  <p className="text-xs text-status-error">
                    El lienzo tiene {state.validation.issues.length} problema(s)
                    de compilación.
                  </p>
                ) : (
                  <p className="text-xs text-status-success">
                    El lienzo compila correctamente.
                  </p>
                )}
                {/* Compiled contract preview: the deterministic render of the
                    payload (server-returned; validation never mutates state). */}
                <details className="rounded-md border border-edge bg-surface px-2.5 py-2">
                  <summary className="cursor-pointer text-xs font-medium text-muted">
                    Contrato compilado
                  </summary>
                  <div className="mt-2 max-h-64 overflow-y-auto rounded-md border border-edge/60 bg-surface-raised px-2 py-1">
                    <MarkdownViewer content={state.validation.source_preview} />
                  </div>
                </details>
              </div>
            )}
          </div>
        </div>
      </details>

      {/* TW12 3-state warnings (REQ-CC-13). */}
      <div className="rounded-lg border border-edge bg-surface px-3 py-3">
        <h3 className="text-xs font-medium text-muted">Advertencias</h3>
        {warnings.length === 0 ? (
          <p className="mt-2 text-xs text-muted">
            Sin advertencias en este borrador.
          </p>
        ) : (
          <ul className="mt-2 space-y-2">
            {warnings.map((warning, index) => (
              <li
                key={`${warning.code}-${index}`}
                className="rounded-md border border-edge bg-surface-raised px-2.5 py-2 text-xs"
              >
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <p className="font-medium text-primary">{warning.code}</p>
                  <Badge variant={WARNING_STATE_VARIANT[warning.state]}>
                    {WARNING_STATE_LABELS[warning.state]}
                  </Badge>
                </div>
                <p className="mt-0.5 text-primary">{warning.message}</p>
                {warning.field && (
                  <p className="mt-0.5 font-mono text-muted">{warning.field}</p>
                )}
                {warning.state === "pendiente" && (
                  <div className="mt-2 flex gap-2">
                    <Button
                      type="button"
                      variant="secondary"
                      size="sm"
                      onClick={() => transitionWarning(index, "resuelta")}
                    >
                      Marcar resuelta
                    </Button>
                    <Button
                      type="button"
                      variant="secondary"
                      size="sm"
                      onClick={() =>
                        transitionWarning(index, "aceptada_por_autor")
                      }
                    >
                      Aceptar
                    </Button>
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>

      {/* TW12 pending questions — chat-owned, Author-only transitions
          (REQ-CC-14). */}
      <div className="rounded-lg border border-edge bg-surface px-3 py-3">
        <h3 className="text-xs font-medium text-muted">Preguntas pendientes</h3>
        {questions.length === 0 ? (
          <p className="mt-2 text-xs text-muted">
            No hay preguntas pendientes.
          </p>
        ) : (
          <ul className="mt-2 space-y-2">
            {questions.map((question, index) => (
              <li
                key={`${question.text}-${index}`}
                className="rounded-md border border-edge bg-surface-raised px-2.5 py-2 text-xs"
              >
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <p className="min-w-0 flex-1 text-primary">{question.text}</p>
                  <Badge variant={WARNING_STATE_VARIANT[question.state]}>
                    {WARNING_STATE_LABELS[question.state]}
                  </Badge>
                </div>
                {question.state === "pendiente" && (
                  <div className="mt-2 flex gap-2">
                    <Button
                      type="button"
                      variant="secondary"
                      size="sm"
                      onClick={() => transitionQuestion(index, "resuelta")}
                    >
                      Marcar resuelta
                    </Button>
                    <Button
                      type="button"
                      variant="secondary"
                      size="sm"
                      onClick={() =>
                        transitionQuestion(index, "aceptada_por_autor")
                      }
                    >
                      Aceptar
                    </Button>
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}