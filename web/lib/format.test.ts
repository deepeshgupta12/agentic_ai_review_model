import { describe, expect, it } from "vitest";

import { coverageState, runIsWorking } from "./format";

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
    expect(coverageState({ status: "complete_for_query", note: "fetched: 3" }, "collecting").text).toBe("complete for query");
  });

  it("never says running once the run has moved on", () => {
    const left = coverageState({ status: "partial", note: "in progress: 3 of up to 80 pages read" }, "cancelled");
    expect([left.text, left.detail]).toEqual(["not finished", "3 of up to 80 pages read"]);
    expect(coverageState({ status: "partial", note: "queued" }, "analysing").text).toBe("not finished");
  });
});
