import { describe, expect, it } from "vitest";

import { balancedPick, fitsPage, nextStep, wordCount } from "./flow";

const base = {
  latest_run: null as { id: string; stage: string } | null,
  pending_review: { findings: 0, review_excerpts: 0 },
  publication: { serving_state: "unpublished", approved_revision: null as number | null, active_revision: null as number | null },
};

describe("nextStep", () => {
  it("starts with a run and follows the run while it works", () => {
    expect(nextStep(base, "prj_1", "q").href).toBe("/console/projects/prj_1/runs");
    const collecting = nextStep({ ...base, latest_run: { id: "run_1", stage: "collecting" } }, "prj_1", "q");
    expect([collecting.step, collecting.tone, collecting.href]).toEqual([1, "wait", "/console/runs/run_1"]);
  });

  it("asks for review decisions first, then the page", () => {
    const waiting = { ...base, latest_run: { id: "run_1", stage: "findings_review" } };
    const decide = nextStep({ ...waiting, pending_review: { findings: 0, review_excerpts: 3 } }, "prj_1", "q");
    expect([decide.step, decide.title, decide.href]).toEqual([2, "3 reviews waiting for a decision", "/console/projects/prj_1/reviews?review_status=pending"]);
    const build = nextStep(waiting, "prj_1", "q", 20);
    expect([build.step, build.href]).toEqual([3, "/console/projects/prj_1/content"]);
    expect(build.detail).toContain("up to 20");
  });

  it("ends at approval, publication and the live page", () => {
    expect(nextStep({ ...base, latest_run: { id: "r", stage: "final_review" } }, "p", "q").step).toBe(4);
    const approved = nextStep({ ...base, latest_run: { id: "r", stage: "approved" }, publication: { ...base.publication, approved_revision: 2 } }, "p", "q");
    expect([approved.title, approved.href]).toEqual(["Publish revision 2", "/console/projects/p/publishing"]);
    const live = nextStep({ ...base, latest_run: { id: "r", stage: "published" }, publication: { ...base.publication, active_revision: 2 } }, "p", "q-slug");
    expect([live.tone, live.href]).toEqual(["done", "/projects/q-slug"]);
    expect(nextStep({ ...base, latest_run: { id: "r", stage: "insufficient_evidence" } }, "p", "q").tone).toBe("stop");
  });
});

describe("balancedPick", () => {
  const review = (id: string, polarity: string, month: number) => ({ id, polarity, published: { value: `2026-0${month}-01` } });
  const pool = [
    ...[1, 2, 3, 4, 5, 6].map((m) => review(`p${m}`, "positive", m)),
    ...[1, 2, 3].map((m) => review(`n${m}`, "negative", m)),
    review("m1", "mixed", 5),
  ];

  it("mixes the sides in proportion, newest first within each, as the backend orders the page", () => {
    const out = balancedPick(pool, 20).map((r) => r.id);
    expect(out).toHaveLength(10);
    expect(out.filter((id) => id.startsWith("n"))).toEqual(["n3", "n2", "n1"]);
    expect(out.indexOf("m1")).toBeGreaterThan(0);
    expect(out.indexOf("m1")).toBeLessThan(9);
  });

  it("keeps both sides when it has to cut", () => {
    const out = balancedPick(pool, 4);
    expect(out).toHaveLength(4);
    expect(new Set(out.map((r) => r.polarity))).toEqual(new Set(["positive", "negative"]));
  });
});

describe("page limits", () => {
  const limits = { page_reviews_max: 20, review_words_min: 3, review_words_max: 5 };
  it("counts words and checks the range", () => {
    expect(wordCount("  one two\nthree ")).toBe(3);
    expect(fitsPage("one two", limits)).toBe(false);
    expect(fitsPage("one two three", limits)).toBe(true);
    expect(fitsPage("one two three four five six", limits)).toBe(false);
    expect(fitsPage(null, limits)).toBe(false);
  });
});
