import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { ActionDialog } from "@/components/ActionDialog";
import { StatusBadge } from "@/components/StatusBadge";
import { ErrorState, Mono, Panel, Table, Td, Th } from "@/components/ui";
import { apiGet, currentUser, type Schemas } from "@/lib/api-server";
import { formatTime } from "@/lib/format";
import { can } from "@/lib/roles";

import { RunProgress } from "./RunProgress";

export const metadata: Metadata = { title: "Run" };

const TERMINAL = ["published", "insufficient_evidence", "cancelled"];

export default async function RunPage({ params }: { params: Promise<{ runId: string }> }) {
  const { runId } = await params;
  const [run, me] = await Promise.all([apiGet<Schemas["WorkflowRun"]>(`/v1/runs/${runId}`), currentUser()]);
  if (run.status === 404) notFound();
  if (!run.data) return <ErrorState status={run.status} error={run.error} requestId={run.requestId} />;
  const r = run.data;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-lg font-semibold">Run</h1>
        <Mono>{r.id}</Mono>
        <StatusBadge status={r.stage} />
        <Link href={`/console/projects/${r.project_id}/runs`} className="text-accent underline">
          all runs of this project
        </Link>
        {can(me?.roles, "cancelRun") && !TERMINAL.includes(r.stage) ? (
          <ActionDialog label="Cancel run" title="Cancel this run" path={`/v1/runs/${r.id}/cancel`} body={{}} reason="required" tone="danger" />
        ) : null}
      </div>
      {r.stage === "insufficient_evidence" ? (
        <p className="rounded border border-idle bg-surface p-3">
          Not enough eligible evidence for any finding or review. This is a valid result; no page content is created. The coverage below
          shows what was and was not collected.
        </p>
      ) : null}
      <Panel title="Progress">
        <RunProgress runId={r.id} initialStage={r.stage} terminal={TERMINAL} />
        <p className="mt-3 text-ink-muted">{r.outcome_note}</p>
        <p className="mt-1 text-ink-muted">
          Window {formatTime(r.window.from)} to {formatTime(r.window.to)} · model spend ${r.budget.spent_usd.toFixed(3)} of ${r.budget.max_usd.toFixed(2)}
          {r.budget.exhausted ? " · budget reached" : ""}
        </p>
        {r.content_revision_id ? (
          <Link href={`/console/projects/${r.project_id}/content/${r.content_revision_id}`} className="mt-2 inline-block text-accent underline">
            Open the generated page content
          </Link>
        ) : null}
      </Panel>
      <Panel title="Coverage by source">
        <Table label="Coverage">
          <thead>
            <tr>
              <Th>Source</Th>
              <Th>Status</Th>
              <Th>Queries</Th>
              <Th>Fetched</Th>
              <Th>Matched</Th>
              <Th>Analysed</Th>
              <Th>Metadata only</Th>
              <Th>Last success</Th>
              <Th>Note</Th>
            </tr>
          </thead>
          <tbody>
            {r.coverage.map((c) => (
              <tr key={c.connector_id}>
                <Td>
                  <Mono>{c.connector_id}</Mono>
                </Td>
                <Td>
                  <StatusBadge status={c.status} />
                </Td>
                <Td>{c.attempted_queries}</Td>
                <Td>{c.fetched}</Td>
                <Td>{c.matched}</Td>
                <Td>{c.analysed}</Td>
                <Td>{c.metadata_only}</Td>
                <Td>{formatTime(c.last_success_at)}</Td>
                <Td className="max-w-xs text-ink-muted">{c.note}</Td>
              </tr>
            ))}
          </tbody>
        </Table>
        <p className="mt-2 text-xs text-ink-muted">Access pending, partial and unavailable are not zero discussion: they say a source was not fully read.</p>
      </Panel>
    </div>
  );
}
