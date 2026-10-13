"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { send } from "@/lib/api-browser";
import type { components } from "@/lib/api-schema";

type Review = components["schemas"]["ReviewExcerpt"];
type EvidenceView = components["schemas"]["EvidenceView"];

/** A new revision from the same source: other spans, a shortened or punctuation-only rendering, or a corrected
 * translation. There is no free rewrite: the backend checks the words against the author's (D28). */
export function ReviewEditor({ review, evidence }: { review: Review; evidence: EvidenceView[] }) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [text, setText] = useState(review.text ?? "");
  const [rendering, setRendering] = useState(review.rendering);
  const [spans, setSpans] = useState(review.evidence.map((e) => e.id));
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);

  async function save(event: React.FormEvent) {
    event.preventDefault();
    const chosen = evidence.filter((e) => spans.includes(e.evidence.id)).map((e) => ({ id: e.evidence.id, revision: e.evidence.revision }));
    const body = { base: { id: review.id, revision: review.revision }, evidence: chosen, rendering, text, reason };
    const result = await send("POST", `/v1/review-excerpts/${review.id}/revisions`, body);
    if (!result.ok) {
      setError(result.message);
      return;
    }
    setOpen(false);
    router.refresh();
  }

  if (!open) {
    return (
      <button type="button" className="text-accent underline" onClick={() => setOpen(true)}>
        Choose other spans or fix the translation
      </button>
    );
  }
  const input = "w-full rounded border border-line px-2 py-1";
  return (
    <form onSubmit={save} className="space-y-2 rounded border border-line p-3">
      <fieldset>
        <legend className="mb-1 text-ink-muted">Spans of this source</legend>
        {evidence.map((e) => (
          <label key={e.evidence.id} className="flex items-start gap-2">
            <input
              type="checkbox"
              checked={spans.includes(e.evidence.id)}
              onChange={(ev) => setSpans(ev.target.checked ? [...spans, e.evidence.id] : spans.filter((x) => x !== e.evidence.id))}
            />
            <span className="text-[13px]">{e.evidence.excerpt_text}</span>
          </label>
        ))}
      </fieldset>
      <label className="block">
        <span className="mb-1 block text-ink-muted">Rendering</span>
        <select value={rendering} onChange={(e) => setRendering(e.target.value as typeof rendering)} className="rounded border border-line px-2 py-1">
          <option value="verbatim">verbatim</option>
          <option value="punctuation_normalised">punctuation only (dashes removed)</option>
          <option value="shortened">whole sentences left out</option>
          <option value="translated">translated</option>
        </select>
      </label>
      <label className="block">
        <span className="mb-1 block text-ink-muted">Text as shown (no dashes or hyphens)</span>
        <textarea value={text} onChange={(e) => setText(e.target.value)} rows={4} className={input} required />
      </label>
      <label className="block">
        <span className="mb-1 block text-ink-muted">Reason (required)</span>
        <input value={reason} onChange={(e) => setReason(e.target.value)} className={input} required />
      </label>
      {error ? (
        <p role="alert" className="text-danger">
          {error}
        </p>
      ) : null}
      <div className="flex gap-2">
        <button type="submit" className="rounded bg-accent px-3 py-1 text-white">
          Save new revision
        </button>
        <button type="button" className="rounded border border-line px-3 py-1" onClick={() => setOpen(false)}>
          Cancel
        </button>
      </div>
    </form>
  );
}
