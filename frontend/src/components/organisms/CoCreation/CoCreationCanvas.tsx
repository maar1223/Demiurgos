import { useState } from "react";
import { Button } from "@/components/atoms/Button";
import { Badge } from "@/components/atoms/Badge";
import { Icon } from "@/components/atoms/Icon";
import { Spinner } from "@/components/atoms/Spinner";
import type {
  DraftPayload,
  PendingQuestion,
  WarningState,
} from "@/api/types";

/** Warning/pending-question state -> human label (Spanish voseo UI copy). */
export const WARNING_STATE_LABELS: Record<WarningState, string> = {
  pendiente: "Pendiente",
  resuelta: "Resuelta",
  aceptada_por_autor: "Aceptada por el autor",
};

/** State -> Badge variant for pending questions and warnings. */
export const WARNING_STATE_VARIANT: Record<WarningState, "default" | "success" | "info" | "warning"> = {
  pendiente: "warning",
  resuelta: "success",
  aceptada_por_autor: "info",
};

/** Legacy wire entries may be plain strings (chat-appended); normalize them to
 *  the typed `{text, state}` shape with the default `pendiente` state. */
export function normalizePendingQuestion(
  entry: PendingQuestion | string,
): PendingQuestion {
  return typeof entry === "string"
    ? { text: entry, state: "pendiente" }
    : entry;
}

interface ListEditorProps {
  label: string;
  items: string[];
  onChange: (next: string[]) => void;
  disabled?: boolean;
}

/** One branch/rule list editor: editable items + remove, plus an add row.
 *  The deterministic template renders branches/rules as adjacent bullet lists
 *  (documented lossy reverse-parse boundary); this editor lets the Author
 *  reclassify items between the two lists after derivation. */
function ListEditor({ label, items, onChange, disabled }: ListEditorProps) {
  const [draft, setDraft] = useState("");

  const update = (index: number, value: string) => {
    onChange(items.map((item, i) => (i === index ? value : item)));
  };

  const remove = (index: number) => {
    onChange(items.filter((_, i) => i !== index));
  };

  const add = () => {
    const trimmed = draft.trim();
    if (!trimmed) return;
    onChange([...items, trimmed]);
    setDraft("");
  };

  return (
    <div>
      <div className="space-y-2">
        {items.map((item, index) => (
          <div key={`${label}-${index}`} className="flex items-center gap-2">
            <input
              type="text"
              value={item}
              onChange={(event) => update(index, event.target.value)}
              disabled={disabled}
              aria-label={`${label} ${index + 1}`}
              className="min-w-0 flex-1 rounded-lg border border-edge bg-surface px-3 py-2 text-sm text-primary focus:border-action focus:outline-none disabled:opacity-60"
            />
            {!disabled && (
              <button
                type="button"
                onClick={() => remove(index)}
                aria-label={`Quitar ${label.toLowerCase()} ${index + 1}`}
                className="shrink-0 rounded-md border border-edge p-1.5 text-icon-muted transition-colors hover:border-status-error/40 hover:text-status-error"
              >
                <Icon name="trash" size={14} />
              </button>
            )}
          </div>
        ))}
      </div>
      {!disabled && (
        <div className="mt-2 flex items-center gap-2">
          <input
            type="text"
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                event.preventDefault();
                add();
              }
            }}
            placeholder={`Añadir ${label.toLowerCase()}...`}
            aria-label={`Nueva ${label.toLowerCase()}`}
            className="min-w-0 flex-1 rounded-lg border border-edge bg-surface px-3 py-2 text-sm text-primary placeholder:text-muted focus:border-action focus:outline-none"
          />
          <Button
            type="button"
            variant="secondary"
            size="sm"
            onClick={add}
            disabled={!draft.trim()}
            aria-label={`Añadir ${label.toLowerCase()}`}
          >
            Añadir
          </Button>
        </div>
      )}
    </div>
  );
}

interface CoCreationCanvasProps {
  /** The editable structured draft (REQ-CC-11). */
  payload: DraftPayload | null;
  /** Author section edit -> debounced autosave via the shared hook. */
  onChange: (patch: Partial<DraftPayload>) => void;
  canUndo: boolean;
  canRedo: boolean;
  onUndo: () => void;
  onRedo: () => void;
  isSaving: boolean;
  saveError: string | null;
  /** Author-only pending-question transition (REQ-CC-14); entries are
   *  read-only here — only state buttons are rendered. */
  onPendingQuestionStatus: (index: number, state: WarningState) => void;
  /** Review/complete phases freeze the canvas (matching the disabled chat). */
  disabled?: boolean;
}

/**
 * TW12 per-section editable structured draft (REQ-CC-11).
 *
 * The canvas is the STRUCTURE surface (name/description/purpose/scope/main
 * flow as textareas; branches/rules as list editors); the chat remains the
 * INTENTION surface. Edits flow through the shared hook's debounced autosave
 * -> `PUT /canvas` (revision-guarded merge, REQ-CC-23 envelope keys). The
 * canvas NEVER authors `pending_questions` (REQ-CC-14) and never emits
 * authority-key content (REQ-CC-7).
 */
