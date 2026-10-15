import { describe, expect, it } from "vitest";

import { activity, coverageState, duration, runBadge, runIsWorking } from "./format";

describe("runIsWorking (pages refresh only while the system works)", () => {
  it("is true while collecting and analysing, false once the analysis stopped", () => {
    expect(runIsWorking({ stage: "collecting" })).toBe(true);
    expect(runIsWorking({ stage: "analysing", outcome_note: "Collection finished; analysis queued" })).toBe(true);
    expect(runIsWorking({ stage: "analysing", outcome_note: "Analysis stopped: budget_exhausted: run budget reached" })).toBe(false);
  });

  it("waits for people: no refresh at review, approval, or a built draft", () => {
    for (const stage of ["findings_review", "final_review", "approved", "published", "cancelled", "insufficient_evidence"]) {
      expect(runIsWorking({ stage })).toBe(false);
    }
    expect(runIsWorking({ stage: "formatting", content_revision_id: null })).toBe(true);
    expect(runIsWorking({ stage: "formatting", content_revision_id: "rev_X" })).toBe(false);
    expect(runIsWorking({ stage: "formatting", outcome_note: "Page building stopped: incomplete: cut off" })).toBe(false);
  });

  it("treats publishing as working only for a few minutes", () => {
    expect(runIsWorking({ stage: "publishing", updated_at: new Date().toISOString() })).toBe(true);
    expect(runIsWorking({ stage: "publishing", updated_at: new Date(Date.now() - 3_600_000).toISOString() })).toBe(false);
  });
});

describe("coverageState", () => {
  it("reads queued, running and final while collecting", () => {
    expect(coverageState({ status: "partial", note: "queued" }, "collecting").text).toBe("queued");
    const running = coverageState({ status: "partial", note: "in progress: 3 of up to 80 pages read" }, "collecting");
    expect([running.text, running.detail]).toEqual(["running", "3 of up to 80 pages read"]);
    expect(coverageState({ status: "complete_for_query", note: "fetched: 3" }, "collecting").text).toBe("complete");
    expect(coverageState({ status: "partial", note: "queued" }, "collecting").status).toBe("queued");
  });

  it("never says running once the run has moved on", () => {
    const left = coverageState({ status: "partial", note: "in progress: 3 of up to 80 pages read" }, "cancelled");
    expect([left.text, left.detail]).toEqual(["not finished", "3 of up to 80 pages read"]);
    expect(coverageState({ status: "partial", note: "queued" }, "analysing").text).toBe("not finished");
  });
});

describe("activity (a working source's own note)", () => {
  it("reads the step and the counts so far", () => {
    const pages = activity("24 of up to 80 pages read; fetched: 20; refused: 4");
    expect(pages.doing).toBe("24 of up to 80 pages read");
    expect(pages.step).toEqual({ done: 24, total: 80, upTo: true });
    expect(pages.counts).toEqual([
      { key: "fetched", value: "20" },
      { key: "refused", value: "4" },
    ]);
    expect(activity("thread 3 of 10").step).toEqual({ done: 3, total: 10, upTo: false });
    expect(activity("comments of video 2 of 5; matched: 1").step).toEqual({ done: 2, total: 5, upTo: false });
  });

  it("has no step when the note names none, and reads a finished note as counts only", () => {
    expect(activity("search 4").step).toBeNull();
    const done = activity("fetched: 3; not_collected:linkedin: 2; errors: timeout");
    expect(done.doing).toBe("");
    expect(done.counts.map((c) => c.key)).toEqual(["fetched", "not_collected:linkedin", "errors"]);
    const brave = activity("searches done; reading the pages found; not_collected:linkedin: 2");
    expect([brave.doing, brave.counts.length]).toEqual(["searches done; reading the pages found", 1]);
    expect(activity(null)).toEqual({ doing: "", step: null, counts: [] });
  });
});

describe("runBadge and duration", () => {
  it("shows a stopped analysis as stopped and a waiting draft as not working", () => {
    expect(runBadge({ stage: "analysing", outcome_note: "Analysis stopped: budget_exhausted" })).toEqual({ status: "partial", text: "stopped" });
    expect(runBadge({ stage: "collecting" })).toEqual({ status: "collecting", text: "collecting" });
    expect(runBadge({ stage: "formatting", content_revision_id: "rev_1" }).status).toBe("needs_review");
    expect(runBadge({ stage: "findings_review" }).text).toBe("awaiting decisions");
  });

  it("says spans of time in words", () => {
    expect(duration(30_000)).toBe("under a minute");
    expect(duration(7 * 60_000)).toBe("7 min");
    expect(duration(125 * 60_000)).toBe("2 h 5 min");
    expect(duration(3 * 86_400_000)).toBe("3 days");
  });
});
