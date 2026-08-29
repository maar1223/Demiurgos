import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { useAuthGate } from "@/hooks/useAuthGate";
import { getAuthStatus } from "@/api/wiki";
import type { Mock } from "vitest";

vi.mock("@/api/wiki", () => ({
  getAuthStatus: vi.fn(),
}));

describe("useAuthGate (R-VC-06 — enabled follows _vault_active())", () => {
  beforeEach(() => {
    (getAuthStatus as Mock).mockReset();
  });

  it("requires login when the vault is ON and no session exists (S-VC-06b)", async () => {
    (getAuthStatus as Mock).mockResolvedValue({
      mode: "disabled",
      enabled: true,
      authenticated: false,
      label: null,
    });
    const { result } = renderHook(() => useAuthGate());

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.authEnabled).toBe(true);
    expect(result.current.needsLogin).toBe(true);
  });

  it("passes through when the vault is OFF (S-VC-06a)", async () => {
    (getAuthStatus as Mock).mockResolvedValue({
      mode: "disabled",
      enabled: false,
      authenticated: false,
      label: null,
    });
    const { result } = renderHook(() => useAuthGate());

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.authEnabled).toBe(false);
    expect(result.current.needsLogin).toBe(false);
  });

  it("does not demand login when the vault is ON and a session exists", async () => {
    (getAuthStatus as Mock).mockResolvedValue({
      mode: "credentials",
      enabled: true,
      authenticated: true,
      label: "el-autor",
      provider: "credentials",
    });
    const { result } = renderHook(() => useAuthGate());

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.authEnabled).toBe(true);
    expect(result.current.needsLogin).toBe(false);
  });

  it("fails open on a status error (UX gate, not a security boundary)", async () => {
    (getAuthStatus as Mock).mockRejectedValue(new Error("network down"));
    const { result } = renderHook(() => useAuthGate());

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.authEnabled).toBe(false);
    expect(result.current.needsLogin).toBe(false);
  });
});