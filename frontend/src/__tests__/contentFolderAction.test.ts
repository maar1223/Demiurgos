import { describe, expect, it } from "vitest";

import { contentActionFor } from "@/lib/contentFolderAction";

/** The four rows of the action table (step 5, S2). */
describe("contentActionFor", () => {
  it("uses an empty folder when there is no content yet", () => {
    expect(contentActionFor({ worlds: 0, targetHasContent: false })).toBe("use");
  });

  it("uses a folder that already holds content, even with no worlds here", () => {
    expect(contentActionFor({ worlds: 0, targetHasContent: true })).toBe("use");
  });

  it("moves when there is content and the target is empty", () => {
    expect(contentActionFor({ worlds: 3, targetHasContent: false })).toBe("move");
  });

  it("never moves over content that is already there", () => {
    // Copying over existing content would be a merge, and this product does not
    // merge the author's data.
    expect(contentActionFor({ worlds: 3, targetHasContent: true })).toBe("use");
  });
});
