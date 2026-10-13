"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { StatusBadge } from "@/components/StatusBadge";
import { Panel } from "@/components/ui";
import { send } from "@/lib/api-browser";
import type { components } from "@/lib/api-schema";

type Config = components["schemas"]["ProjectConfig"];

const STATUSES = ["new_launch", "under_construction", "partially_ready", "ready_to_move"] as const;

/** Configuration at the expected version (docs/03): sources, languages, refresh, negative keywords, and a new
 * construction-status record. A stale version is a conflict with a reload, never a silent overwrite. */
export function ConfigForm({ config, connectorStatus, canEdit }: { config: Config; connectorStatus: Record<string, string>; canEdit: boolean }) {
  const router = useRouter();
  const [sources, setSources] = useState(config.sources);
  const [keywords, setKeywords] = useState(config.negative_keywords.join("\n"));
  const [languages, setLanguages] = useState(config.input_languages.join(", "));
  const [cadence, setCadence] = useState(config.refresh.cadence);
  const [lookback, setLookback] = useState(config.refresh.lookback_days);
  const [status, setStatus] = useState<(typeof STATUSES)[number] | "">("");
  const [asOf, setAsOf] = useState(new Date().toISOString().slice(0, 10));
  const [note, setNote] = useState("");
  const [message, setMessage] = useState<{ tone: "ok" | "error"; text: string } | null>(null);
  const [conflict, setConflict] = useState(false);

  async function save(event: React.FormEvent) {
    event.preventDefault();
    const body: Record<string, unknown> = {
      expected_version: config.version,
      sources,
      negative_keywords: keywords.split("\n").map((s) => s.trim()).filter(Boolean),
      input_languages: languages.split(",").map((s) => s.trim()).filter(Boolean),
      refresh: { cadence, lookback_days: lookback },
    };
    if (status) {
      body.construction_status = [
        ...config.construction_status,
        { status, applies_to: { kind: "project", rera_id: null }, basis: "moderator", as_of: asOf, note: note.trim() || null },
      ];
    }
    const result = await send("PATCH", `/v1/projects/${config.project_id}`, body);
    setConflict(result.status === 409);
    if (!result.ok) {
      setMessage({ tone: "error", text: result.message ?? "Not saved" });
      return;
    }
    setMessage({ tone: "ok", text: "Saved as a new configuration version." });
    setStatus("");
    router.refresh();
  }

  const input = "rounded border border-line px-2 py-1 disabled:bg-surface-sunken";
  return (
    <Panel title="Sources and refresh">
      <form onSubmit={save} className="grid gap-4 lg:grid-cols-2">
        <fieldset className="space-y-1" disabled={!canEdit}>
          <legend className="mb-1 font-medium">Sources</legend>
          {sources.map((s, i) => (
            <label key={s.connector_id} className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={s.enabled}
                onChange={(e) => setSources(sources.map((x, j) => (j === i ? { ...x, enabled: e.target.checked } : x)))}
              />
              <span className="font-mono text-xs">{s.connector_id}</span>
              <StatusBadge status={connectorStatus[s.connector_id] ?? "unknown"} />
            </label>
          ))}
          <p className="text-xs text-ink-muted">A source that is access pending is recorded as not run until its credential is demonstrated.</p>
        </fieldset>
        <fieldset className="space-y-3" disabled={!canEdit}>
          <label className="block">
            <span className="mb-1 block text-ink-muted">Input languages (comma separated tags)</span>
            <input value={languages} onChange={(e) => setLanguages(e.target.value)} className={`${input} w-full`} />
          </label>
          <div className="flex flex-wrap gap-3">
            <label>
              <span className="mb-1 block text-ink-muted">Refresh</span>
              <select value={cadence} onChange={(e) => setCadence(e.target.value as typeof cadence)} className={input}>
                <option value="daily_incremental_and_manual">daily and manual</option>
                <option value="manual_only">manual only</option>
              </select>
            </label>
            <label>
              <span className="mb-1 block text-ink-muted">Look back (days)</span>
              <input type="number" min={1} max={3650} value={lookback} onChange={(e) => setLookback(Number(e.target.value))} className={`${input} w-24`} />
            </label>
          </div>
          <label className="block">
            <span className="mb-1 block text-ink-muted">Negative keywords (one per line)</span>
            <textarea value={keywords} onChange={(e) => setKeywords(e.target.value)} rows={3} className={`${input} w-full`} />
          </label>
          <div className="rounded border border-line p-3">
            <p className="mb-2 font-medium">Add a construction-status record</p>
            <div className="flex flex-wrap gap-2">
              <select aria-label="Status" value={status} onChange={(e) => setStatus(e.target.value as typeof status)} className={input}>
                <option value="">no change</option>
                {STATUSES.map((s) => (
                  <option key={s} value={s}>
                    {s.replaceAll("_", " ")}
                  </option>
                ))}
              </select>
              <input aria-label="As of" type="date" value={asOf} onChange={(e) => setAsOf(e.target.value)} className={input} />
              <input aria-label="Note" placeholder="note (optional)" value={note} onChange={(e) => setNote(e.target.value)} className={`${input} flex-1`} />
            </div>
          </div>
        </fieldset>
        <div className="lg:col-span-2">
          {message ? (
            <p role={message.tone === "error" ? "alert" : "status"} className={message.tone === "error" ? "mb-2 text-danger" : "mb-2 text-ok"}>
              {message.text}
              {conflict ? (
                <button type="button" className="ml-2 underline" onClick={() => router.refresh()}>
                  Reload the current version
                </button>
              ) : null}
            </p>
          ) : null}
          {canEdit ? (
            <button type="submit" className="rounded bg-accent px-3 py-1.5 font-medium text-white">
              Save configuration (version {config.version})
            </button>
          ) : (
            <p className="text-ink-muted">Only a researcher can change the configuration.</p>
          )}
        </div>
      </form>
    </Panel>
  );
}