export function CoCreationCanvas({
  payload,
  onChange,
  canUndo,
  canRedo,
  onUndo,
  onRedo,
  isSaving,
  saveError,
  onPendingQuestionStatus,
  disabled = false,
}: CoCreationCanvasProps) {
  if (!payload) {
    return (
      <div className="flex h-full items-center justify-center p-6">
        <p className="text-sm text-muted">
          El lienzo todavía no tiene contenido. Conversá con el Co-creador de skills para
          empezar a estructurar el borrador.
        </p>
      </div>
    );
  }

  const questions = payload.pending_questions.map(normalizePendingQuestion);

  const textareaClass =
    "mt-1 w-full resize-none rounded-lg border border-edge bg-surface px-3 py-2 text-sm text-primary placeholder:text-muted focus:border-action focus:outline-none disabled:opacity-60";

  return (
    <div className="flex h-full flex-col">
      {/* Undo/redo toolbar + autosave status (REQ-CC-15 in-memory stack). */}
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-edge px-4 py-2">
        <div className="flex items-center gap-2">
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={onUndo}
            disabled={!canUndo || disabled}
            aria-label="Deshacer edición"
          >
            <Icon name="chevron-left" size={14} />
            Deshacer
          </Button>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={onRedo}
            disabled={!canRedo || disabled}
            aria-label="Rehacer edición"
          >
            Rehacer
            <Icon name="corner-up-right" size={14} />
          </Button>
        </div>
        <div className="flex items-center gap-2 text-xs">
          {isSaving ? (
            <span className="flex items-center gap-1.5 text-muted">
              <Spinner size="sm" /> Guardando…
            </span>
          ) : (
            <span className="flex items-center gap-1 text-status-success">
              <Icon name="check" size={14} /> Guardado
            </span>
          )}
          {saveError && (
            <span role="alert" className="text-status-error">
              {saveError}
            </span>
          )}
        </div>
      </div>

      <div className="min-h-0 flex-1 space-y-5 overflow-y-auto px-4 py-4">
        <div className="grid gap-4">
          <label className="block text-xs text-muted">
            Nombre
            <input
              type="text"
              value={payload.name}
              onChange={(event) => onChange({ name: event.target.value })}
              disabled={disabled}
              className="mt-1 w-full rounded-lg border border-edge bg-surface px-3 py-2 text-sm text-primary placeholder:text-muted focus:border-action focus:outline-none disabled:opacity-60"
            />
          </label>
          <label className="block text-xs text-muted">
            Descripción
            <textarea
              value={payload.description}
              onChange={(event) => onChange({ description: event.target.value })}
              disabled={disabled}
              rows={2}
              className={textareaClass}
            />
          </label>
          <label className="block text-xs text-muted">
            Propósito
            <textarea
              value={payload.purpose}
              onChange={(event) => onChange({ purpose: event.target.value })}
              disabled={disabled}
              rows={3}
              className={textareaClass}
            />
          </label>
          <label className="block text-xs text-muted">
            Alcance
            <textarea
              value={payload.scope}
              onChange={(event) => onChange({ scope: event.target.value })}
              disabled={disabled}
              rows={3}
              className={textareaClass}
            />
          </label>
          <label className="block text-xs text-muted">
            Flujo principal
            <textarea
              value={payload.main_flow}
              onChange={(event) => onChange({ main_flow: event.target.value })}
              disabled={disabled}
              rows={4}
              className={textareaClass}
            />
          </label>
        </div>

        <div className="grid gap-4 sm:grid-cols-2">
          <div className="rounded-lg border border-edge bg-surface px-3 py-3">
            <h3 className="text-xs font-medium text-muted">Ramas</h3>
            <div className="mt-2">
              <ListEditor
                label="Rama"
                items={payload.branches}
                onChange={(branches) => onChange({ branches })}
                disabled={disabled}
              />
            </div>
          </div>
          <div className="rounded-lg border border-edge bg-surface px-3 py-3">
            <h3 className="text-xs font-medium text-muted">Reglas</h3>
            <div className="mt-2">
              <ListEditor
                label="Regla"
                items={payload.rules}
                onChange={(rules) => onChange({ rules })}
                disabled={disabled}
              />
            </div>
          </div>
        </div>

        {/* Pending questions — chat-appended, read-only, Author-only state
            transitions (REQ-CC-14). */}
        <div className="rounded-lg border border-edge bg-surface px-3 py-3">
          <h3 className="text-xs font-medium text-muted">
            Preguntas pendientes
          </h3>
          {questions.length === 0 ? (
            <p className="mt-2 text-xs text-muted">
              No hay preguntas pendientes. El Co-creador de skills las agrega durante la
              conversación.
            </p>
          ) : (
            <ul className="mt-2 space-y-2">
              {questions.map((question, index) => (
                <li
                  key={`${question.text}-${index}`}
                  className="rounded-md border border-edge bg-surface-raised px-3 py-2"
                >
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <p className="min-w-0 flex-1 text-sm text-primary">
                      {question.text}
                    </p>
                    <Badge variant={WARNING_STATE_VARIANT[question.state]}>
                      {WARNING_STATE_LABELS[question.state]}
                    </Badge>
                  </div>
                  {question.state === "pendiente" && !disabled && (
                    <div className="mt-2 flex gap-2">
                      <Button
                        type="button"
                        variant="secondary"
                        size="sm"
                        onClick={() =>
                          onPendingQuestionStatus(index, "resuelta")
                        }
                      >
                        Marcar resuelta
                      </Button>
                      <Button
                        type="button"
                        variant="secondary"
                        size="sm"
                        onClick={() =>
                          onPendingQuestionStatus(index, "aceptada_por_autor")
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
    </div>
  );
}

export default CoCreationCanvas;