"use client";

import { useRouter } from "next/navigation";
import { useRef, useState } from "react";

import { Panel } from "@/components/ui";
import { newKey, send } from "@/lib/api-browser";

type Accepted = { run_id: string | null; job_id: string | null };

/** Start the project's full run (D58): collection over the chosen window and sources, then analysis up to the review
 * queue. A run spends paid credits (search, scraping and Claude within the model budget), so it asks first. */
export function StartRunForm({ projectId, connectors }: { projectId: string; connectors: string[] }) {
  const router = useRouter();
  const dialog = useRef<HTMLDialogElement>(null);
  const key = useRef(newKey("run"));
  const [days, setDays] = useState(90);
  const [chosen, setChosen] = useState<string[]>(connectors);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function start() {
    setBusy(true);
    setError(null);
    const result = await send<Accepted>(
      "POST",
      `/v1/projects/${projectId}/runs`,
      { window_days: days, connectors: chosen.length ? chosen : null },
      { idempotencyKey: key.current },
    );
    setBusy(false);
    if (!result.ok || !result.data?.run_id) {
      setError(result.message ?? "The run was not started");
      return;
    }
    dialog.current?.close();
    key.current = newKey("run");
    router.push(`/console/runs/${result.data.run_id}`);
  }

  return (
    <Panel title="Start a full run">
      <div className="flex flex-wrap items-end gap-4">
        <label>
          <span className="mb-1 block text-ink-muted">Window (days back)</span>
          <input type="number" min={1} max={3650} value={days} onChange={(e) => setDays(Number(e.target.value))} className="w-28 rounded border border-line px-2 py-1" />
        </label>
        <fieldset className="flex flex-wrap gap-3">
          <legend className="mb-1 text-ink-muted">Sources (the project&apos;s enabled ones)</legend>
          {connectors.map((c) => (
            <label key={c} className="flex items-center gap-1">
              <input type="checkbox" checked={chosen.includes(c)} onChange={(e) => setChosen(e.target.checked ? [...chosen, c] : chosen.filter((x) => x !== c))} />
              <span className="font-mono text-xs">{c}</span>
            </label>
          ))}
        </fieldset>
        <button type="button" data-testid="start-run" onClick={() => dialog.current?.showModal()} className="rounded bg-accent px-3 py-1.5 font-medium text-white">
          Start run
        </button>
      </div>
      <dialog ref={dialog} aria-label="Start run" className="w-full max-w-lg rounded-lg border border-line p-0 backdrop:bg-black/30">
        <div className="space-y-3 p-5">
          <h2 className="text-base font-semibold">Start a run now?</h2>
          <p className="text-ink-muted">
            This calls paid services: the search, scraping and video sources selected, then the Claude model for analysis within the
            model budget. Collection and analysis continue in the background; reviews wait for a moderator.
          </p>
          {error ? (
            <p role="alert" className="text-danger">
              {error}
            </p>
          ) : null}
          <div className="flex justify-end gap-2">
            <button type="button" className="rounded border border-line px-3 py-1" onClick={() => dialog.current?.close()}>
              Cancel
            </button>
            <button type="button" disabled={busy} onClick={start} className="rounded bg-accent px-3 py-1 font-medium text-white disabled:opacity-60">
              {busy ? "Starting…" : "Start the run"}
            </button>
          </div>
        </div>
      </dialog>
    </Panel>
  );
}
