import { useCallback, useEffect, useRef, useState } from "react";
import {
  clearTelegramToken,
  getTelegramStatus,
  setTelegramToken,
  testTelegramConnection,
} from "@/api/telegram";
import type { TelegramStatus } from "@/api/types";
import { Button } from "@/components/atoms/Button";
import { Spinner } from "@/components/atoms/Spinner";
import { useLocalDevAuth } from "@/hooks/useLocalDevAuth";

const inputClass =
  "w-full rounded-md border border-filio bg-piedra py-1.5 px-3 text-small text-pergamino " +
  "placeholder:text-sombra focus:border-llamita focus:outline-none focus:ring-1 focus:ring-llamita/50";
const labelClass = "mb-1 block text-small text-tinta-desvaida";

const STATE_META: Record<
  TelegramStatus["state"],
  { label: string; className: string }
> = {
  pending: { label: "Pendiente", className: "text-tinta-desvaida" },
  requires_connection: { label: "Requiere conexión", className: "text-llamita" },
  configured: { label: "Configurado", className: "text-musgo" },
  error: { label: "Error", className: "text-sangre" },
};

/** Client-side remediation guidance for the backend's stable error codes
 *  (mirrors the message the server returns on test-connection; here it also
 *  covers a status loaded with a stale error_code). */
const ERROR_GUIDANCE: Record<string, string> = {
  invalid_token: "El token guardado no es válido o fue revocado. Guardá un token nuevo.",
  network: "No se pudo contactar la API de Telegram. Verificá la conexión e intentá de nuevo.",
  telegram_http: "Telegram respondió con un error HTTP. Reintentá en unos segundos.",
  telegram_api: "Telegram no validó el token. Revisalo e intentá de nuevo.",
};

function errorText(cause: unknown, fallback: string): string {
  return cause instanceof Error ? cause.message : fallback;
}

/**
 * ONB-3.3 — resumable Telegram card panel (WU-3b2).
 *
 * The bot token is WRITE-ONLY: it lives only in the transient input value,
 * is sent to the backend PUT body, and is cleared immediately after saving.
 * The stored value is never rendered, logged, or kept in React state — the
 * status payload only exposes `has_token`. Card state comes from the ONB-3.3
 * backend's real evidence (token presence + last getMe test), so the panel
 * never overstates readiness: offline maps to requires_connection, invalid
 * tokens map to error, and a fresh token stays requires_connection until the
 * connection test succeeds.
 */
