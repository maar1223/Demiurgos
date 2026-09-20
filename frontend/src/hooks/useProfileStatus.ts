import { useEffect, useState } from "react";
import { getBackupStatus } from "@/api/backup";
import { getAssistantSettings } from "@/api/assistantSettings";
import { getAuthStatus } from "@/api/wiki";
import type {
  AssistantSettingsStatus,
  AuthSessionStatus,
  BackupStatus,
} from "@/api/types";

export interface ProfileStatus {
  /** Unified session status — identity (getAuthStatus). */
  auth: AuthSessionStatus | null;
  /** Honest local-write card state (getBackupStatus). */
  backup: BackupStatus | null;
  /** Hermes assistant configuration metadata (getAssistantSettings). */
  assistant: AssistantSettingsStatus | null;
  /** True until all three sources settle. */
  isLoading: boolean;
}

/**
 * Loads the three read-only status sources the Perfil status header
 * summarizes (REQ-PIA-05): identity (`getAuthStatus`), backup
 * (`getBackupStatus`) and assistant (`getAssistantSettings`). All three are
 * existing endpoints — the header introduces no new backend data
 * (CON-PIA-01).
 *
 * Each source fails open: a rejected read leaves that slot `null` and never
 * blocks the other two, so one unavailable endpoint cannot take the header
 * down with it.
 */
export function useProfileStatus(): ProfileStatus {
  const [auth, setAuth] = useState<AuthSessionStatus | null>(null);
  const [backup, setBackup] = useState<BackupStatus | null>(null);
  const [assistant, setAssistant] = useState<AssistantSettingsStatus | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    let active = true;
    void Promise.all([
      getAuthStatus().catch(() => null),
      getBackupStatus().catch(() => null),
      getAssistantSettings().catch(() => null),
    ]).then(([nextAuth, nextBackup, nextAssistant]) => {
      if (!active) return;
      setAuth(nextAuth);
      setBackup(nextBackup);
      setAssistant(nextAssistant);
      setIsLoading(false);
    });
    return () => {
      active = false;
    };
  }, []);

  return { auth, backup, assistant, isLoading };
}