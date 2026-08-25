import { describe, expect, it, vi } from "vitest";
import { act, renderHook } from "@testing-library/react";
import {
  useAIAssistantSessions,
  type Session,
} from "@/hooks/useAIAssistantSessions";

vi.mock("@/hooks/useAppLanguage", () => ({
  useAppLanguage: vi.fn(() => "es"),
}));

const SESSIONS_KEY = "demiurgos-ai-sessions";
const ACTIVE_KEY = "demiurgos-ai-sessions-active";

function makeSession(id: string, title = "Session title"): Session {
  return { id, title, messages: [], createdAt: Date.now() };
}

function seedSessions(sessions: Session[]): void {
  window.localStorage.setItem(SESSIONS_KEY, JSON.stringify(sessions));
}

describe("useAIAssistantSessions active session persistence", () => {
  it("persists the active session id and restores it on a fresh mount", () => {
    seedSessions([makeSession("s1"), makeSession("s2")]);

    const first = renderHook(() => useAIAssistantSessions("mundo"));
    expect(first.result.current.activeSessionId).toBeNull();

    act(() => {
      first.result.current.switchSession("s2");
    });
    expect(first.result.current.activeSessionId).toBe("s2");

    const stored = window.localStorage.getItem(ACTIVE_KEY);
    expect(stored).toBe(JSON.stringify("s2"));

    first.unmount();

    // Fresh mount — simulates the sidebar remounting after a tab switch
    const second = renderHook(() => useAIAssistantSessions("mundo"));
    expect(second.result.current.activeSessionId).toBe("s2");
    expect(second.result.current.activeSession?.id).toBe("s2");
  });

  it("falls back to null when the persisted id no longer exists", () => {
    seedSessions([makeSession("s1")]);
    window.localStorage.setItem(ACTIVE_KEY, JSON.stringify("ghost-id"));

    const { result } = renderHook(() => useAIAssistantSessions("mundo"));
    expect(result.current.activeSessionId).toBeNull();
    expect(result.current.activeSession).toBeNull();
  });

  it("does not auto-select a session when nothing was active", () => {
    seedSessions([makeSession("s1"), makeSession("s2")]);

    const { result } = renderHook(() => useAIAssistantSessions("mundo"));
    expect(result.current.activeSessionId).toBeNull();
    expect(result.current.activeSession).toBeNull();
  });

  it("clears the persisted id when the active session is deleted", () => {
    seedSessions([makeSession("s1"), makeSession("s2")]);

    const { result } = renderHook(() => useAIAssistantSessions("mundo"));
    act(() => {
      result.current.switchSession("s2");
    });
    expect(result.current.activeSessionId).toBe("s2");

    act(() => {
      result.current.deleteSession("s2");
    });
    expect(result.current.activeSessionId).toBeNull();
    expect(window.localStorage.getItem(ACTIVE_KEY)).toBeNull();
  });

  it("persists a newly created session as active", () => {
    seedSessions([makeSession("s1")]);

    const { result } = renderHook(() => useAIAssistantSessions("mundo"));
    act(() => {
      result.current.createSession();
    });

    const createdId = result.current.activeSessionId;
    expect(createdId).not.toBeNull();
    expect(window.localStorage.getItem(ACTIVE_KEY)).toBe(JSON.stringify(createdId));

    // A fresh mount restores the newly created session
    const second = renderHook(() => useAIAssistantSessions("mundo"));
    expect(second.result.current.activeSessionId).toBe(createdId);
  });
});