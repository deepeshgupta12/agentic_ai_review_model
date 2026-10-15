import { StatusBadge } from "@/components/StatusBadge";
import { connectorName, coverageState } from "@/lib/format";

type Coverage = { connector_id: string; status: string; fetched: number; matched: number; note: string | null };

/** A run's sources with their live state and counts (portfolio and run lists): queued, running with what it is
 * doing, not finished (the run moved on without it), or its final status; "read" is what was stored, "matched" what
 * belongs to the project. */
export function CoverageList({ rows, stage, empty = "no run yet" }: { rows: Coverage[]; stage?: string; empty?: string }) {
  if (rows.length === 0) return <span className="text-ink-muted">{empty}</span>;
  return (
    <ul className="space-y-0.5">
      {rows.map((c) => {
        const state = coverageState(c, stage);
        return (
          <li key={c.connector_id} className="flex flex-wrap items-center gap-1" data-testid="coverage-row">
            <span className="text-xs">{connectorName(c.connector_id)}</span>
            <StatusBadge status={state.status} text={state.text} />
            {state.text !== "queued" ? (
              <span className="text-xs text-ink-muted">
                {c.fetched} read · {c.matched} matched
              </span>
            ) : null}
            {state.text === "running" && state.detail ? (
              <span className="w-full truncate pl-2 text-[11px] text-ink-muted" title={state.detail}>
                {state.detail}
              </span>
            ) : null}
          </li>
        );
      })}
    </ul>
  );
}
