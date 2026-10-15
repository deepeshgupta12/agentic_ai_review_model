/** The console's review-first flow (D68, D69): run, approve reviews, build the page, approve and publish. One place
 * decides what a project needs next, so the portfolio and every project screen say the same thing. */

export type FlowSummary = {
  latest_run: { id: string; stage: string } | null;
  pending_review: { findings: number; review_excerpts: number };
  publication: { serving_state: string; approved_revision: number | null; active_revision: number | null };
};

export type NextStep = {
  /** 1 run, 2 approve reviews, 3 build the page, 4 approve and publish. */
  step: 1 | 2 | 3 | 4;
  title: string;
  detail: string;
  href: string;
  action: string;
  /** todo: someone acts now; wait: the system is working; done: published; stop: the run found nothing. */
  tone: "todo" | "wait" | "done" | "stop";
};

export const STEPS = ["Run", "Approve reviews", "Build the page", "Approve and publish"] as const;

function plural(n: number, one: string, many = `${one}s`): string {
  return `${n} ${n === 1 ? one : many}`;
}

export function nextStep(summary: FlowSummary, projectId: string, slug: string, reviewsMax = 20): NextStep {
  const base = `/console/projects/${projectId}`;
  const run = summary.latest_run;
  const reviews = summary.pending_review.review_excerpts;
  const findings = summary.pending_review.findings;
  const start = { step: 1 as const, href: `${base}/runs`, action: "Start a run" };
  const { approved_revision: approved, active_revision: active } = summary.publication;
  // a newer revision approved after the page went live (an edit) waits for a publisher (audit, 14 Oct 2026)
  const newerApproved = approved !== null && approved !== active;
  if (!run) {
    return { ...start, title: "Start the first run", detail: "It collects people's reviews from the portals, Reddit, Quora and YouTube, then reads them.", tone: "todo" };
  }
  switch (run.stage) {
    case "collecting":
    case "analysing":
      return {
        step: 1,
        title: run.stage === "collecting" ? "Collecting reviews" : "Reading the reviews",
        detail: "The run continues in the background; this page updates when it reaches review.",
        href: `/console/runs/${run.id}`,
        action: "Follow the run",
        tone: "wait",
      };
    case "cancelled":
      return { ...start, title: "The last run was cancelled", detail: "What it collected is kept. Start a new run when ready.", tone: "todo" };
    case "insufficient_evidence":
      return {
        step: 1,
        title: "The last run found no usable reviews",
        detail: "Check the project's names and sources in Setup, then run again. Coverage on the run page shows what was read.",
        href: `/console/runs/${run.id}`,
        action: "See what was read",
        tone: "stop",
      };
    case "findings_review": {
      if (reviews + findings > 0) {
        const parts = [reviews ? plural(reviews, "review") : "", findings ? plural(findings, "finding") : ""].filter(Boolean);
        return {
          step: 2,
          title: `${parts.join(" and ")} waiting for a decision`,
          detail: "Approve each one that is a real person's review of this project; reject the rest.",
          href: reviews ? `${base}/reviews?review_status=pending` : `${base}/findings?review_status=pending`,
          action: "Decide",
          tone: "todo",
        };
      }
      return {
        step: 3,
        title: "Build the page",
        detail: `Choose up to ${reviewsMax} approved reviews (a mix of positive and negative) and generate the draft. No model is called.`,
        href: `${base}/content`,
        action: "Build the page",
        tone: "todo",
      };
    }
    case "formatting":
      return {
        step: 3,
        title: "Page draft in progress",
        detail: "A draft is being built, or it has issues to fix in the editor before it can be approved.",
        href: `${base}/content`,
        action: "Open the page",
        tone: "todo",
      };
    case "final_review":
      return { step: 4, title: "Approve the page", detail: "Read the draft and approve that exact revision.", href: `${base}/content`, action: "Open the draft", tone: "todo" };
    case "approved":
      return {
        step: 4,
        title: `Publish revision ${summary.publication.approved_revision ?? ""}`.trim(),
        detail: "It is approved; a publisher makes it live.",
        href: `${base}/publishing`,
        action: "Publish",
        tone: "todo",
      };
    case "publishing":
      return { step: 4, title: "Publishing", detail: "Activating and checking the public page.", href: `${base}/publishing`, action: "Follow it", tone: "wait" };
    case "published":
      if (newerApproved) {
        return {
          step: 4,
          title: `Publish revision ${approved}`,
          detail: `Revision ${active ?? "none"} is live; revision ${approved} is approved and waits for a publisher.`,
          href: `${base}/publishing`,
          action: "Publish",
          tone: "todo",
        };
      }
      return {
        step: 4,
        title: summary.publication.active_revision ? `Revision ${summary.publication.active_revision} is live` : "Published",
        detail: "To change the reviews shown, edit the latest page revision; it needs a new approval.",
        href: `/projects/${slug}`,
        action: "View the public page",
        tone: "done",
      };
    default:
      return { ...start, title: run.stage.replaceAll("_", " "), detail: "", tone: "todo" };
  }
}

type Sided = { id: string; polarity: string; published?: { value?: string | null } | null };

/** The page's starting selection: at most `limit` reviews, positive, negative and mixed in proportion and newest
 * first within each side (the backend orders the page by the same rule, Webster's, in content/build.balanced). */
export function balancedPick<T extends Sided>(reviews: T[], limit: number): T[] {
  const sides = new Map<string, T[]>();
  for (const review of reviews) sides.set(review.polarity, [...(sides.get(review.polarity) ?? []), review]);
  for (const side of sides.values()) side.sort((a, b) => String(b.published?.value ?? "").localeCompare(String(a.published?.value ?? "")));
  const shown = new Map([...sides.keys()].map((k) => [k, 0]));
  const out: T[] = [];
  const total = reviews.length;
  while (out.length < Math.min(limit, total)) {
    let best: string | null = null;
    for (const [key, side] of sides) {
      const n = shown.get(key) ?? 0;
      if (n >= side.length) continue;
      if (best === null || (n + 0.5) / side.length < ((shown.get(best) ?? 0) + 0.5) / (sides.get(best)?.length ?? 1)) best = key;
    }
    if (best === null) break;
    const n = shown.get(best) ?? 0;
    out.push((sides.get(best) as T[])[n]);
    shown.set(best, n + 1);
  }
  return out;
}

export function wordCount(text: string | null | undefined): number {
  return (text ?? "").split(/\s+/).filter(Boolean).length;
}

/** The backend's review limits for the page (from /healthz; D69). */
export type ReviewLimits = { page_reviews_max: number; review_words_min: number; review_words_max: number };

export function fitsPage(text: string | null | undefined, limits: ReviewLimits): boolean {
  const count = wordCount(text);
  return count >= limits.review_words_min && count <= limits.review_words_max;
}
