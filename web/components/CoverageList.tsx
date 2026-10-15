import { SourceIcon } from "@/components/icons";
import { StatusBadge } from "@/components/StatusBadge";
import { ProgressBar } from "@/components/ui";
import { activity, connectorName, coverageState } from "@/lib/format";

type Coverage = { connector_id: string; status: string; fetched: number; matched: number; note: string | null };

/** A run's sources with their live state and counts (portfolio and run lists): queued, running with what it is
 * doing and how far it got, not finished (the run moved on without it), or its final status; "read" is what was
 * stored, "matched" what belongs to the project. */
export function CoverageList({ rows, stage, empty = "no run yet" }: { rows: Coverage[]; stage?: string; empty?: string }) {
  if (rows.length === 0) return <span className="text-ink-muted">{empty}</span>;
  return (
    <ul className="divide-y divide-line/70">
      {rows.map((c) => {
        const state = coverageState(c, stage);
        const running = state.text === "running";
        const now = running ? activity(state.detail) : null;
        const muted = c.status === "access_pending" || state.text === "queued";
        return (
          <li key={c.connector_id} className="py-1.5 first:pt-0 last:pb-0" data-testid="coverage-row">
            <div className={`flex items-center gap-2 ${muted ? "opacity-70" : ""}`}>
              <SourceIcon connectorId={c.connector_id} size="sm" />
              <span className="min-w-0 flex-1 truncate text-[13px]">{connectorName(c.connector_id)}</span>
              {state.text !== "queued" && c.status !== "access_pending" ? (
                <span className="text-xs tabular-nums text-ink-muted">
                  <span className="font-medium text-ink">{c.fetched}</span> read · <span className="font-medium text-ink">{c.matched}</span> matched
                </span>
              ) : null}
              <StatusBadge status={state.status} text={state.text} />
            </div>
            {running && now ? (
              <div className="mt-1 pl-8">
                {now.step ? (
                  <ProgressBar value={now.step.done} max={now.step.total} tone="info" live size="sm" label={`${connectorName(c.connector_id)}: ${now.doing}`} />
                ) : null}
                {now.doing ? (
                  <p className="mt-0.5 truncate text-[11px] text-ink-muted" title={state.detail ?? undefined}>
                    {now.doing}
                  </p>
                ) : null}
              </div>
            ) : null}
          </li>
        );
      })}
    </ul>
  );
}
