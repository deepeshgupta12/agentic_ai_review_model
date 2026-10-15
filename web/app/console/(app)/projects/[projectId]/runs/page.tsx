import type { Metadata } from "next";
import Link from "next/link";

import { AutoRefresh } from "@/components/AutoRefresh";
import { CoverageList } from "@/components/CoverageList";
import { Icon } from "@/components/icons";
import { StatusBadge } from "@/components/StatusBadge";
import { BUTTON, EmptyState, ErrorState, MoreLink } from "@/components/ui";
import { apiGet, backendInfo, currentUser, type Schemas } from "@/lib/api-server";
import { formatDay, formatTime, runBadge, runIsWorking } from "@/lib/format";
import { can } from "@/lib/roles";

import { StartRunForm } from "./StartRunForm";

export const metadata: Metadata = { title: "Runs" };

export default async function RunsPage({
  params,
  searchParams,
}: {
  params: Promise<{ projectId: string }>;
  searchParams: Promise<{ cursor?: string }>;
}) {
  const { projectId } = await params;
  const { cursor } = await searchParams;
  const me = await currentUser();
  const mayStart = can(me?.roles, "startRun");
  const [runs, detail, health, info] = await Promise.all([
    apiGet<Schemas["RunPage"]>(`/v1/projects/${projectId}/runs`, { cursor, limit: 20 }),
    apiGet<Schemas["ProjectDetail"]>(`/v1/projects/${projectId}`),
    mayStart ? apiGet<Schemas["ConnectorHealthList"]>("/v1/connectors/health") : null,
    backendInfo(),
  ]);
  if (!runs.data) return <ErrorState status={runs.status} error={runs.error} requestId={runs.requestId} />;
  const enabled = (detail.data?.config.sources ?? []).filter((s) => s.enabled).map((s) => s.connector_id);
  const status = Object.fromEntries((health?.data?.connectors ?? []).map((c) => [c.connector_id, c.status]));

  const working = runs.data.items.find((run) => runIsWorking(run));
  const running = working !== undefined;

  return (
    <div className="space-y-6">
      {running ? (
        <div className="flex flex-wrap items-center gap-3 rounded-lg border border-info/20 bg-info-soft px-4 py-3 text-ink">
          <AutoRefresh active />
          <span>A run is working; its numbers below update as it goes.</span>
          {working ? (
            <Link href={`/console/runs/${working.id}`} className={`ml-auto ${BUTTON.secondary}`}>
              Follow the run <Icon name="arrow" />
            </Link>
          ) : null}
        </div>
      ) : null}
      {mayStart ? (
        <StartRunForm
          projectId={projectId}
          enabled={enabled}
          status={status}
          analysisMode={info.analysis_mode}
          busyRunId={working?.id ?? null}
        />
      ) : null}
      <section aria-labelledby="runs-heading" className="space-y-3">
        <h2 id="runs-heading" className="text-lg font-semibold tracking-tight">
          Runs
        </h2>
        {runs.data.items.length === 0 ? (
          <EmptyState>No run yet. A researcher starts it here: it collects people&apos;s reviews, reads them and queues them for a moderator.</EmptyState>
        ) : (
          <ul className="space-y-3" aria-label="Runs">
            {runs.data.items.map((run) => {
              const badge = runBadge(run);
              return (
                <li key={run.id} className="rounded-lg border border-line bg-surface shadow-card">
                  <div className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-line px-5 py-3">
                    <StatusBadge status={badge.status} text={badge.text} size="md" />
                    <Link href={`/console/runs/${run.id}`} className="font-semibold hover:text-accent hover:underline">
                      Run started {formatTime(run.created_at)}
                    </Link>
                    <span className="font-mono text-[11px] text-ink-muted">{run.id}</span>
                    <span className="ml-auto flex items-center gap-4 text-[13px] text-ink-muted">
                      <span>
                        reviews from {formatDay(run.window.from)} to {formatDay(run.window.to)}
                      </span>
                      <span className="inline-flex items-center gap-1">
                        <Icon name="coins" className="h-3.5 w-3.5" />${run.budget.spent_usd.toFixed(3)}
                      </span>
                      {run.budget.exhausted ? <StatusBadge status="budget_exhausted" text="budget reached" /> : null}
                    </span>
                  </div>
                  <div className="grid gap-4 px-5 py-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,22rem)]">
                    <CoverageList rows={run.coverage} stage={run.stage} empty="no source" />
                    <div className="flex flex-col gap-3">
                      {run.outcome_note ? <p className="rounded-md bg-surface-sunken px-3 py-2 text-[13px] text-ink-muted">{run.outcome_note}</p> : null}
                      <Link href={`/console/runs/${run.id}`} className={`mt-auto self-start ${BUTTON.secondary}`}>
                        Open the run <Icon name="arrow" />
                      </Link>
                    </div>
                  </div>
                </li>
              );
            })}
          </ul>
        )}
        <MoreLink cursor={runs.data.next_cursor} params={{}} path={`/console/projects/${projectId}/runs`} />
      </section>
    </div>
  );
}
