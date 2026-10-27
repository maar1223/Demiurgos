import { beforeEach, describe, expect, it } from "vitest";
import {
  matchReleasedReports,
  readPseudonymPreference,
  readSubmittedReports,
  rememberSubmittedReport,
  writePseudonymPreference,
  type ReleasedVersion,
} from "@/lib/bugReportHistory";

const KEY = "demiurgos.bugreport.reports";

function report(id: string, at = "2026-10-01T10:00:00Z") {
  return { id, at, app_version: "0.4.0" };
}

function release(version: string, ids: string[]): ReleasedVersion {
  return { version, report_ids: ids, at: "2026-10-25T00:00:00Z" };
}

describe("bug report history — what this install sent (S12)", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("remembers a delivered report and reads it back", () => {
    rememberSubmittedReport(report("abc-123"));

    expect(readSubmittedReports()).toEqual([report("abc-123")]);
  });

  it("does not duplicate a repeated delivery id", () => {
    rememberSubmittedReport(report("abc-123"));
    rememberSubmittedReport(report("abc-123", "2026-10-02T10:00:00Z"));

    const stored = readSubmittedReports();
    expect(stored).toHaveLength(1);
    expect(stored[0].at).toBe("2026-10-02T10:00:00Z");
  });

  it("keeps the list bounded", () => {
    for (let index = 0; index < 60; index += 1) {
      rememberSubmittedReport(report(`id-${index}-aaaa`));
    }

    expect(readSubmittedReports()).toHaveLength(50);
  });

  it("treats unreadable or corrupt storage as empty", () => {
    localStorage.setItem(KEY, "not json");
    expect(readSubmittedReports()).toEqual([]);

    localStorage.setItem(KEY, JSON.stringify([{ id: 5 }, report("ok-12345")]));
    expect(readSubmittedReports()).toEqual([report("ok-12345")]);
  });

  it("matches only this install's reports, newest release first", () => {
    const fixed = matchReleasedReports(
      [report("mine-1"), report("mine-2"), report("mine-3")],
      [
        release("v0.6.0", ["mine-3", "ajeno"]),
        release("v0.5.0", ["mine-1", "mine-3"]),
      ],
    );

    // mine-3 belongs to the newest release that mentions it; mine-2 was never fixed.
    expect(fixed).toEqual([
      { id: "mine-3", version: "v0.6.0" },
      { id: "mine-1", version: "v0.5.0" },
    ]);
  });

  it("finds nothing when the release list is empty or unrelated", () => {
    expect(matchReleasedReports([report("mine-1")], [])).toEqual([]);
    expect(matchReleasedReports([report("mine-1")], [release("v1", ["otro"])])).toEqual(
      [],
    );
  });
});

describe("pseudonym preference — optional and remembered (S20)", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("is on when nothing was chosen", () => {
    expect(readPseudonymPreference()).toBe(true);
  });

  it("remembers turning it off", () => {
    writePseudonymPreference(false);
    expect(readPseudonymPreference()).toBe(false);
    expect(localStorage.getItem("demiurgos.bugreport.pseudonym")).toBe("0");

    writePseudonymPreference(true);
    expect(readPseudonymPreference()).toBe(true);
  });

  it("survives an unreadable store by falling back to on", () => {
    const original = localStorage.getItem;
    localStorage.getItem = () => {
      throw new Error("blocked");
    };
    try {
      expect(readPseudonymPreference()).toBe(true);
    } finally {
      localStorage.getItem = original;
    }
  });
});
