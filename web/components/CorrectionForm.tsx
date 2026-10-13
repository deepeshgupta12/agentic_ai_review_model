"use client";

import { useState } from "react";

/** "Report a correction" on the public page (docs/09 item 9): message, optional contact and a hidden honeypot field.
 * No sign-in; the backend rate-limits by address. */
export function CorrectionForm({ slug, revisionId }: { slug: string; revisionId: string | null }) {
  const [open, setOpen] = useState(false);
  const [state, setState] = useState<"idle" | "sending" | "sent" | "error">("idle");
  const [message, setMessage] = useState<string | null>(null);

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setState("sending");
    const response = await fetch(`/v1/public/projects/${encodeURIComponent(slug)}/corrections`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        message: String(form.get("message") ?? ""),
        contact: String(form.get("contact") ?? "").trim() || null,
        revision_id: revisionId,
        website: String(form.get("website") ?? ""),
      }),
    }).catch(() => null);
    if (response?.status === 202) {
      setState("sent");
      return;
    }
    setState("error");
    setMessage(response?.status === 429 ? "Too many reports from this connection; please try again later." : "The report could not be sent. Please check the message (at least 10 characters).");
  }

  if (state === "sent") {
    return <p className="mt-6 text-[15px]" role="status">Thank you. Our editors will review your report.</p>;
  }
  return (
    <div className="mt-6">
      {!open ? (
        <button type="button" className="text-[15px] text-accent underline" onClick={() => setOpen(true)}>
          Report a correction
        </button>
      ) : (
        <form onSubmit={submit} className="space-y-3 rounded border border-line p-4 text-[15px]">
          <label className="block">
            <span className="mb-1 block">What should be corrected?</span>
            <textarea name="message" required minLength={10} maxLength={2000} rows={4} className="w-full rounded border border-line px-2 py-1" />
          </label>
          <label className="block">
            <span className="mb-1 block">How can we reach you? (optional)</span>
            <input name="contact" maxLength={200} className="w-full rounded border border-line px-2 py-1" />
          </label>
          <div aria-hidden="true" className="hidden">
            <label>
              Website
              <input name="website" tabIndex={-1} autoComplete="off" defaultValue="" />
            </label>
          </div>
          {state === "error" ? <p role="alert" className="text-danger">{message}</p> : null}
          <button type="submit" disabled={state === "sending"} className="rounded bg-accent px-3 py-1 text-white disabled:opacity-60">
            {state === "sending" ? "Sending…" : "Send report"}
          </button>
        </form>
      )}
    </div>
  );
}
