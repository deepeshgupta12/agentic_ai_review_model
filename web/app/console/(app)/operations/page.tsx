import type { Metadata } from "next";

import { StatusBadge } from "@/components/StatusBadge";
import { EmptyState, ErrorState, Mono, MoreLink, PageTitle, Panel, Table, Td, Th } from "@/components/ui";
import { apiGet, type Schemas } from "@/lib/api-server";
import { formatTime } from "@/lib/format";

export const metadata: Metadata = { title: "Operations" };

export default async function OperationsPage({ searchParams }: { searchParams: Promise<{ job_status?: string; cursor?: string }> }) {
  const search = await searchParams;
  const [health, jobs, summary, evaluations] = await Promise.all([
    apiGet<Schemas["ConnectorHealthList"]>("/v1/connectors/health"),
    apiGet<Schemas["JobPage"]>("/v1/ops/jobs", { ...search, limit: 25 }),
    apiGet<Schemas["OpsSummary"]>("/v1/ops/summary"),
    apiGet<Schemas["EvaluationPage"]>("/v1/evaluations", { limit: 10 }),
  ]);
  const totalSpend = (summary.data?.model_usage ?? []).reduce((n, row) => n + row.cost_usd, 0);

  return (
    <section className="space-y-6">
      <PageTitle title="Operations">
        A connector turns live only after a real credential and a recorded demonstration (docs/06). Credentials and raw source text are
        never shown here.
      </PageTitle>
      <Panel title="Model usage and cost by agent">
        {!summary.data ? (
          <ErrorState status={summary.status} error={summary.error} />
        ) : summary.data.model_usage.length === 0 ? (
          <EmptyState>No model call yet.</EmptyState>
        ) : (
          <Table label="Model usage">
            <thead>
              <tr>
                <Th>Agent</Th>
                <Th>Calls</Th>
                <Th>Input tokens</Th>
                <Th>Output tokens</Th>
                <Th>Cost</Th>
              </tr>
            </thead>
            <tbody>
              {summary.data.model_usage.map((row) => (
                <tr key={row.agent}>
                  <Td>
                    <Mono>{row.agent}</Mono>
                  </Td>
                  <Td>{row.calls}</Td>
                  <Td>{row.input_tokens.toLocaleString("en-IN")}</Td>
                  <Td>{row.output_tokens.toLocaleString("en-IN")}</Td>
                  <Td>${row.cost_usd.toFixed(3)}</Td>
                </tr>
              ))}
              <tr>
                <Td className="font-medium">Total</Td>
                <Td />
                <Td />
                <Td />
                <Td className="font-medium">${totalSpend.toFixed(3)}</Td>
              </tr>
            </tbody>
          </Table>
        )}
        {summary.data ? (
          <p className="mt-2 text-ink-muted">
            Delivery pending: {summary.data.delivery_pending} · deletion backlog: {summary.data.deletion_backlog}
          </p>
        ) : null}
      </Panel>

      <Panel title="Connectors">
        {!health.data ? (
          <ErrorState status={health.status} error={health.error} />
        ) : (
          <Table label="Connectors">
            <thead>
              <tr>
                <Th>Connector</Th>
                <Th>Status</Th>
                <Th>Last verified</Th>
                <Th>Last success</Th>
                <Th>Quota</Th>
                <Th>Last error</Th>
              </tr>
            </thead>
            <tbody>
              {health.data.connectors.map((c) => (
                <tr key={c.connector_id} data-testid="connector-row">
                  <Td>
                    <Mono>{c.connector_id}</Mono>
                  </Td>
                  <Td>
                    <StatusBadge status={c.status} />
                  </Td>
                  <Td>{c.last_verified ?? "never"}</Td>
                  <Td>{formatTime(c.last_success_at)}</Td>
                  <Td>{c.quota.limit !== null ? `${c.quota.used ?? 0} of ${c.quota.limit}` : "n/a"}</Td>
                  <Td className="max-w-xs text-ink-muted">{c.last_error ? `${c.last_error.code}: ${c.last_error.message}` : "none"}</Td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Panel>

      <Panel title="Jobs">
        <form className="mb-3 flex items-end gap-3" aria-label="Filter jobs">
          <select name="job_status" defaultValue={search.job_status ?? ""} aria-label="Job status" className="rounded border border-line px-2 py-1">
            <option value="">all</option>
            {["failed", "retry_wait", "running", "queued", "waiting_review", "completed", "cancelled"].map((s) => (
              <option key={s} value={s}>
                {s.replaceAll("_", " ")}
              </option>
            ))}
          </select>
          <button type="submit" className="rounded border border-line bg-surface px-3 py-1">
            Filter
          </button>
        </form>
        {!jobs.data ? (
          <ErrorState status={jobs.status} error={jobs.error} />
        ) : jobs.data.items.length === 0 ? (
          <EmptyState>No jobs.</EmptyState>
        ) : (
          <Table label="Jobs">
            <thead>
              <tr>
                <Th>Job</Th>
                <Th>Kind</Th>
                <Th>Status</Th>
                <Th>Attempts</Th>
                <Th>Updated</Th>
                <Th>Error</Th>
              </tr>
            </thead>
            <tbody>
              {jobs.data.items.map((job) => (
                <tr key={job.id}>
                  <Td>
                    <Mono>{job.id}</Mono>
                  </Td>
                  <Td>{job.kind}</Td>
                  <Td>
                    <StatusBadge status={job.status} />
                  </Td>
                  <Td>
                    {job.attempts} of {job.max_attempts}
                  </Td>
                  <Td>{formatTime(job.updated_at)}</Td>
                  <Td className="max-w-xs text-ink-muted">{job.error ? `${job.error.code}: ${job.error.message}` : ""}</Td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
        <MoreLink cursor={jobs.data?.next_cursor ?? null} params={search as Record<string, string>} path="/console/operations" />
      </Panel>

      <Panel title="Evaluations">
        {!evaluations.data ? (
          <ErrorState status={evaluations.status} error={evaluations.error} />
        ) : evaluations.data.items.length === 0 ? (
          <EmptyState>No evaluation recorded.</EmptyState>
        ) : (
          <ul className="space-y-3">
            {evaluations.data.items.map((run) => (
              <li key={run.id}>
                <p>
                  <span className="font-medium">{run.dataset.name}</span> {run.dataset.version} {run.dataset.synthetic ? "(synthetic)" : ""} ·{" "}
                  <StatusBadge status={run.status} /> · {formatTime(run.created_at)}
                </p>
                <ul className="ml-4 text-ink-muted">
                  {run.metrics.map((m) => (
                    <li key={m.name}>
                      {m.name}: {m.value ?? "n/a"} (n = {m.sample_size}){m.note ? `, ${m.note}` : ""}
                    </li>
                  ))}
                </ul>
              </li>
            ))}
          </ul>
        )}
      </Panel>
    </section>
  );
}