export function TelegramCard() {
  const auth = useLocalDevAuth(true);
  const authenticated = auth.status?.authenticated ?? false;
  const [status, setStatus] = useState<TelegramStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [tokenDraft, setTokenDraft] = useState("");
  const [confirmClear, setConfirmClear] = useState(false);
  const tokenInputRef = useRef<HTMLInputElement>(null);

  const refresh = useCallback(() => {
    if (!authenticated) {
      // No session → nothing to load; the render gates handle the message.
      setLoading(false);
      return;
    }
    setLoading(true);
    setLoadError(null);
    void getTelegramStatus()
      .then(setStatus)
      .catch((cause: unknown) =>
        setLoadError(errorText(cause, "No se pudo cargar el estado de Telegram")),
      )
      .finally(() => setLoading(false));
  }, [authenticated]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  if (auth.isLoading || (loading && !status)) {
    return (
      <div className="flex items-center gap-2 py-6 text-small text-tinta-desvaida">
        <Spinner size="sm" /> Cargando estado de Telegram…
      </div>
    );
  }
  if (!auth.status?.enabled) {
    return (
      <p className="rounded-lg border border-filio bg-madero p-4 text-small text-tinta-desvaida">
        La configuración de Telegram requiere la sesión local.
      </p>
    );
  }
  if (!authenticated) {
    return (
      <div className="rounded-lg border border-filio bg-madero p-4">
        <p className="text-small text-tinta-desvaida">
          Iniciá la sesión local para configurar Telegram.
        </p>
        <Button className="mt-3" onClick={() => void auth.start()}>
          Iniciar sesión local
        </Button>
      </div>
    );
  }
  if (!status) {
    return (
      <p className="text-small text-sangre">
        {loadError ?? "No se pudo cargar el estado de Telegram"}
      </p>
    );
  }

  const meta = STATE_META[status.state];
  const guidance = status.error_code ? ERROR_GUIDANCE[status.error_code] : null;

  const save = async () => {
    const value = tokenDraft.trim();
    if (!value || busy) return;
    setBusy(true);
    setLoadError(null);
    setNotice(null);
    try {
      const next = await setTelegramToken(value);
      setStatus(next);
      setTokenDraft("");
      if (tokenInputRef.current) tokenInputRef.current.value = "";
      setNotice("Token guardado en el servidor. Probá la conexión para confirmar.");
    } catch (cause) {
      setLoadError(errorText(cause, "No se pudo guardar el token"));
    } finally {
      setBusy(false);
    }
  };

  const test = async () => {
    if (busy) return;
    setBusy(true);
    setLoadError(null);
    setNotice(null);
    try {
      const result = await testTelegramConnection();
      setStatus(result);
      setNotice(result.message ?? "Prueba de conexión finalizada.");
    } catch (cause) {
      setLoadError(errorText(cause, "No se pudo probar la conexión"));
    } finally {
      setBusy(false);
    }
  };

  const clear = async () => {
    if (!confirmClear) {
      setConfirmClear(true);
      return;
    }
    if (busy) return;
    setBusy(true);
    setLoadError(null);
    setNotice(null);
    try {
      const next = await clearTelegramToken();
      setStatus(next);
      setConfirmClear(false);
      setNotice("Token eliminado. La tarjeta volvió a Pendiente.");
    } catch (cause) {
      setLoadError(errorText(cause, "No se pudo eliminar el token"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="rounded-lg border border-filio bg-madero p-4">
      <div className="flex items-center justify-between gap-3">
        <h3 className="font-heading text-body text-pergamino">Conexión del bot</h3>
        <span className="flex items-center gap-2">
          <strong className={meta.className}>{meta.label}</strong>
          <span className="sr-only">Estado: {meta.label}</span>
        </span>
      </div>
      <p className="mt-1 text-small text-tinta-desvaida">
        El token se guarda solo en el servidor y nunca se vuelve a mostrar.
      </p>

      {status.has_token && (
        <p className="mt-3 text-small text-tinta-desvaida">
          Hay un token guardado en el servidor. Pegá uno nuevo solo para reemplazarlo.
        </p>
      )}

      <div className="mt-3">
        <label className={labelClass} htmlFor="telegram-token">
          Token del bot (write-only)
        </label>
        <input
          ref={tokenInputRef}
          id="telegram-token"
          type="password"
          autoComplete="new-password"
          spellCheck={false}
          className={inputClass}
          value={tokenDraft}
          onChange={(event) => {
            setTokenDraft(event.target.value);
            setConfirmClear(false);
          }}
          placeholder={
            status.has_token
              ? "•••••• (configurado — valor oculto)"
              : "123456789:AA… (token de BotFather)"
          }
        />
      </div>

      <div className="mt-3 flex flex-wrap gap-2">
        <Button onClick={() => void save()} disabled={busy || !tokenDraft.trim()}>
          {busy ? "Guardando…" : "Guardar token"}
        </Button>
        {status.has_token && (
          <>
            <Button variant="secondary" onClick={() => void test()} disabled={busy}>
              {busy ? "Probando…" : "Probar conexión"}
            </Button>
            <Button variant="secondary" onClick={() => void clear()} disabled={busy}>
              {confirmClear ? "Confirmar eliminación" : "Eliminar token"}
            </Button>
          </>
        )}
      </div>

      {guidance && status.state === "error" && (
        <p aria-live="polite" className="mt-3 text-small text-sangre">
          {guidance}
        </p>
      )}
      {loadError && (
        <p aria-live="polite" className="mt-3 text-small text-sangre">
          {loadError}
        </p>
      )}
      {notice && (
        <p aria-live="polite" className="mt-3 text-small text-musgo">
          {notice}
        </p>
      )}
    </div>
  );
}