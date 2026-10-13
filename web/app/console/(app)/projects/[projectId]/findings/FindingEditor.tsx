"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { send } from "@/lib/api-browser";
import type { components } from "@/lib/api-schema";

type Finding = components["schemas"]["Finding"];
type Claim = components["schemas"]["Claim"];

/** Edit as a new revision (docs/09): wording, kind, which claims, caveats. The backend refuses an attribution the
 * claims do not support, numbers not in the claims and dropped required caveats; a newer revision is a conflict. */
export function FindingEditor({ finding, claims }: { finding: Finding; claims: Claim[] }) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [wording, setWording] = useState(finding.wording);
  const [kind, setKind] = useState(finding.kind);
  const [chosen, setChosen] = useState(finding.claims.map((c) => c.id));
  const [caveats, setCaveats] = useState(finding.caveats.join("\n"));
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);

  async function save(event: React.FormEvent) {
    event.preventDefault();
    const body = {
      base: { id: finding.id, revision: finding.revision },
      kind,
      aspect: finding.aspect,
      wording,
      attribution: finding.attribution,
      claims: claims.filter((c) => chosen.includes(c.id)).map((c) => ({ id: c.id, revision: c.revision })),
      caveats: caveats.split("\n").map((c) => c.trim()).filter(Boolean),
      reason,
    };
    const result = await send("POST", `/v1/findings/${finding.id}/revisions`, body);
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
        Edit as a new revision
      </button>
    );
  }
  const input = "w-full rounded border border-line px-2 py-1";
  return (
    <form onSubmit={save} className="space-y-2 rounded border border-line p-3">
      <label className="block">
        <span className="mb-1 block text-ink-muted">Wording</span>
        <textarea value={wording} onChange={(e) => setWording(e.target.value)} rows={3} className={input} required />
      </label>
      <label className="block">
        <span className="mb-1 block text-ink-muted">Kind</span>
        <select value={kind} onChange={(e) => setKind(e.target.value as typeof kind)} className="rounded border border-line px-2 py-1">
          <option value="pro">pro</option>
          <option value="con">con</option>
          <option value="neutral">neutral</option>
        </select>
      </label>
      <fieldset>
        <legend className="mb-1 text-ink-muted">Claims it rests on</legend>
        {claims.map((c) => (
          <label key={c.id} className="flex items-start gap-2">
            <input type="checkbox" checked={chosen.includes(c.id)} onChange={(e) => setChosen(e.target.checked ? [...chosen, c.id] : chosen.filter((x) => x !== c.id))} />
            <span>{c.statement}</span>
          </label>
        ))}
      </fieldset>
      <label className="block">
        <span className="mb-1 block text-ink-muted">Caveats (one per line; the required ones cannot be removed)</span>
        <textarea value={caveats} onChange={(e) => setCaveats(e.target.value)} rows={2} className={input} />
      </label>
      <label className="block">
        <span className="mb-1 block text-ink-muted">Reason for the edit (required)</span>
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
