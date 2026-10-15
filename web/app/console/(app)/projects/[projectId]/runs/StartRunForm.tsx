"use client";

import { useRouter } from "next/navigation";
import { useRef, useState } from "react";

import { StatusBadge } from "@/components/StatusBadge";
import { Panel } from "@/components/ui";
import { newKey, send } from "@/lib/api-browser";
import { connectorName, HELPER_CONNECTORS, RUN_SOURCES } from "@/lib/format";

type Accepted = { run_id: string | null; job_id: string | null };

type Group = { key: string; label: string; detail: string; connectors: string[] };

/** Start the project's full run (D58): collection over the chosen window and sources, then the reading of the reviews
 * up to the review queue. A run spends paid credits (search, scraping and Claude within the model budget), so it asks
 * first. Sources are offered as people think of them; the backend still records each connector's coverage. */
export function StartRunForm({
  projectId,
  enabled,
  status,
  analysisMode,
  busyRunId,
}: {
  projectId: string;
  /** The project's enabled connectors (Setup). */
  enabled: string[];
  /** Connector health, when the role may read it. */
  status: Record<string, string>;
  analysisMode: string;
  /** A run of this project that is still working: a second one is not started (the backend refuses it too). */
  busyRunId: string | null;
}) {
  const router = useRouter();
  const dialog = useRef<HTMLDialogElement>(null);
  const key = useRef(newKey("run"));
  const known = new Set<string>(RUN_SOURCES.flatMap((g) => [...g.connectors]));
  const groups: Group[] = [
    ...RUN_SOURCES.map((g) => ({ ...g, connectors: g.connectors.filter((c) => enabled.includes(c)) })),
    ...enabled.filter((c) => !known.has(c) && !HELPER_CONNECTORS.includes(c)).map((c) => ({ key: c, label: connectorName(c), detail: "", connectors: [c] })),
  ].filter((g) => g.connectors.length > 0);
  const unused = (g: Group) => g.key === "registry" && analysisMode === "reviews";
  const [chosen, setChosen] = useState<string[]>(groups.filter((g) => !unused(g)).map((g) => g.key));
  const [days, setDays] = useState(90);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const connectors = groups.filter((g) => chosen.includes(g.key)).flatMap((g) => g.connectors);
  const validDays = Number.isInteger(days) && days >= 1 && days <= 3650;

  async function start() {
    setBusy(true);
    setError(null);
    const result = await send<Accepted>(
      "POST",
      `/v1/projects/${projectId}/runs`,
      { window_days: days, connectors },
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
    <Panel title="Start a run">
      <div className="space-y-4">
        <fieldset>
          <legend className="mb-2 text-ink-muted">Where to look for people&apos;s reviews (the sources enabled in Setup)</legend>
          {groups.length === 0 ? <p className="text-warn">No source is enabled for this project. Enable one in Setup.</p> : null}
          <ul className="grid gap-2 lg:grid-cols-2">
            {groups.map((g) => (
              <li key={g.key}>
                <label className="flex items-start gap-2 rounded border border-line p-2">
                  <input
                    type="checkbox"
                    className="mt-1"
                    checked={chosen.includes(g.key)}
                    onChange={(e) => setChosen(e.target.checked ? [...chosen, g.key] : chosen.filter((x) => x !== g.key))}
                  />
                  <span className="min-w-0">
                    <span className="font-medium">{g.label}</span>
                    {g.detail ? <span className="block text-ink-muted">{g.detail}</span> : null}
                    {unused(g) ? <span className="block text-warn">Not read in the reviews-only analysis.</span> : null}
                    <span className="mt-1 flex flex-wrap gap-1">
                      {g.connectors.map((c) => (
                        <span key={c} className="flex items-center gap-1 text-xs text-ink-muted">
                          {connectorName(c)} <StatusBadge status={status[c] ?? "unknown"} />
                        </span>
                      ))}
                    </span>
                  </span>
                </label>
              </li>
            ))}
          </ul>
          <p className="mt-2 text-xs text-ink-muted">A source that is access pending has no working credential yet; the run records it as not read.</p>
        </fieldset>
        <div className="flex flex-wrap items-end gap-4">
          <label>
            <span className="mb-1 block text-ink-muted">Look back (days)</span>
            <input
              type="number"
              min={1}
              max={3650}
              value={Number.isNaN(days) ? "" : days}
              onChange={(e) => setDays(e.target.valueAsNumber)}
              className="w-28 rounded border border-line px-2 py-1"
            />
          </label>
          <button
            type="button"
            data-testid="start-run"
            disabled={connectors.length === 0 || !validDays || busyRunId !== null}
            onClick={() => {
              setError(null);
              dialog.current?.showModal();
            }}
            className="rounded bg-accent px-3 py-1.5 font-medium text-white disabled:opacity-50"
          >
            Start run
          </button>
          {busyRunId ? (
            <span className="text-warn">
              A run of this project is still working;{" "}
              <a href={`/console/runs/${busyRunId}`} className="underline">
                follow it
              </a>{" "}
              or cancel it first.
            </span>
          ) : null}
          {connectors.length === 0 ? <span className="text-warn">Choose at least one source.</span> : null}
          {!validDays ? <span className="text-warn">Look back 1 to 3650 days.</span> : null}
        </div>
      </div>
      <dialog ref={dialog} aria-label="Start run" className="w-full max-w-lg rounded-lg border border-line p-0 backdrop:bg-black/30">
        <div className="space-y-3 p-5">
          <h2 className="text-base font-semibold">Start a run now?</h2>
          <p className="text-ink-muted">
            This calls paid services: web search, page scraping and video sources as selected, then the Claude model to read the reviews
            within the model budget. It continues in the background; the reviews found then wait for a moderator.
          </p>
          <p className="text-ink-muted">
            Sources: {groups.filter((g) => chosen.includes(g.key)).map((g) => g.label).join(", ")} · last {days} days
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
