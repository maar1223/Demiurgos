import { useCallback, useEffect, useState } from "react";
import { Button } from "@/components/atoms/Button";
import { Icon } from "@/components/atoms/Icon";
import { Spinner } from "@/components/atoms/Spinner";
import {
  authorizeChat,
  clearIdeaCaptureToken,
  discoverChatCandidates,
  getIdeaCaptureStatus,
  saveIdeaCaptureConfig,
  setIdeaCaptureToken,
} from "@/api/ideaCapture";
import type {
  ChatCandidate,
  ChatDiscoveryResult,
  IdeaCaptureConfig,
  IdeaCaptureStatus,
  LocalDevSessionStatus,
} from "@/api/types";
import { ApiError } from "@/api/types";
import { cn } from "@/lib/utils";

/** Local session controller surfaced by useLocalDevAuth — passed in so the
 *  panel stays decoupled from the hook and easy to test. */
export interface LocalAuthController {
  status: LocalDevSessionStatus | null;
  isLoading: boolean;
  error: Error | null;
  start: () => Promise<LocalDevSessionStatus>;
  logout: () => Promise<LocalDevSessionStatus>;
}

interface GroupRow {
  chat: string;
  senders: string;
}

/** The guided wizard steps. One step is visible at a time; the label doubles
 *  as the progress indicator entry (technical identifiers stay out of copy).
 *  Capture NEVER asks for a world: ideas always land in the global Taller de
 *  Ideas bank; the world is chosen later, when materializing an idea. */
const STEPS = [
  { id: "connect", label: "Conectar bot" },
  { id: "chat", label: "Detectar chat" },
  { id: "review", label: "Revisar" },
  { id: "finish", label: "Finalizar" },
] as const;

const LAST_STEP = STEPS.length - 1;

const inputClass =
  "w-full rounded-md border border-filio bg-piedra py-1.5 px-3 " +
  "text-small text-pergamino placeholder:text-sombra " +
  "focus:border-llamita focus:outline-none focus:ring-1 focus:ring-llamita/50 transition-colors";

const labelClass = "mb-1 block text-small text-tinta-desvaida";

/** Parse "1, 2, 3" / "1 2 3" into an int list; null when any token is not an
 *  integer (the backend mirrors this validation fail-closed). */
function parseIdList(text: string): number[] | null {
  const trimmed = text.trim();
  if (!trimmed) return [];
  const parts = trimmed.split(/[\s,]+/).filter(Boolean);
  const out: number[] = [];
  for (const part of parts) {
    if (!/^-?\d+$/.test(part)) return null;
    out.push(Number(part));
  }
  return out;
}

function errorText(cause: unknown, fallback: string): string {
  return cause instanceof Error ? cause.message : fallback;
}

/** Number of currently authorized chats (private + groups), reading the local
 *  form state — i.e. exactly what the Finish step would persist. */
function countAuthorized(privateText: string, groupRows: GroupRow[]): number {
  const privateIds = parseIdList(privateText);
  const privateCount = privateIds === null ? 0 : privateIds.length;
  const groupCount = groupRows.filter((row) => /^-?\d+$/.test(row.chat.trim())).length;
  return privateCount + groupCount;
}

/**
 * Profile → Integraciones → Captura de ideas.
 *
 * Temporary, single-user MVP panel for the native Hermes/Telegram idea
 * capture, guided as a compact step-by-step wizard:
 *   1. Conectar bot — token entry (masked by default), save/replace/clear.
 *   2. Detectar chat — /start instruction, read-only discovery, one-click
 *      private authorization, explicit group authorization (fail-closed).
 *   3. Revisar — bot/chat summary + collapsed advanced settings (manual IDs,
 *      groups, media limits, raw retention). The destination is ALWAYS the
 *      global Taller de Ideas: no world is chosen at capture.
 *   4. Finalizar — save confirmation, exact Hermes gateway command, next
 *      action to start capture. The panel NEVER auto-starts Telegram.
 *
 * Everything lives behind the local-dev session boundary: without an
 * authenticated loopback session the panel only shows the auth gate. The bot
 * token is stored server-side in .env and is never returned — the input is
 * masked by default and reveal/copy only apply to a value being typed.
 * Configure/discover is a migration-only flow. Production ingress is owned by
 * Hermes; the legacy serve command is never started from the panel.
 */
