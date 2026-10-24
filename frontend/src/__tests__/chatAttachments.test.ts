import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { uploadChatAttachment } from "@/api/chatAttachments";
import { ApiError } from "@/api/types";

const fetchMock = vi.fn();

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function attachmentPayload() {
  return {
    id: "att-1",
    name: "Personaje.docx",
    kind: "docx",
    chars: 1200,
    truncated: false,
  };
}

describe("uploadChatAttachment", () => {
  it("posts the file as multipart to the world-scoped endpoint", async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify(attachmentPayload()), { status: 201 }),
    );
    const file = new File(["contenido"], "Personaje.docx", {
      type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    });

    const attachment = await uploadChatAttachment("Vibrantes", file);

    expect(attachment).toEqual(attachmentPayload());
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/Vibrantes/ai/attachments");
    expect(init.method).toBe("POST");
    expect(init.body).toBeInstanceOf(FormData);
    expect((init.body as FormData).get("file")).toBe(file);
  });

  it("encodes the global assistant context as the mundo segment", async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify(attachmentPayload()), { status: 201 }),
    );
    await uploadChatAttachment("ideas-global", new File(["x"], "a.pdf"));
    expect(fetchMock.mock.calls[0][0]).toBe("/api/ideas-global/ai/attachments");
  });

  it("throws the backend code when the upload is rejected", async () => {
    fetchMock.mockResolvedValue(
      new Response(
        JSON.stringify({
          detail: "Unsupported attachment type; only .docx and .pdf are accepted.",
          code: "attachment.unsupported_type",
          params: {},
        }),
        { status: 422 },
      ),
    );

    await expect(
      uploadChatAttachment("Vibrantes", new File(["x"], "notes.txt")),
    ).rejects.toMatchObject({
      name: "ApiError",
      status: 422,
      code: "attachment.unsupported_type",
    });
    await expect(
      uploadChatAttachment("Vibrantes", new File(["x"], "notes.txt")),
    ).rejects.toBeInstanceOf(ApiError);
  });

  it("never returns a malformed attachment payload", async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ id: 3 }), { status: 201 }),
    );
    await expect(
      uploadChatAttachment("Vibrantes", new File(["x"], "a.pdf")),
    ).rejects.toMatchObject({ status: 0 });
  });
});
