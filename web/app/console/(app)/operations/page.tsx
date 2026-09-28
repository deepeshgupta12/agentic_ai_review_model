import type { Metadata } from "next";

import { StatusBadge } from "@/components/StatusBadge";
import { apiGet, type Schemas } from "@/lib/api-server";

export const metadata: Metadata = { title: "Operations" };

export default async function OperationsPage() {
  const [health, jobs] = await Promise.all([
    apiGet<Schemas["ConnectorHealthList"]>("/v1/connectors/health"),
    apiGet<Schemas["JobPage"]>("/v1/ops/jobs?limit=10"),
  ]);

  if (health.status === 403) {
    return (
      <section>
        <h1 className="mb-2 text-lg font-semibold">Operations</h1>
        <p className="text-ink-muted">Connector details need the researcher or admin role.</p>
      </section>
    );
  }

  return (
    <section className="space-y-6">
      <div>
        <h1 className="mb-1 text-lg font-semibold">Operations</h1>
        <p className="text-ink-muted">A connector turns live only after a real credential and a recorded demonstration (docs/06).</p>
      </div>
      <table className="w-full border-collapse rounded-lg border border-line bg-surface text-[13px]">
        <thead>
          <tr className="border-b border-line text-left text-ink-muted">
            <th className="px-3 py-2 font-medium">Connector</th>
            <th className="px-3 py-2 font-medium">Status</th>
            <th className="px-3 py-2 font-medium">Last verified</th>
          </tr>
        </thead>
        <tbody>
          {(health.data?.connectors ?? []).map((c) => (
            <tr key={c.connector_id} className="border-b border-line last:border-0" data-testid="connector-row">
              <td className="px-3 py-2 font-mono">{c.connector_id}</td>
              <td className="px-3 py-2">
                <StatusBadge status={c.status} />
              </td>
              <td className="px-3 py-2 text-ink-muted">{c.last_verified ?? "never"}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <div>
        <h2 className="mb-2 font-semibold">Recent jobs</h2>
        {(jobs.data?.items ?? []).length === 0 ? (
          <p className="text-ink-muted">No jobs yet.</p>
        ) : (
          <ul className="space-y-1">
            {jobs.data?.items.map((job) => (
              <li key={job.id} className="flex items-center gap-2">
                <span className="font-mono text-xs">{job.id}</span>
                <span>{job.kind}</span>
                <StatusBadge status={job.status} />
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}
