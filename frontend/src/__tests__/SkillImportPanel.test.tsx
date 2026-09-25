import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { SkillImportPanel } from "@/components/organisms/SkillImportPanel";
import { ApiError } from "@/api/types";
import type { QuarantineRecord } from "@/api/types";
import { tEs } from "@/__tests__/i18nTestUtils";

const mockImportPackage = vi.hoisted(() => vi.fn());
const mockListQuarantine = vi.hoisted(() => vi.fn());
const mockTrustQuarantine = vi.hoisted(() => vi.fn());

vi.mock("@/api/methodologies", () => ({
  importPackage: mockImportPackage,
  listQuarantine: mockListQuarantine,
  trustQuarantine: mockTrustQuarantine,
}));

describe("SkillImportPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockImportPackage.mockResolvedValue({});
    mockListQuarantine.mockResolvedValue({ entries: [] });
  });

  const quarantineRecord = (
    overrides: Partial<QuarantineRecord> = {},
  ): QuarantineRecord => ({
    package_id: "pkg-abc123",
    verdict: {
      ok: true,
      checksum_valid: true,
      signature_present: true,
      signature_valid: true,
      issues: [],
    },
    trusted: false,
    clasificacion: "Comunitarias",
    trust_attributes: ["quarantined"],
    draft_id: null,
    ...overrides,
  });

  it("shows the import section with the outside-workshop integrity copy", async () => {
    render(<SkillImportPanel />);

    expect(await screen.findByText(tEs("skillImport.title"))).toBeInTheDocument();
    expect(
      screen.getByText(
        /La Skill creada fuera del Taller no se ejecuta como válida/,
      ),
    ).toBeInTheDocument();
  });

  it("imports a package into quarantine and renders readable verdict badges", async () => {
    mockListQuarantine.mockResolvedValue({ entries: [quarantineRecord()] });
    const user = userEvent.setup();
    render(<SkillImportPanel />);
    await screen.findByText(tEs("skillImport.title"));

    const file = new File(["pkg"], "skill.zip", { type: "application/zip" });
    await user.upload(screen.getByLabelText(/Paquete/), file);

    await waitFor(() => {
      // The component relies on the API default `origin = "community"`.
      expect(mockImportPackage).toHaveBeenCalledWith(file);
    });
    expect(await screen.findByText(tEs("skillImport.checksumOk"))).toBeInTheDocument();
    expect(screen.getByText(tEs("skillImport.signatureVerified"))).toBeInTheDocument();
    expect(screen.getByText(tEs("skillImport.compileOk"))).toBeInTheDocument();
    expect(screen.getByText(tEs("skillImport.quarantined"))).toBeInTheDocument();
  });

  it("trusts a quarantined package and reflects the promoted draft", async () => {
    mockListQuarantine.mockResolvedValue({ entries: [quarantineRecord()] });
    mockTrustQuarantine.mockResolvedValue({
      package_id: "pkg-abc123",
      trusted: true,
      draft_id: "draft-imported-1",
      clasificacion: "Comunitarias",
      trust_attributes: [],
    });
    const user = userEvent.setup();
    render(<SkillImportPanel />);

    await user.click(await screen.findByRole("button", { name: tEs("skillImport.trust") }));

    await waitFor(() => {
      expect(mockTrustQuarantine).toHaveBeenCalledWith("pkg-abc123");
    });
    // The badge AND the promoted-draft note render; the draft id is truncated
    // via shortId, so match its prefix.
    expect(
      await screen.findByText(/borrador draft-imported/),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: tEs("skillImport.trust") }),
    ).not.toBeInTheDocument();
  });

  it("shows the reserved-id rejection copy on 409", async () => {
    mockListQuarantine.mockResolvedValue({ entries: [quarantineRecord()] });
    mockTrustQuarantine.mockRejectedValue(
      new ApiError(409, "reserved_skill_id", "reserved_skill_id", "reserved_skill_id"),
    );
    const user = userEvent.setup();
    render(<SkillImportPanel />);

    await user.click(await screen.findByRole("button", { name: tEs("skillImport.trust") }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      /reservada por Demiurgos/,
    );
  });
});