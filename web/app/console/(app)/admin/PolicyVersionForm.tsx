"use client";

import { useRouter } from "next/navigation";
import { useRef, useState } from "react";

import { newKey, send } from "@/lib/api-browser";
import type { components } from "@/lib/api-schema";

type Policy = components["schemas"]["SourcePolicy"];

/** A new immutable policy version (admin): start from the family's current version, change the rights, give the basis.
 * Narrowing rights starts dependency invalidation in the backend. */
export function PolicyVersionForm({ policies }: { policies: Policy[] }) {
  const router = useRouter();
  const latest = new Map<string, Policy>();
  for (const p of policies) {
    const known = latest.get(p.family);
    if (!known || known.policy_version < p.policy_version) latest.set(p.family, p);
  }
  const families = [...latest.keys()].sort();
  const [family, setFamily] = useState(families[0] ?? "");
  const [rights, setRights] = useState(() => pick(latest.get(families[0] ?? "")));
  const [basis, setBasis] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const key = useRef(newKey("policy"));

  function pick(p: Policy | undefined) {
    return {
      collection_allowed: p?.collection_allowed ?? false,
      ai_processing_allowed: p?.ai_processing_allowed ?? false,
      quotation_allowed: p?.quotation_allowed ?? false,
      derived_publication_allowed: p?.derived_publication_allowed ?? false,
    };
  }

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    const base = latest.get(family);
    if (!base) return;
    const body = {
      family,
      ...rights,
      attribution_required: base.attribution_required,
      retention_days: base.retention_days,
      hosts: base.hosts,
      excluded_hosts: base.excluded_hosts,
      conditions: base.conditions,
      robots_txt: base.robots_txt,
      host_scope: base.host_scope,
      basis,
      effective_from: new Date().toISOString().replace(/\.\d{3}Z$/, "Z"),
      expires_at: base.expires_at,
    };
    setBusy(true);
    // one key per intended version: a double submit or a retry stores one version, not two (audit, 14 Oct 2026)
    const result = await send("POST", "/v1/admin/source-policies", body, { idempotencyKey: key.current });
    setBusy(false);
    setMessage(result.ok ? "New version stored." : result.message);
    if (result.ok) {
      key.current = newKey("policy");
      setBasis("");
      router.refresh();
    }
  }

  return (
    <form onSubmit={submit} className="mt-4 space-y-2 rounded border border-line p-3" aria-label="New policy version">
      <p className="font-medium">New policy version</p>
      <div className="flex flex-wrap items-center gap-3">
        <select
          aria-label="Family"
          value={family}
          onChange={(e) => {
            setFamily(e.target.value);
            setRights(pick(latest.get(e.target.value)));
          }}
          className="rounded border border-line px-2 py-1"
        >
          {families.map((f) => (
            <option key={f} value={f}>
              {f}
            </option>
          ))}
        </select>
        {(Object.keys(rights) as (keyof typeof rights)[]).map((k) => (
          <label key={k} className="flex items-center gap-1">
            <input type="checkbox" checked={rights[k]} onChange={(e) => setRights({ ...rights, [k]: e.target.checked })} />
            {k.replace("_allowed", "").replaceAll("_", " ")}
          </label>
        ))}
      </div>
      <input aria-label="Basis" required value={basis} onChange={(e) => setBasis(e.target.value)} placeholder="basis: who decided, when, why" className="w-full rounded border border-line px-2 py-1" />
      {message ? <p role="status">{message}</p> : null}
      <button type="submit" disabled={busy} className="rounded bg-accent px-3 py-1 text-white disabled:opacity-60">
        {busy ? "Storing…" : "Store version"}
      </button>
    </form>
  );
}
