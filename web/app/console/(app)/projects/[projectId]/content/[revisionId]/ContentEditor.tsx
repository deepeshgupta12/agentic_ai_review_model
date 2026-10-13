"use client";

import { useRouter } from "next/navigation";
import { useRef, useState } from "react";

import { Panel } from "@/components/ui";
import { newKey, send } from "@/lib/api-browser";
import type { components } from "@/lib/api-schema";
import { creditLine } from "@/lib/format";

type Revision = components["schemas"]["ContentRevision"];
type Payload = components["schemas"]["ContentPayload"];
type Issue = components["schemas"]["QaIssue"];
type View = components["schemas"]["ContentRevisionView"];

function Issues({ issues, block, index }: { issues: Issue[]; block: string; index?: number | null }) {
  const own = issues.filter((i) => i.block === block && (index === undefined || i.item_index === index || i.item_index === null));
  if (own.length === 0) return null;
  return (
    <ul className="mt-1 space-y-0.5">
      {own
        .sort((a, b) => (a.severity === b.severity ? 0 : a.severity === "blocking" ? -1 : 1))
        .map((i, n) => (
          <li key={n} className={i.severity === "blocking" ? "text-danger" : "text-warn"}>
            {i.severity === "blocking" ? "Blocking" : "Note"} ({i.category.replaceAll("_", " ")}, {i.source}): {i.explanation}
          </li>
        ))}
    </ul>
  );
}

function Refs({ support }: { support: { findings: { id: string; revision: number }[]; claims: { id: string; revision: number }[] } }) {
  return (
    <p className="mt-1 font-mono text-[11px] text-ink-muted">
      rests on {support.findings.map((f) => `${f.id.slice(-6)} r${f.revision}`).join(", ")} · {support.claims.length} claim(s)
    </p>
  );
}

/** Block-by-block controlled editor (Step 10.4): the editor may change the heading, the text and caveat of each block,
 * the questions, the coverage note and the metadata, and which approved reviews to show in what order. References,
 * credits, sources and JSON-LD are the backend's; a saved edit is a new revision checked again by the same QA. */
