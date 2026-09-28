import type { Metadata } from "next";

import { apiGet, type Schemas } from "@/lib/api-server";

export const metadata: Metadata = { title: "Portfolio" };

export default async function PortfolioPage() {
  const summary = await apiGet<Schemas["OpsSummary"]>("/v1/ops/summary");
  const projects = summary.data?.projects ?? [];

  return (
    <section>
      <h1 className="mb-1 text-lg font-semibold">Portfolio</h1>
      <p className="mb-4 text-ink-muted">
        The full portfolio view (runs, coverage, review queues, publication) arrives with Steps 04 and 09.
      </p>
      <div className="rounded-lg border border-line bg-surface p-4">
        {projects.length === 0 ? (
          <p className="text-ink-muted">No projects in the catalogue yet. Run the project seed step.</p>
        ) : (
          <p>
            <span className="font-semibold">{projects.length}</span> projects in the catalogue;{" "}
            <span className="font-semibold">{projects.reduce((n, p) => n + p.failed_jobs, 0)}</span> failed jobs.
          </p>
        )}
      </div>
    </section>
  );
}
