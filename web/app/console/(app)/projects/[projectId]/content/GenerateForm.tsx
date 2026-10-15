"use client";

import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { Panel } from "@/components/ui";
import { newKey, send } from "@/lib/api-browser";
import type { components } from "@/lib/api-schema";
import { balancedPick, fitsPage, type ReviewLimits, wordCount } from "@/lib/flow";

type Finding = components["schemas"]["Finding"];
type Review = components["schemas"]["ReviewExcerpt"];
type Accepted = components["schemas"]["Accepted"];

const SIDES = ["positive", "negative", "mixed"] as const;

/** Choose the exact approved reviews (and, in the full analysis, findings) for the page and generate a draft
 * (Step 10). Reviews alone need no model (D64); the backend orders them positive, negative and mixed in proportion
 * and checks the limits again (D69). When the draft is ready the editor opens. */
export function GenerateForm({
  projectId,
  findings,
  reviews,
  limits,
}: {
  projectId: string;
  findings: Finding[];
  reviews: Review[];
  limits: ReviewLimits;
}) {
  const router = useRouter();
  const key = useRef(newKey("generate"));
  const publishable = reviews.filter((r) => fitsPage(r.text, limits));
  // No finding is ticked by default: with findings the page writer and checker are paid model calls (audit, 14 Oct)
  const [chosenFindings, setFindings] = useState<string[]>([]);
  const [chosenReviews, setReviews] = useState<string[]>(() => balancedPick(publishable, limits.page_reviews_max).map((r) => r.id));
  const [message, setMessage] = useState<{ tone: "ok" | "error"; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [waitingFor, setWaitingFor] = useState<string | null>(null);

  // Follow the run until the draft exists, then open it; stop, and say why, when the run reports a problem after the
  // request, or after three minutes (audit, 14 Oct 2026: the form could wait forever).
  useEffect(() => {
    if (!waitingFor) return;
    const started = Date.now();
    let stopped = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const poll = async () => {
      const response = await fetch(`/v1/runs/${waitingFor}`, { credentials: "same-origin", cache: "no-store" }).catch(() => null);
      if (stopped) return;
      if (response?.ok) {
        const run = (await response.json()) as { stage: string; content_revision_id: string | null; outcome_note: string | null; updated_at: string };
        const changedSince = Date.parse(run.updated_at) >= started - 1000;
        const problem = /^(Selection refused|Page building stopped|Analysis stopped)/.test(run.outcome_note ?? "");
        if (run.content_revision_id) {
          router.push(`/console/projects/${projectId}/content/${run.content_revision_id}`);
          router.refresh();
          return;
        }
        if ((changedSince && problem) || !["findings_review", "formatting"].includes(run.stage)) {
          setWaitingFor(null);
          setMessage({ tone: "error", text: run.outcome_note ?? `The run is now ${run.stage.replaceAll("_", " ")}.` });
          router.refresh();
          return;
        }
      }
      if (Date.now() - started > 3 * 60_000) {
        setWaitingFor(null);
        setMessage({ tone: "error", text: "Still not ready after three minutes. Follow the run page; the draft appears here when it is built." });
        return;
      }
      timer = setTimeout(poll, 3000);
    };
    timer = setTimeout(poll, 3000);
    return () => {
      stopped = true;
      if (timer) clearTimeout(timer);
    };
  }, [waitingFor, projectId, router]);

  async function generate() {
    setBusy(true);
    const body = {
      mode: "generate",
      locale: "en-IN",
      findings: findings.filter((f) => chosenFindings.includes(f.id)).map((f) => ({ id: f.id, revision: f.revision })),
      reviews: reviews.filter((r) => chosenReviews.includes(r.id)).map((r) => ({ id: r.id, revision: r.revision })),
    };
    const result = await send<Accepted>("POST", `/v1/projects/${projectId}/content-revisions`, body, { idempotencyKey: key.current });
    setBusy(false);
    if (!result.ok || !result.data) {
      setMessage({ tone: "error", text: result.message ?? "Not started" });
      return;
    }
    key.current = newKey("generate");
    setMessage({ tone: "ok", text: "Generating in the background. The draft opens here when it is ready." });
    setWaitingFor(result.data.run_id ?? null);
  }

  const usesModel = chosenFindings.length > 0;
  const selected = reviews.filter((r) => chosenReviews.includes(r.id));
  const mix = SIDES.map((side) => `${selected.filter((r) => r.polarity === side).length} ${side}`).join(", ");
  const full = chosenReviews.length >= limits.page_reviews_max;
  return (
    <Panel title="Build the page">
      <p className="mb-3 max-w-3xl text-ink-muted">
        Choose up to {limits.page_reviews_max} approved reviews of {limits.review_words_min} to {limits.review_words_max} words. The page shows
        them as Person 1, Person 2 and so on, in the authors&apos; own words, with positive, negative and mixed reviews spread through the list.
      </p>
      <div className={findings.length ? "grid gap-4 lg:grid-cols-2" : ""}>
        <fieldset>
          <legend className="mb-1 font-medium">
            Approved reviews: {chosenReviews.length} of at most {limits.page_reviews_max} selected ({mix})
          </legend>
          {reviews.length === 0 ? <p className="text-ink-muted">None approved yet. Approve reviews on the Reviews tab first.</p> : null}
          {reviews.length > publishable.length ? (
            <p className="mb-1 text-xs text-ink-muted">
              {reviews.length - publishable.length} approved review(s) are outside {limits.review_words_min} to {limits.review_words_max} words
              and cannot be shown; a moderator can shorten one to whole sentences on the Reviews tab.
            </p>
          ) : null}
          <ul className="max-h-96 space-y-1 overflow-y-auto">
            {reviews.map((r) => {
              const fits = fitsPage(r.text, limits);
              const on = chosenReviews.includes(r.id);
              return (
                <li key={r.id}>
                  <label className="flex items-start gap-2">
                    <input
                      type="checkbox"
                      checked={on}
                      disabled={!fits || (!on && full)}
                      onChange={(e) => setReviews(e.target.checked ? [...chosenReviews, r.id] : chosenReviews.filter((x) => x !== r.id))}
                    />
                    <span className={fits ? "" : "text-ink-muted"}>
                      <span className="mr-1 rounded border border-line px-1 text-xs">{r.polarity}</span>
                      <span className="mr-1 text-xs text-ink-muted">{wordCount(r.text)} words</span>
                      {r.text}
                    </span>
                  </label>
                </li>
              );
            })}
          </ul>
        </fieldset>
        {findings.length ? (
          <fieldset>
            <legend className="mb-1 font-medium">Approved findings ({findings.length})</legend>
            <ul className="max-h-96 space-y-1 overflow-y-auto">
              {findings.map((f) => (
                <li key={f.id}>
                  <label className="flex items-start gap-2">
                    <input type="checkbox" checked={chosenFindings.includes(f.id)} onChange={(e) => setFindings(e.target.checked ? [...chosenFindings, f.id] : chosenFindings.filter((x) => x !== f.id))} />
                    <span>
                      <span className="mr-1 rounded border border-line px-1 text-xs uppercase">{f.kind}</span>
                      {f.wording}
                    </span>
                  </label>
                </li>
              ))}
            </ul>
          </fieldset>
        ) : null}
      </div>
      <p className="mt-3 text-ink-muted">
        {usesModel
          ? "With findings selected, the page editor (A08) and checker (A09) run on Claude within the model budget."
          : "Reviews only: no model is called; reviews appear exactly as approved."}
      </p>
      {message ? (
        <p role={message.tone === "error" ? "alert" : "status"} className={`mt-2 ${message.tone === "error" ? "text-danger" : "text-ok"}`}>
          {message.text}
        </p>
      ) : null}
      <button
        type="button"
        data-testid="generate"
        disabled={busy || waitingFor !== null || (!chosenFindings.length && !chosenReviews.length)}
        onClick={generate}
        className="mt-3 rounded bg-accent px-3 py-1.5 font-medium text-white disabled:opacity-50"
      >
        {busy ? "Starting…" : waitingFor ? "Generating…" : "Generate draft"}
      </button>
    </Panel>
  );
}