export function ContentEditor({ revision, issues, editable }: { revision: Revision; issues: Issue[]; editable: boolean }) {
  const router = useRouter();
  const key = useRef(newKey("edit"));
  const [payload, setPayload] = useState<Payload>(structuredClone(revision.payload));
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const dirty = JSON.stringify(payload) !== JSON.stringify(revision.payload);

  function update(change: (p: Payload) => void) {
    setPayload((current) => {
      const next = structuredClone(current);
      change(next);
      return next;
    });
  }

  async function save() {
    setBusy(true);
    setError(null);
    const result = await send<View>(
      "POST",
      `/v1/projects/${revision.project_id}/content-revisions`,
      { mode: "edit", locale: revision.locale, base: { id: revision.id, revision: revision.revision }, payload, reason },
      { idempotencyKey: key.current },
    );
    setBusy(false);
    if (!result.ok || !result.data) {
      setError(result.message);
      return;
    }
    key.current = newKey("edit");
    router.push(`/console/projects/${revision.project_id}/content/${result.data.revision.id}`);
    router.refresh();
  }

  const area = "w-full rounded border border-line px-2 py-1 disabled:bg-surface-sunken";
  return (
    <div className="space-y-4">
      <Panel title="Heading and overview">
        <input aria-label="Heading" disabled={!editable} value={payload.heading} onChange={(e) => update((p) => void (p.heading = e.target.value))} className={`${area} text-base font-semibold`} />
        <Issues issues={issues} block="heading" />
        {payload.overview ? (
          <div className="mt-3">
            <textarea
              aria-label="Overview"
              disabled={!editable}
              rows={3}
              value={payload.overview.text}
              onChange={(e) => update((p) => void (p.overview!.text = e.target.value))}
              className={area}
            />
            <Refs support={payload.overview.support} />
            <Issues issues={issues} block="overview" />
          </div>
        ) : (
          <p className="mt-2 text-ink-muted">No overview: this page is built from first-person reviews (D64).</p>
        )}
      </Panel>

      {(["advantages", "considerations"] as const).map((block) => (
        <Panel key={block} title={block === "advantages" ? `Advantages (${payload.advantages.length})` : `Considerations (${payload.considerations.length})`}>
          {payload[block].length === 0 ? <p className="text-ink-muted">None.</p> : null}
          <ol className="space-y-3">
            {payload[block].map((item, index) => (
              <li key={index}>
                <textarea aria-label={`${block} ${index + 1}`} disabled={!editable} rows={2} value={item.text} onChange={(e) => update((p) => void (p[block][index].text = e.target.value))} className={area} />
                <input
                  aria-label={`${block} ${index + 1} caveat`}
                  disabled={!editable}
                  placeholder="caveat"
                  value={item.caveat ?? ""}
                  onChange={(e) => update((p) => void (p[block][index].caveat = e.target.value || null))}
                  className={`${area} mt-1 text-[13px]`}
                />
                <Refs support={item.support} />
                <Issues issues={issues} block={block} index={index} />
              </li>
            ))}
          </ol>
        </Panel>
      ))}

      <Panel title={`First-person reviews (${payload.reviews.length})`}>
        <p className="mb-2 text-ink-muted">Shown exactly as approved. You can remove one or change the order; the words cannot be edited here.</p>
        <ol className="space-y-3">
          {payload.reviews.map((review, index) => (
            <li key={review.support.review.id} className="rounded border border-line p-2">
              <p>“{review.text}”</p>
              <p className="text-ink-muted">{creditLine(review.credit)}</p>
              {editable ? (
                <div className="mt-1 flex gap-2 text-xs">
                  <button type="button" disabled={index === 0} className="underline disabled:opacity-40" onClick={() => update((p) => void p.reviews.splice(index - 1, 0, ...p.reviews.splice(index, 1)))}>
                    move up
                  </button>
                  <button type="button" className="text-danger underline" onClick={() => update((p) => void p.reviews.splice(index, 1))}>
                    remove from page
                  </button>
                </div>
              ) : null}
              <Issues issues={issues} block="reviews" index={index} />
            </li>
          ))}
        </ol>
        <Issues issues={issues.filter((i) => i.item_index === null)} block="reviews" />
      </Panel>

      {payload.questions.length ? (
        <Panel title="Buyer questions">
          <ol className="space-y-3">
            {payload.questions.map((q, index) => (
              <li key={index} className="space-y-1">
                <input aria-label={`question ${index + 1}`} disabled={!editable} value={q.question} onChange={(e) => update((p) => void (p.questions[index].question = e.target.value))} className={area} />
                <textarea aria-label={`answer ${index + 1}`} disabled={!editable} rows={2} value={q.answer} onChange={(e) => update((p) => void (p.questions[index].answer = e.target.value))} className={area} />
                <Refs support={q.support} />
                <Issues issues={issues} block="questions" index={index} />
              </li>
            ))}
          </ol>
        </Panel>
      ) : null}

      <Panel title="Coverage note and metadata">
        <textarea aria-label="Coverage note" disabled={!editable} rows={2} value={payload.coverage_note} onChange={(e) => update((p) => void (p.coverage_note = e.target.value))} className={area} />
        <Issues issues={issues} block="coverage_note" />
        <input aria-label="Page title" disabled={!editable} value={payload.metadata.title} maxLength={70} onChange={(e) => update((p) => void (p.metadata.title = e.target.value))} className={`${area} mt-3`} />
        <textarea aria-label="Page description" disabled={!editable} rows={2} maxLength={170} value={payload.metadata.description} onChange={(e) => update((p) => void (p.metadata.description = e.target.value))} className={`${area} mt-2`} />
        <Issues issues={issues} block="metadata" />
      </Panel>

      {editable ? (
        <Panel title="Save as a new revision">
          <label className="block">
            <span className="mb-1 block text-ink-muted">Reason for the edit (required)</span>
            <input value={reason} onChange={(e) => setReason(e.target.value)} className={area} />
          </label>
          {error ? (
            <p role="alert" className="mt-2 text-danger">
              {error}
              {error.includes("latest") || error.includes("newer") ? (
                <button type="button" className="ml-2 underline" onClick={() => router.refresh()}>
                  Reload the newest revision
                </button>
              ) : null}
            </p>
          ) : null}
          <button
            type="button"
            data-testid="save-revision"
            disabled={!dirty || !reason.trim() || busy}
            onClick={save}
            className="mt-3 rounded bg-accent px-3 py-1.5 font-medium text-white disabled:opacity-50"
          >
            {busy ? "Checking…" : "Save and run QA"}
          </button>
          <p className="mt-2 text-xs text-ink-muted">Saving creates revision {revision.revision + 1}; any earlier approval does not carry over.</p>
        </Panel>
      ) : null}
    </div>
  );
}
