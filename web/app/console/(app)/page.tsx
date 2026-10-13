import type { Metadata } from "next";
import Link from "next/link";

import { StatusBadge } from "@/components/StatusBadge";
import { EmptyState, ErrorState, PageTitle, Table, Td, Th } from "@/components/ui";
import { apiGet, currentUser, type Schemas } from "@/lib/api-server";
import { formatTime } from "@/lib/format";
import { can } from "@/lib/roles";

import { AddProjectForm } from "./AddProjectForm";
import { ImportForm } from "./ImportForm";

export const metadata: Metadata = { title: "Portfolio" };

function coverage(rows: Schemas["RunCoverage"][]) {
  if (rows.length === 0) return <span className="text-ink-muted">no run yet</span>;
  return (
    <ul className="space-y-0.5">
      {rows.map((c) => (
        <li key={c.connector_id} className="flex items-center gap-1">
          <span className="font-mono text-xs">{c.connector_id}</span>
          <StatusBadge status={c.status} />
          <span className="text-ink-muted">{c.fetched} fetched</span>
        </li>
      ))}
    </ul>
  );
}

export default async function PortfolioPage() {
  const [page, me] = await Promise.all([apiGet<Schemas["ProjectPage"]>("/v1/projects", { limit: 100 }), currentUser()]);
  if (!page.data) return <ErrorState status={page.status} error={page.error} requestId={page.requestId} />;
  const projects = page.data.items;
  const mayAdd = can(me?.roles, "createProject");

  return (
    <section className="space-y-6">
      <PageTitle title="Portfolio">
        Every project in the catalogue with its latest run, coverage, open review work and what the public page shows.
      </PageTitle>
      {projects.length === 0 ? (
        <EmptyState>No projects yet. {mayAdd ? "Add one below or import the input file." : "A researcher can add projects."}</EmptyState>
      ) : (
        <Table label="Projects">
          <thead>
            <tr>
              <Th>Project</Th>
              <Th>Latest run</Th>
              <Th>Coverage</Th>
              <Th>Pending review</Th>
              <Th>Page</Th>
              <Th>Spend 30 days</Th>
            </tr>
          </thead>
          <tbody>
            {projects.map((row) => {
              const pending = row.pending_review;
              return (
                <tr key={row.project.id} data-testid="portfolio-row">
                  <Td>
                    <Link href={`/console/projects/${row.project.id}/setup`} className="font-medium text-accent underline">
                      {row.project.project_name}
                    </Link>
                    <div className="text-ink-muted">
                      {row.project.locality}, {row.project.city}
                    </div>
                  </Td>
                  <Td>
                    {row.latest_run ? (
                      <Link href={`/console/runs/${row.latest_run.id}`} className="space-y-1">
                        <StatusBadge status={row.latest_run.stage} />
                        <div className="text-ink-muted">{formatTime(row.latest_run.updated_at)}</div>
                      </Link>
                    ) : (
                      <span className="text-ink-muted">never run</span>
                    )}
                  </Td>
                  <Td>{coverage(row.coverage)}</Td>
                  <Td>
                    <ul className="space-y-0.5">
                      <li>
                        <Link href={`/console/projects/${row.project.id}/findings`}>{pending.findings} findings</Link>
                      </li>
                      <li>
                        <Link href={`/console/projects/${row.project.id}/reviews`}>{pending.review_excerpts} reviews</Link>
                      </li>
                      <li className="text-ink-muted">
                        {pending.links} links · {pending.alias_proposals} names · {pending.corrections} corrections
                      </li>
                    </ul>
                  </Td>
                  <Td>
                    <StatusBadge status={row.publication.serving_state} />
                    <div className="text-ink-muted">
                      approved r{row.publication.approved_revision ?? "–"} · active r{row.publication.active_revision ?? "–"}
                    </div>
                    {row.publication.delivery_status ? <StatusBadge status={row.publication.delivery_status} /> : null}
                  </Td>
                  <Td>${row.spend_usd_30d.toFixed(2)}</Td>
                </tr>
              );
            })}
          </tbody>
        </Table>
      )}
      {mayAdd ? (
        <div className="grid gap-6 lg:grid-cols-2">
          <AddProjectForm />
          {can(me?.roles, "importProjects") ? <ImportForm /> : null}
        </div>
      ) : null}
    </section>
  );
}
