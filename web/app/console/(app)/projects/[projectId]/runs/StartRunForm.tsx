"use client";

import { useRouter } from "next/navigation";
import { useRef, useState } from "react";

import { SourceIcon } from "@/components/icons";
import { StatusBadge } from "@/components/StatusBadge";
import { BUTTON, Panel } from "@/components/ui";
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
  // the product owner's default look-back (I08: 90 days, raised to 120 on 15 Oct 2026); any 1 to 3650 may be chosen
  const [days, setDays] = useState(120);
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
    <Panel title="Start a run" icon="search" description="Collect people's reviews from the chosen sources, then read them for the moderator.">
      <div className="space-y-4">
        <fieldset>
          <legend className="mb-3 text-[13px] font-medium text-ink-muted">Where to look for people&apos;s reviews (the sources enabled in Setup)</legend>
          {groups.length === 0 ? <p className="text-warn">No source is enabled for this project. Enable one in Setup.</p> : null}
          <ul className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            {groups.map((g) => {
              const on = chosen.includes(g.key);
              return (
                <li key={g.key}>
                  <label
                    className={`flex h-full cursor-pointer items-start gap-3 rounded-lg border p-3.5 transition ${
                      on ? "border-accent/50 bg-accent-soft/60 ring-1 ring-accent/20" : "border-line bg-surface hover:border-line-strong"
                    }`}
                  >
                    <input
                      type="checkbox"
                      className="mt-1 h-4 w-4"
                      checked={on}
                      onChange={(e) => setChosen(e.target.checked ? [...chosen, g.key] : chosen.filter((x) => x !== g.key))}
                    />
                    <span className="min-w-0 flex-1">
                      <span className="flex items-center gap-2">
                        <SourceIcon connectorId={g.connectors[0]} size="sm" />
                        <span className="font-semibold">{g.label}</span>
                      </span>
                      {g.detail ? <span className="mt-1 block text-[13px] text-ink-muted">{g.detail}</span> : null}
                      {unused(g) ? <span className="mt-1 block text-[13px] text-warn">Not read in the reviews-only analysis.</span> : null}
                      <span className="mt-2 flex flex-wrap gap-1.5">
                        {g.connectors.map((c) => (
                          <span key={c} className="flex items-center gap-1 text-xs text-ink-muted">
                            {connectorName(c)} <StatusBadge status={status[c] ?? "unknown"} />
                          </span>
                        ))}
                      </span>
                    </span>
                  </label>
                </li>
              );
            })}
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
              className="w-28 rounded border border-line-strong px-3 py-2"
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
            className={BUTTON.primary}
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
      <dialog ref={dialog} aria-label="Start run" className="m-auto w-full max-w-lg rounded-xl border border-line p-0">
        <div className="space-y-4 p-6">
          <h2 className="text-lg font-semibold tracking-tight">Start a run now?</h2>
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
          <div className="flex justify-end gap-2 border-t border-line pt-4">
            <button type="button" className={BUTTON.secondary} onClick={() => dialog.current?.close()}>
              Cancel
            </button>
            <button type="button" disabled={busy} onClick={start} className={BUTTON.primary}>
              {busy ? "Starting…" : "Start the run"}
            </button>
          </div>
        </div>
      </dialog>
    </Panel>
  );
}
