import { useCallback, useEffect, useState } from "react";

export interface RecoveryWordsUnlock {
  /** The verified words held for this session, or null while locked. */
  unlockedWords: string | null;
  /** Arm the session unlock after a successful words-gated action. */
  unlock: (words: string) => void;
  /** Clear the unlocked words (logout / explicit lock). */
  lock: () => void;
}

/**
 * Session-scoped recovery-words unlock (REQ-SRW-01..04). The recovery words
 * are the ownership key: once a words-gated action succeeds, the verified
 * words are held in memory for the rest of the session and replayed on later
 * actions without re-prompting (REQ-SRW-01).
 *
 * Security framing (REQ-SRW-04): the words live ONLY in React state — never
 * localStorage, sessionStorage or cookies (REQ-SRW-02) — and are cleared when
 * the owning surface unmounts (REQ-SRW-03). Reload clears them trivially
 * because nothing is persisted; logout clears them explicitly before the
 * page reloads. Instantiating this hook at the page level (not inside the
 * tab panel) makes the unlock survive section switches for the session.
 */
export function useRecoveryWordsUnlock(): RecoveryWordsUnlock {
  const [unlockedWords, setUnlockedWords] = useState<string | null>(null);

  const unlock = useCallback((words: string) => {
    setUnlockedWords(words.trim());
  }, []);

  const lock = useCallback(() => {
    setUnlockedWords(null);
  }, []);

  // REQ-SRW-03: the words never outlive the owning surface.
  useEffect(() => {
    return () => {
      setUnlockedWords(null);
    };
  }, []);

  return { unlockedWords, unlock, lock };
}