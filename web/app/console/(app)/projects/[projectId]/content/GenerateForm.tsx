"use client";

import { useRouter } from "next/navigation";
import { useRef, useState } from "react";

import { Panel } from "@/components/ui";
import { newKey, send } from "@/lib/api-browser";
import type { components } from "@/lib/api-schema";

type Finding = components["schemas"]["Finding"];
type Review = components["schemas"]["ReviewExcerpt"];
type Accepted = components["schemas"]["Accepted"];

/** Choose the exact approved findings and reviews for the page and generate a draft (Step 10). Reviews alone need no
 * model (D64); with findings, A08 writes and A09 checks the text through Claude within the model budget. */
export function GenerateForm({
  projectId,
  waiting,
  stage,
  findings,
  reviews,
}: {
  projectId: string;
  waiting: boolean;
  stage: string | null;
  findings: Finding[];
  reviews: Review[];
}) {
  const router = useRouter();
  const key = useRef(newKey("generate"));
  const [chosenFindings, setFindings] = useState<string[]>(findings.map((f) => f.id));
  const [chosenReviews, setReviews] = useState<string[]>(reviews.map((r) => r.id));
  const [message, setMessage] = useState<{ tone: "ok" | "error"; text: string; run?: string } | null>(null);
  const [busy, setBusy] = useState(false);

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
    setMessage({ tone: "ok", text: "Generating in the background. The draft appears below when it is ready.", run: result.data.run_id ?? undefined });
    router.refresh();
  }

  const usesModel = chosenFindings.length > 0;
  return (
    <Panel title="Generate page content">
      {!waiting ? (
        <p className="mb-3 text-warn">
          The latest run is {stage ? stage.replaceAll("_", " ") : "missing"}: generation continues a run that waits at findings review.
        </p>
      ) : null}
      <div className="grid gap-4 lg:grid-cols-2">
        <fieldset>
          <legend className="mb-1 font-medium">Approved reviews ({reviews.length})</legend>
          {reviews.length === 0 ? <p className="text-ink-muted">None approved yet.</p> : null}
          <ul className="max-h-72 space-y-1 overflow-y-auto">
            {reviews.map((r) => (
              <li key={r.id}>
                <label className="flex items-start gap-2">
                  <input type="checkbox" checked={chosenReviews.includes(r.id)} onChange={(e) => setReviews(e.target.checked ? [...chosenReviews, r.id] : chosenReviews.filter((x) => x !== r.id))} />
                  <span>
                    <span className="mr-1 rounded border border-line px-1 text-xs">{r.polarity}</span>
                    {r.text}
                  </span>
                </label>
              </li>
            ))}
          </ul>
        </fieldset>
        <fieldset>
          <legend className="mb-1 font-medium">Approved findings ({findings.length})</legend>
          {findings.length === 0 ? <p className="text-ink-muted">None approved. A page can be built from reviews alone.</p> : null}
          <ul className="max-h-72 space-y-1 overflow-y-auto">
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
      </div>
      <p className="mt-3 text-ink-muted">
        {usesModel
          ? "With findings selected, the page editor (A08) and checker (A09) run on Claude within the model budget."
          : "Reviews only: no model is called; reviews appear exactly as approved."}
      </p>
      {message ? (
        <p role={message.tone === "error" ? "alert" : "status"} className={`mt-2 ${message.tone === "error" ? "text-danger" : "text-ok"}`}>
          {message.text}
          {message.run ? (
            <a href={`/console/runs/${message.run}`} className="ml-2 underline">
              follow the run
            </a>
          ) : null}
        </p>
      ) : null}
      <button
        type="button"
        data-testid="generate"
        disabled={busy || (!chosenFindings.length && !chosenReviews.length)}
        onClick={generate}
        className="mt-3 rounded bg-accent px-3 py-1.5 font-medium text-white disabled:opacity-50"
      >
        {busy ? "Starting…" : "Generate draft"}
      </button>
    </Panel>
  );
}
