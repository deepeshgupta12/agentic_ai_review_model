import { SourceIcon } from "@/components/icons";
import { StatusBadge } from "@/components/StatusBadge";
import { ProgressBar } from "@/components/ui";
import { activity, connectorName, countLabel, coverageState, formatTime, isSearchEngine } from "@/lib/format";

type Coverage = {
  connector_id: string;
  status: string;
  attempted_queries: number;
  fetched: number;
  matched: number;
  analysed: number;
  metadata_only: number;
  last_success_at: string | null;
  note: string | null;
};

/** One source of a run: its state, the step it is on while it works (from its own note), its counts and what its
 * note says. Access pending, partial and unavailable are not zero discussion: they say a source was not fully read. */
export function SourceCard({ c, stage }: { c: Coverage; stage: string }) {
  const state = coverageState(c, stage);
  const running = state.text === "running";
  const said = activity(state.detail);
  const pending = c.status === "access_pending";
  const queued = state.text === "queued";
  const search = isSearchEngine(c.connector_id);
  // a search engine's results are addresses: the web reader reads and matches the pages (its card has those counts)
  // results stored but left unread (not naming the project, single listings); results never collected are not stored
  const unread = said.counts.filter((n) => n.key.startsWith("not_read:")).reduce((sum, n) => sum + (Number(n.value) || 0), 0);
  const numbers: [string, number][] = search
    ? [
        ["Searches", c.attempted_queries],
        ["Results", c.fetched],
        ["Name the project", Math.max(0, c.fetched - unread)],
      ]
    : [
        ["Queries", c.attempted_queries],
        ["Read", c.fetched],
        ["Matched", c.matched],
        ["Analysed", c.analysed],
      ];
  return (
    <article
      aria-label={connectorName(c.connector_id)}
      className={`flex flex-col rounded-lg border bg-surface p-4 shadow-card transition ${
        running ? "border-info/40 ring-2 ring-info/10" : "border-line"
      } ${pending ? "bg-surface/70" : ""}`}
    >
      <header className="flex items-start gap-3">
        <SourceIcon connectorId={c.connector_id} />
        <div className="min-w-0 flex-1">
          <h3 className={`truncate font-semibold ${pending ? "text-ink-muted" : ""}`}>{connectorName(c.connector_id)}</h3>
          <p className="truncate font-mono text-[11px] text-ink-muted">{c.connector_id}</p>
        </div>
        <StatusBadge status={state.status} text={state.text} />
      </header>

      {running ? (
        <div className="mt-3 rounded-md bg-info-soft/60 px-3 py-2">
          <div className="mb-1.5 flex items-baseline justify-between gap-2 text-xs">
            <span className="min-w-0 truncate font-medium text-info" title={said.doing}>
              {said.doing || "working"}
            </span>
            {said.step ? (
              <span className="shrink-0 tabular-nums text-info">
                {said.step.done} / {said.step.upTo ? "≤" : ""}
                {said.step.total}
              </span>
            ) : null}
          </div>
          {said.step ? (
            <ProgressBar
              value={said.step.done}
              max={said.step.total}
              tone="info"
              live
              size="sm"
              label={`${connectorName(c.connector_id)}: ${said.doing}`}
            />
          ) : (
            // working on something without a count to show: a moving bar, no made-up share
            <div aria-hidden="true" className="h-1.5 w-full overflow-hidden rounded-full bg-idle-soft">
              <div className="bar-live h-full w-full rounded-full bg-info/50" />
            </div>
          )}
        </div>
      ) : null}

      {pending || queued ? (
        <p className="mt-3 text-[13px] text-ink-muted">
          {pending ? said.doing || "No credential or adapter configured; not read." : "Waiting for its turn; it starts when a worker is free."}
        </p>
      ) : (
        <dl className={`mt-3 grid gap-2 ${search ? "grid-cols-3" : "grid-cols-4"}`}>
          {numbers.map(([name, value]) => (
            <div key={name} className="rounded-md bg-surface-sunken px-2 py-1.5">
              <dt className="text-[10px] font-medium uppercase tracking-wide text-ink-muted">{name}</dt>
              <dd className="text-base font-semibold tabular-nums">{value}</dd>
            </div>
          ))}
        </dl>
      )}

      {!pending && !running && said.doing ? <p className="mt-2 text-xs text-ink-muted">{said.doing}</p> : null}
      {search && !pending && !queued ? (
        <p className="mt-2 text-xs text-ink-muted">Results are addresses only: the web reader reads the ones that name the project and matches them.</p>
      ) : null}
      {!pending && said.counts.length ? (
        <ul className="mt-2 flex flex-wrap gap-1" aria-label="Counts">
          {said.counts.map((count) => (
            <li
              key={count.key}
              className={`rounded-md px-1.5 py-0.5 text-[11px] ring-1 ring-inset ${
                count.key === "errors" ? "bg-danger-soft text-danger ring-danger/15" : "bg-surface-sunken text-ink-muted ring-line"
              }`}
            >
              {countLabel(count.key)}
              {count.value ? <span className="ml-1 font-semibold text-ink">{count.value}</span> : null}
            </li>
          ))}
        </ul>
      ) : null}

      {!pending && !queued ? (
        <p className="mt-auto pt-3 text-[11px] text-ink-muted">
          Last success {formatTime(c.last_success_at)}
          {c.metadata_only ? ` · ${c.metadata_only} metadata only` : ""}
        </p>
      ) : null}
    </article>
  );
}