export function IdeaCapturePanel({ auth }: { auth: LocalAuthController }) {
  const enabled = auth.status?.enabled ?? false;
  const authenticated = auth.status?.authenticated ?? false;

  // ------------------------------------------------------------------ data
  const [status, setStatus] = useState<IdeaCaptureStatus | null>(null);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);

  const refresh = useCallback(() => {
    setLoading(true);
    setLoadError(null);
    getIdeaCaptureStatus()
      .then(setStatus)
      .catch((cause: unknown) =>
        setLoadError(errorText(cause, "No se pudo cargar la configuración")),
      )
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    if (!authenticated) return;
    refresh();
  }, [authenticated, refresh]);

  // -------------------------------------------------------------- wizard
  const [step, setStep] = useState(0);

  // ------------------------------------------------------------- form state
  const [privateText, setPrivateText] = useState("");
  const [groupRows, setGroupRows] = useState<GroupRow[]>([]);
  const [limits, setLimits] = useState({
    image_mb: 20,
    audio_mb: 50,
    audio_minutes: 5,
    raw_retention_days: 30,
  });
  const [formError, setFormError] = useState<string | null>(null);
  const [formNotice, setFormNotice] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [advancedOpen, setAdvancedOpen] = useState(false);

  // Hydrate the form whenever the server status changes.
  useEffect(() => {
    if (!status) return;
    setPrivateText(status.config.private_chat_ids.join(", "));
    setGroupRows(
      Object.entries(status.config.approved_groups).map(([chat, senders]) => ({
        chat,
        senders: senders.join(", "),
      })),
    );
    setLimits({ ...status.config.limits });
  }, [status]);

  // ---------------------------------------------------------------- token
  const hasToken = status?.has_token ?? false;
  const [tokenDraft, setTokenDraft] = useState("");
  const [tokenRevealed, setTokenRevealed] = useState(false);
  const [tokenBusy, setTokenBusy] = useState(false);
  const [tokenMessage, setTokenMessage] = useState<string | null>(null);
  const [tokenError, setTokenError] = useState<string | null>(null);
  const [confirmingClear, setConfirmingClear] = useState(false);
  const [copied, setCopied] = useState(false);

  const handleTokenSave = async () => {
    const value = tokenDraft.trim();
    if (!value || tokenBusy) return;
    setTokenBusy(true);
    setTokenMessage(null);
    setTokenError(null);
    try {
      await setIdeaCaptureToken(value);
      setTokenDraft("");
      setTokenRevealed(false);
      setStatus((prev) => (prev ? { ...prev, has_token: true } : prev));
      setTokenMessage("Token guardado en .env — no se vuelve a mostrar.");
    } catch (cause) {
      setTokenError(errorText(cause, "No se pudo guardar el token"));
    } finally {
      setTokenBusy(false);
    }
  };

  const handleCopyToken = async () => {
    if (!tokenDraft) return;
    try {
      await navigator.clipboard.writeText(tokenDraft);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      setTokenError("No se pudo copiar el token");
    }
  };

  const handleClearToken = async () => {
    if (!confirmingClear) {
      setConfirmingClear(true);
      return;
    }
    if (tokenBusy) return;
    setTokenBusy(true);
    setTokenMessage(null);
    setTokenError(null);
    try {
      await clearIdeaCaptureToken();
      setConfirmingClear(false);
      setTokenDraft("");
      setStatus((prev) => (prev ? { ...prev, has_token: false } : prev));
      setTokenMessage("Token eliminado de .env.");
    } catch (cause) {
      setTokenError(errorText(cause, "No se pudo eliminar el token"));
    } finally {
      setTokenBusy(false);
    }
  };

  // ------------------------------------------------------ Detectar mi chat
  const [discoverResult, setDiscoverResult] = useState<ChatDiscoveryResult | null>(null);
  const [discovering, setDiscovering] = useState(false);
  const [discoverError, setDiscoverError] = useState<string | null>(null);
  const [discoverRemediation, setDiscoverRemediation] = useState<{
    code: string;
    message: string;
  } | null>(null);
  const [discoverNotice, setDiscoverNotice] = useState<string | null>(null);
  const [authorizingId, setAuthorizingId] = useState<number | null>(null);
  const [groupDrafts, setGroupDrafts] = useState<
    Record<number, { senders: string; confirmed: boolean }>
  >({});

  /** Any in-flight request — nav (Back/Continuar) is disabled meanwhile. */
  const busy = tokenBusy || discovering || authorizingId !== null || saving;

  const handleDiscover = async () => {
    if (discovering) return;
    setDiscovering(true);
    setDiscoverError(null);
    setDiscoverRemediation(null);
    setDiscoverNotice(null);
    setDiscoverResult(null);
    try {
      const result = await discoverChatCandidates();
      setDiscoverResult(result);
    } catch (cause) {
      if (cause instanceof ApiError && cause.code) {
        // Backend mapped the Telegram failure to a machine-readable
        // remediation code (webhook_conflict, invalid_token, network…):
        // render dedicated guidance instead of a bare message.
        setDiscoverRemediation({
          code: cause.code,
          message:
            cause.message ||
            errorText(cause, "No se pudieron detectar los chats"),
        });
      } else {
        setDiscoverError(errorText(cause, "No se pudieron detectar los chats"));
      }
    } finally {
      setDiscovering(false);
    }
  };

  const handleAuthorizePrivate = async (candidate: ChatCandidate) => {
    if (authorizingId !== null) return;
    setAuthorizingId(candidate.id);
    setDiscoverError(null);
    setDiscoverNotice(null);
    try {
      const next = await authorizeChat({
        chat_id: candidate.id,
        chat_type: "private",
      });
      setStatus(next);
      setDiscoverNotice(
        next.message || "Chat privado autorizado. Estado actualizado.",
      );
      setDiscoverResult(null);
    } catch (cause) {
      setDiscoverError(errorText(cause, "No se pudo autorizar el chat"));
    } finally {
      setAuthorizingId(null);
    }
  };

  const handleAuthorizeGroup = async (candidate: ChatCandidate) => {
    if (authorizingId !== null) return;
    const draft = groupDrafts[candidate.id];
    const senders = parseIdList(draft?.senders ?? "");
    if (senders === null || senders.length === 0) {
      setDiscoverError("Ingresá al menos un ID de remitente entero para el grupo.");
      return;
    }
    if (!draft?.confirmed) {
      setDiscoverError(
        "Confirmá explícitamente que autorizás solo a los remitentes listados.",
      );
      return;
    }
    setAuthorizingId(candidate.id);
    setDiscoverError(null);
    setDiscoverNotice(null);
    try {
      const next = await authorizeChat({
        chat_id: candidate.id,
        chat_type: candidate.type,
        sender_ids: senders,
        confirm_group: true,
      });
      setStatus(next);
      setDiscoverNotice(
        next.message || "Grupo autorizado con remitentes explícitos. Estado actualizado.",
      );
      setDiscoverResult(null);
    } catch (cause) {
      setDiscoverError(errorText(cause, "No se pudo autorizar el grupo"));
    } finally {
      setAuthorizingId(null);
    }
  };

  // ----------------------------------------------------------- config save
  const handleSaveConfig = async () => {
    setFormError(null);
    setFormNotice(null);

    const privateChatIds = parseIdList(privateText);
    if (privateChatIds === null) {
      setFormError("IDs privados: enteros separados por coma");
      return;
    }
    const groups: Record<string, number[]> = {};
    for (const row of groupRows) {
      const chat = row.chat.trim();
      if (!chat) continue;
      if (!/^-?\d+$/.test(chat)) {
        setFormError(`Grupo "${chat}": el ID debe ser un entero`);
        return;
      }
      const senders = parseIdList(row.senders);
      if (senders === null) {
        setFormError(`Grupo ${chat}: los remitentes deben ser enteros separados por coma`);
        return;
      }
      groups[chat] = senders;
    }
    for (const [key, value] of Object.entries(limits)) {
      if (!Number.isInteger(value) || value < 1) {
        setFormError(`limits.${key}: debe ser un entero positivo`);
        return;
      }
    }

    const config: IdeaCaptureConfig = {
      private_chat_ids: privateChatIds,
      approved_groups: groups,
      limits: { ...limits },
    };
    setSaving(true);
    try {
      const next = await saveIdeaCaptureConfig(config);
      setStatus(next);
      setSaved(true);
      setFormNotice("Configuración guardada.");
    } catch (cause) {
      setFormError(errorText(cause, "No se pudo guardar la configuración"));
    } finally {
      setSaving(false);
    }
  };

  // ------------------------------------------------------------------ gate
  if (auth.isLoading) {
    return (
      <div className="flex items-center gap-2 py-6 text-small text-tinta-desvaida">
        <Spinner size="sm" /> Comprobando sesión local…
      </div>
    );
  }

  if (!enabled) {
    return (
      <div className="rounded-lg border border-filio bg-madero p-4">
        <p className="text-small text-tinta-desvaida">
          La configuración de captura de ideas requiere la sesión local.
          Activá <code className="text-plata">DEMIURGOS_AUTH_MODE=local-dev</code>{" "}
          en <code className="text-plata">.env</code> para probarla.
        </p>
      </div>
    );
  }

  if (!authenticated) {
    return (
      <div className="rounded-lg border border-filio bg-madero p-4">
        <p className="text-small text-tinta-desvaida">
          Sesión local no iniciada. Iniciá sesión para ver y editar la
          configuración de captura de ideas.
        </p>
        <Button
          variant="primary"
          onClick={() => void auth.start()}
          className="mt-3"
        >
          Iniciar sesión local
        </Button>
        {auth.error && (
          <p className="mt-2 text-small text-sangre">{auth.error.message}</p>
        )}
      </div>
    );
  }

  const failClosed = countAuthorized(privateText, groupRows) === 0;
  // Capture never asks for a world: only the bot token gates the first step.
  const canContinue = step === 0 ? hasToken : true;

  const goNext = () => {
    if (!canContinue || busy) return;
    setFormError(null);
    setFormNotice(null);
    setStep((prev) => Math.min(prev + 1, LAST_STEP));
  };
  const goBack = () => {
    if (busy) return;
    setFormError(null);
    setFormNotice(null);
    setStep((prev) => Math.max(prev - 1, 0));
  };

  return (
    <div className="mx-auto w-full max-w-2xl space-y-5">
      {/* Operational distinction: discovery is migration-only; Hermes owns ingress. */}
      <div className="rounded-lg border border-filio bg-madero p-3 text-small text-tinta-desvaida">
        <span className="font-medium text-pergamino">Cómo funciona:</span>{" "}
         configurá el bot y descubrí tu chat mientras Hermes está detenido. La{" "}
         <strong>captura de producción la inicia Hermes</strong> cuando ejecutes
         el comando — el panel nunca inicia Telegram automáticamente.
      </div>

      {loadError && (
        <div className="rounded-lg border border-sangre/40 bg-sangre/10 p-3 text-small text-sangre">
          {loadError}
        </div>
      )}

      {loading && !status && (
        <div className="flex items-center gap-2 py-4 text-small text-tinta-desvaida">
          <Spinner size="sm" /> Cargando configuración…
        </div>
      )}

      {status && (
        <>
          {/* --------------------------------------------------- progress */}
          <nav
            aria-label="Progreso de la configuración"
            className="flex items-center gap-1"
          >
            {STEPS.map((entry, index) => {
              const state =
                index < step ? "done" : index === step ? "current" : "todo";
              return (
                <div key={entry.id} className="flex flex-1 items-center gap-1">
                  <div
                    className={cn(
                      "flex min-w-0 flex-1 flex-col items-center gap-1 text-center",
                      index > 0 && "ml-1",
                    )}
                    aria-current={index === step ? "step" : undefined}
                  >
                    <span
                      className={cn(
                        "flex h-7 w-7 shrink-0 items-center justify-center rounded-full border text-xs font-medium",
                        state === "done" &&
                          "border-musgo bg-musgo/15 text-musgo",
                        state === "current" &&
                          "border-llamita bg-llamita/15 text-llamita",
                        state === "todo" &&
                          "border-filio bg-piedra text-tinta-desvaida",
                      )}
                    >
                      {state === "done" ? <Icon name="check" size={14} /> : index + 1}
                    </span>
                    <span
                      className={cn(
                        "text-xs leading-tight",
                        state === "current"
                          ? "text-pergamino"
                          : state === "done"
                            ? "text-musgo"
                            : "text-tinta-desvaida",
                      )}
                    >
                      {entry.label}
                    </span>
                  </div>
                  {index < LAST_STEP && (
                    <div
                      aria-hidden="true"
                      className={cn(
                        "mb-5 h-px w-3 shrink-0",
                        index < step ? "bg-musgo/50" : "bg-filio",
                      )}
                    />
                  )}
                </div>
              );
            })}
          </nav>

          {/* -------------------------------------------------- step content */}
          <div className="rounded-lg border border-filio bg-madero p-5">
            {step === 0 && (
              <section aria-label="Conectar bot">
                <h3 className="font-heading text-body text-pergamino">
                  Conectá tu bot de Telegram
                </h3>
                <p className="mt-1 text-small text-tinta-desvaida">
                  {hasToken
                    ? "Token configurado en .env. No se vuelve a mostrar: pegá un valor nuevo para reemplazarlo."
                    : "Pegá el token de BotFather. Se guarda solo en el .env del servidor y nunca se expone."}
                </p>
                <div className="mt-3 flex items-center gap-2">
                  <input
                    type={tokenRevealed ? "text" : "password"}
                    value={tokenDraft}
                    onChange={(event) => {
                      setTokenDraft(event.target.value);
                      setConfirmingClear(false);
                    }}
                    placeholder={
                      hasToken
                        ? "•••••••• (configurado — valor oculto)"
                        : "123456789:AA… (token de BotFather)"
                    }
                    autoComplete="off"
                    spellCheck={false}
                    aria-label="Token del bot"
                    className={inputClass}
                  />
                  <button
                    type="button"
                    onClick={() => setTokenRevealed((prev) => !prev)}
                    disabled={!tokenDraft || tokenBusy}
                    aria-label={tokenRevealed ? "Ocultar token" : "Mostrar token"}
                    className="shrink-0 rounded-md border border-filio bg-piedra px-2 py-1.5 text-small text-plata hover:text-pergamino disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {tokenRevealed ? "Ocultar" : "Mostrar"}
                  </button>
                  <button
                    type="button"
                    onClick={() => void handleCopyToken()}
                    disabled={!tokenDraft || tokenBusy}
                    aria-label="Copiar token"
                    className="shrink-0 rounded-md border border-filio bg-piedra px-2 py-1.5 text-small text-plata hover:text-pergamino disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {copied ? "Copiado" : "Copiar"}
                  </button>
                </div>
                <div className="mt-3 flex items-center gap-2">
                  <Button
                    variant="primary"
                    onClick={() => void handleTokenSave()}
                    disabled={!tokenDraft.trim() || tokenBusy}
                  >
                    {tokenBusy ? "Guardando…" : hasToken ? "Reemplazar token" : "Guardar token"}
                  </Button>
                  {hasToken && (
                    <Button
                      variant="secondary"
                      onClick={() => void handleClearToken()}
                      disabled={tokenBusy}
                    >
                      {confirmingClear ? "¿Confirmar eliminación?" : "Eliminar token"}
                    </Button>
                  )}
                </div>
                {tokenMessage && (
                  <p className="mt-3 text-small text-musgo">{tokenMessage}</p>
                )}
                {tokenError && (
                  <p className="mt-3 text-small text-sangre">{tokenError}</p>
                )}
              </section>
            )}

            {step === 1 && (
              <section aria-label="Detectar chat">
                <h3 className="font-heading text-body text-pergamino">
                  Detectá el chat que recibirá tus ideas
                </h3>
                <p className="mt-1 text-small text-tinta-desvaida">
                  Enviá <code className="text-plata">/start</code> (o cualquier
                  mensaje) a tu bot en Telegram y después tocá{" "}
                  <em>Ya lo envié — Detectar chat</em>. La detección es de solo
                  lectura: no confirma ni consume mensajes pendientes, y no
                  muestra el contenido de los mensajes.
                </p>
                <div className="mt-3 flex items-center gap-2">
                  <Button
                    variant="secondary"
                    onClick={() => void handleDiscover()}
                    disabled={discovering}
                  >
                    {discovering ? "Detectando…" : "Ya lo envié — Detectar chat"}
                  </Button>
                  {discovering && <Spinner size="sm" />}
                </div>
                {discoverError && (
                  <p className="mt-3 text-small text-sangre">{discoverError}</p>
                )}
                {discoverRemediation && (
                  <div
                    role="alert"
                    className="mt-3 rounded-lg border border-llamita/40 bg-llamita/10 p-3 text-small"
                  >
                    <p className="text-llama-alta">
                      <strong>No se pudieron detectar los chats.</strong>
                    </p>
                    <p className="mt-1 text-tinta-desvaida">
                      {discoverRemediation.message}
                    </p>
                    {discoverRemediation.code === "webhook_conflict" && (
                      <div className="mt-2">
                        <p className="text-tinta-desvaida">
                          <strong>Webhook activo:</strong> Telegram no permite
                          usar getUpdates mientras el bot tenga un webhook
                          configurado (suele quedar de una configuración
                          anterior). Para desbloquear la detección eliminá el
                          webhook manualmente:
                        </p>
                        <ul className="mt-1 list-disc pl-5 text-tinta-desvaida">
                          <li>
                            En <strong>BotFather</strong>: <code>/deletewebhook</code>
                          </li>
                          <li>
                            O con el método <code>deleteWebhook</code> de la Bot
                            API usando el token de este panel.
                          </li>
                        </ul>
                        <p className="mt-2 text-tinta-desvaida">
                          Este panel nunca borra el webhook automáticamente: la
                          eliminación es una decisión tuya. Cuando lo hayas
                          eliminado, tocá <em>Ya lo envié — Detectar chat</em>{" "}
                          de nuevo.
                        </p>
                      </div>
                    )}
                  </div>
                )}
                {discoverNotice && (
                  <p className="mt-3 text-small text-musgo">{discoverNotice}</p>
                )}
                {discoverResult && (
                  <div className="mt-3">
                    {discoverResult.candidates.length === 0 ? (
                      <div className="rounded-lg border border-filio bg-piedra p-3 text-small text-tinta-desvaida">
                        {discoverResult.message}
                      </div>
                    ) : (
                      <ul className="space-y-2">
                        {discoverResult.candidates.map((candidate) =>
                          candidate.kind === "private" ? (
                            <li
                              key={candidate.id}
                              className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-filio bg-piedra p-3"
                            >
                              <div className="min-w-0">
                                <p className="truncate text-small text-pergamino">
                                  {candidate.title || "Chat privado (sin nombre)"}
                                </p>
                                <p className="text-xs text-tinta-desvaida">
                                  Chat privado — autorización de un clic
                                </p>
                              </div>
                              <Button
                                variant="primary"
                                onClick={() => void handleAuthorizePrivate(candidate)}
                                disabled={authorizingId !== null}
                              >
                                {authorizingId === candidate.id
                                  ? "Autorizando…"
                                  : "Autorizar"}
                              </Button>
                            </li>
                          ) : (
                            <li
                              key={candidate.id}
                              className="rounded-md border border-filio bg-piedra p-3"
                            >
                              <p className="truncate text-small text-pergamino">
                                {candidate.title || "Grupo (sin título)"}
                              </p>
                              <p className="text-xs text-tinta-desvaida">
                                Grupo — la autorización es explícita (fail-closed)
                              </p>
                              <div className="mt-2 space-y-2">
                                <input
                                  type="text"
                                  value={groupDrafts[candidate.id]?.senders ?? ""}
                                  onChange={(event) =>
                                    setGroupDrafts((prev) => ({
                                      ...prev,
                                      [candidate.id]: {
                                        senders: event.target.value,
                                        confirmed:
                                          prev[candidate.id]?.confirmed ?? false,
                                      },
                                    }))
                                  }
                                  placeholder="IDs de remitentes autorizados"
                                  aria-label={`Remitentes del grupo ${candidate.id}`}
                                  className={inputClass}
                                />
                                <label className="flex items-center gap-2 text-small text-tinta-desvaida">
                                  <input
                                    type="checkbox"
                                    checked={groupDrafts[candidate.id]?.confirmed ?? false}
                                    onChange={(event) =>
                                      setGroupDrafts((prev) => ({
                                        ...prev,
                                        [candidate.id]: {
                                          senders: prev[candidate.id]?.senders ?? "",
                                          confirmed: event.target.checked,
                                        },
                                      }))
                                    }
                                    aria-label={`Confirmar autorización del grupo ${candidate.id}`}
                                    className="accent-llamita"
                                  />
                                  Confirmo que autorizo solo a estos remitentes
                                </label>
                                <Button
                                  variant="secondary"
                                  onClick={() => void handleAuthorizeGroup(candidate)}
                                  disabled={authorizingId !== null}
                                >
                                  {authorizingId === candidate.id
                                    ? "Autorizando…"
                                    : "Autorizar grupo"}
                                </Button>
                              </div>
                            </li>
                          ),
                        )}
                      </ul>
                    )}
                  </div>
                )}
                {failClosed ? (
                  <div className="mt-3 rounded-lg border border-llamita/40 bg-llamita/10 p-3 text-small text-llama-alta">
                     <strong>Fail-closed:</strong> con listas de autorización
                     vacías se rechaza TODO el ingreso y Hermes no arranca la captura.
                    Autorizá explícitamente un chat privado o un grupo (o usá la
                    entrada manual en <em>Revisar → Configuración avanzada</em>).
                  </div>
                ) : (
                  <p className="mt-3 text-small text-musgo">
                    Autorización activa: {countAuthorized(privateText, groupRows)}{" "}
                    chat(s) autorizado(s).
                  </p>
                )}
                <p className="mt-3 text-small text-tinta-desvaida">
                  ¿Problemas o necesitás el ID numérico? Podés usar la entrada
                  manual avanzada en <em>Revisar → Configuración avanzada</em>.
                </p>
              </section>
            )}

            {step === 2 && (
              <section aria-label="Revisar">
                <h3 className="font-heading text-body text-pergamino">
                  Revisá tu configuración
                </h3>
                <dl className="mt-3 space-y-2 text-small">
                  <div className="flex items-center justify-between gap-3">
                    <dt className="text-tinta-desvaida">Bot de Telegram</dt>
                    <dd className="text-pergamino">
                      {hasToken ? "Token configurado" : "Sin token"}
                    </dd>
                  </div>
                  <div className="flex items-center justify-between gap-3">
                    <dt className="text-tinta-desvaida">Chat autorizado</dt>
                    <dd className="text-pergamino">
                      {failClosed
                        ? "Ninguno (fail-closed)"
                        : `${countAuthorized(privateText, groupRows)} chat(s)`}
                    </dd>
                  </div>
                  <div className="flex items-center justify-between gap-3">
                    <dt className="text-tinta-desvaida">Destino</dt>
                    <dd className="text-pergamino">Taller de Ideas</dd>
                  </div>
                </dl>
                <p className="mt-3 text-small text-tinta-desvaida">
                  Las ideas capturadas van siempre al <strong>Taller de Ideas</strong>{" "}
                  global: no elegís mundo al capturar. El mundo se define recién
                  cuando materializás una idea desde el taller.
                </p>

                {failClosed && (
                  <div className="mt-3 rounded-lg border border-llamita/40 bg-llamita/10 p-3 text-small text-llama-alta">
                     <strong>Fail-closed:</strong> sin chats autorizados se
                     rechaza TODO el ingreso y Hermes no arranca la captura.
                  </div>
                )}
                {!status.validation.ok && (
                  <div className="mt-3 rounded-lg border border-sangre/40 bg-sangre/10 p-3 text-small text-sangre">
                    <strong>Errores de validación:</strong>
                    <ul className="mt-1 list-disc pl-5">
                      {status.validation.errors.map((error) => (
                        <li key={error}>{error}</li>
                      ))}
                    </ul>
                  </div>
                )}

                {/* ------------------------- advanced (collapsed by default) */}
                <div className="mt-4 rounded-md border border-filio bg-piedra">
                  <button
                    type="button"
                    onClick={() => setAdvancedOpen((open) => !open)}
                    aria-expanded={advancedOpen}
                    aria-controls="ic-advanced-panel"
                    className="flex w-full items-center justify-between gap-2 px-3 py-2 text-left text-small font-medium text-plata hover:text-pergamino"
                  >
                    Configuración avanzada (opcional)
                    <Icon
                      name={advancedOpen ? "chevron-down" : "chevron-right"}
                      size={16}
                    />
                  </button>
                  {advancedOpen && (
                    <div
                      id="ic-advanced-panel"
                      className="space-y-3 border-t border-filio p-3"
                    >
                      <div>
                        <label htmlFor="ic-private-chats" className={labelClass}>
                          Chats privados autorizados
                        </label>
                        <input
                          id="ic-private-chats"
                          type="text"
                          value={privateText}
                          onChange={(event) => setPrivateText(event.target.value)}
                          placeholder="123456789, 555000111"
                          className={inputClass}
                        />
                      </div>

                      <div>
                        <span className={labelClass}>Grupos autorizados (chat → remitentes)</span>
                        <div className="space-y-2">
                          {groupRows.map((row, index) => (
                            <div key={index} className="flex items-center gap-2">
                              <input
                                type="text"
                                value={row.chat}
                                onChange={(event) => {
                                  const next = [...groupRows];
                                  next[index] = { ...next[index], chat: event.target.value };
                                  setGroupRows(next);
                                }}
                                placeholder="ID del grupo"
                                aria-label={`ID del grupo ${index + 1}`}
                                className={inputClass}
                              />
                              <input
                                type="text"
                                value={row.senders}
                                onChange={(event) => {
                                  const next = [...groupRows];
                                  next[index] = { ...next[index], senders: event.target.value };
                                  setGroupRows(next);
                                }}
                                placeholder="IDs de remitentes autorizados"
                                aria-label={`Remitentes del grupo ${index + 1}`}
                                className={inputClass}
                              />
                              <button
                                type="button"
                                onClick={() =>
                                  setGroupRows(groupRows.filter((_, i) => i !== index))
                                }
                                aria-label={`Quitar grupo ${index + 1}`}
                                className="shrink-0 rounded-md p-2 text-sangre hover:bg-piedra"
                              >
                                <Icon name="trash" size={16} />
                              </button>
                            </div>
                          ))}
                          <Button
                            variant="secondary"
                            onClick={() => setGroupRows([...groupRows, { chat: "", senders: "" }])}
                          >
                            <Icon name="plus" size={14} /> Agregar grupo
                          </Button>
                        </div>
                      </div>

                      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
                        {(
                          [
                            ["limits.image_mb", "Límite imagen (MB)", limits.image_mb],
                            ["limits.audio_mb", "Límite audio (MB)", limits.audio_mb],
                            ["limits.audio_minutes", "Audio (min)", limits.audio_minutes],
                            ["limits.raw_retention_days", "Retención bruta (días)", limits.raw_retention_days],
                          ] as const
                        ).map(([key, label, value]) => (
                          <div key={key}>
                            <label htmlFor={key} className={labelClass}>
                              {label}
                            </label>
                            <input
                              id={key}
                              type="number"
                              min={1}
                              step={1}
                              value={value}
                              onChange={(event) =>
                                setLimits((prev) => ({
                                  ...prev,
                                  [key.split(".")[1]]: Number(event.target.value),
                                }))
                              }
                              className={inputClass}
                            />
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>

                {formError && (
                  <p className="mt-3 text-small text-sangre">{formError}</p>
                )}
                {formNotice && (
                  <p className="mt-3 text-small text-musgo">{formNotice}</p>
                )}
              </section>
            )}

            {step === 3 && (
              <section aria-label="Finalizar">
                <h3 className="font-heading text-body text-pergamino">
                  Finalizá y arrancá la captura
                </h3>
                <p className="mt-1 text-small text-tinta-desvaida">
                  Guardá la configuración y después ejecutá el comando del
                  gateway Hermes en tu terminal para empezar a capturar ideas.
                  Tus ideas se guardan en el <strong>Taller de Ideas</strong>{" "}
                  (sin elegir mundo). El panel no inicia Telegram automáticamente.
                </p>
                <div className="mt-3">
                  <Button
                    variant="primary"
                    onClick={() => void handleSaveConfig()}
                    disabled={saving}
                  >
                    {saving ? "Guardando…" : "Guardar configuración"}
                  </Button>
                </div>
                {formError && (
                  <p className="mt-3 text-small text-sangre">{formError}</p>
                )}
                {formNotice && (
                  <p className="mt-3 text-small text-musgo">{formNotice}</p>
                )}
                {saved && status && (
                  <div className="mt-3 space-y-3">
                    <div className="rounded-lg border border-musgo/40 bg-musgo/10 p-3 text-small text-musgo">
                      <strong>Listo.</strong> La configuración quedó guardada.
                      Ahora arrancá la captura ejecutando el comando exacto:
                    </div>
                    <pre className="overflow-x-auto rounded-md border border-filio bg-cripta p-3 text-small text-musgo">
                      {status.serve.command}
                    </pre>
                    {status.serve.runnable ? (
                      <p className="text-small text-musgo">
                        Listo para ejecutar Hermes.
                      </p>
                    ) : (
                      <ul className="list-disc pl-5 text-small text-sangre">
                        {status.serve.blocked_reasons.map((reason) => (
                          <li key={reason}>{reason}</li>
                        ))}
                      </ul>
                    )}
                    <p className="text-small text-tinta-desvaida">
                      <strong>Próximo paso:</strong> ejecutá el comando en tu
                      terminal. Hermes debe ser el único supervisor de Telegram;
                      no ejecutes el serve de compatibilidad en paralelo.
                    </p>
                  </div>
                )}
                {status && (
                  <div className="mt-4 rounded-md border border-filio bg-piedra p-3">
                    <h4 className="font-heading text-small text-pergamino">
                      Limitaciones actuales
                    </h4>
                    <ul className="mt-2 list-disc pl-5 text-small text-tinta-desvaida">
                      {status.limitations.map((limitation) => (
                        <li key={limitation} className="mt-1">
                          {limitation}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </section>
            )}
          </div>

          {/* ----------------------------------------------------- footer nav */}
          <div className="flex items-center justify-between">
            <Button
              variant="ghost"
              onClick={goBack}
              disabled={step === 0 || busy}
            >
              <Icon name="chevron-left" size={16} /> Volver
            </Button>
            {step < LAST_STEP && (
              <div className="flex flex-col items-end gap-1">
                <Button
                  variant="primary"
                  onClick={goNext}
                  disabled={!canContinue || busy}
                >
                  Continuar <Icon name="chevron-right" size={16} />
                </Button>
                {step === 0 && !hasToken && (
                  <span className="text-xs text-tinta-desvaida">
                    Guardá el token para continuar.
                  </span>
                )}
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}
