import type { Metadata } from "next";
import Link from "next/link";

import { StatusBadge } from "@/components/StatusBadge";
import { EmptyState, ErrorState, MoreLink, Table, Td, Th } from "@/components/ui";
import { apiGet, backendInfo, currentUser, type Schemas } from "@/lib/api-server";
import { connectorName, formatTime, stageLabel } from "@/lib/format";
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

  return (
    <div className="space-y-6">
      {mayStart ? <StartRunForm projectId={projectId} enabled={enabled} status={status} analysisMode={info.analysis_mode} /> : null}
      {runs.data.items.length === 0 ? (
        <EmptyState>No run yet. A researcher starts it here: it collects people&apos;s reviews, reads them and queues them for a moderator.</EmptyState>
      ) : (
        <Table label="Runs">
          <thead>
            <tr>
              <Th>Run</Th>
              <Th>Stage</Th>
              <Th>Window</Th>
              <Th>Coverage</Th>
              <Th>Spend</Th>
              <Th>Note</Th>
            </tr>
          </thead>
          <tbody>
            {runs.data.items.map((run) => (
              <tr key={run.id}>
                <Td>
                  <Link href={`/console/runs/${run.id}`} className="font-mono text-xs text-accent underline">
                    {run.id}
                  </Link>
                  <div className="text-ink-muted">{formatTime(run.created_at)}</div>
                </Td>
                <Td>
                  <StatusBadge status={run.stage} text={stageLabel(run.stage)} />
                </Td>
                <Td className="text-ink-muted">
                  {formatTime(run.window.from)} to {formatTime(run.window.to)}
                </Td>
                <Td>
                  {run.coverage.map((c) => (
                    <div key={c.connector_id} className="flex items-center gap-1">
                      <span className="text-xs">{connectorName(c.connector_id)}</span> <StatusBadge status={c.status} />
                      <span className="text-xs text-ink-muted">{c.fetched} read</span>
                    </div>
                  ))}
                </Td>
                <Td>
                  ${run.budget.spent_usd.toFixed(3)}
                  {run.budget.exhausted ? <StatusBadge status="budget_exhausted" /> : null}
                </Td>
                <Td className="max-w-sm text-ink-muted">{run.outcome_note}</Td>
              </tr>
            ))}
          </tbody>
        </Table>
      )}
      <MoreLink cursor={runs.data.next_cursor} params={{}} path={`/console/projects/${projectId}/runs`} />
    </div>
  );
}
