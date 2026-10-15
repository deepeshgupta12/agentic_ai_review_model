import type { Metadata } from "next";
import Link from "next/link";

import { AutoRefresh } from "@/components/AutoRefresh";
import { CoverageList } from "@/components/CoverageList";
import { StatusBadge } from "@/components/StatusBadge";
import { EmptyState, ErrorState, PageTitle, Table, Td, Th } from "@/components/ui";
import { apiGetAll, backendInfo, currentUser, type Schemas } from "@/lib/api-server";
import { nextStep } from "@/lib/flow";
import { formatTime, runIsWorking, stageLabel } from "@/lib/format";
import { can } from "@/lib/roles";

import { AddProjectForm } from "./AddProjectForm";
import { ImportForm } from "./ImportForm";

export const metadata: Metadata = { title: "Portfolio" };

export default async function PortfolioPage() {
  const [page, me, info] = await Promise.all([
    apiGetAll<Schemas["ProjectSummary"]>("/v1/projects"),
    currentUser(),
    backendInfo(),
  ]);
  if (!page.data) return <ErrorState status={page.status} error={page.error} requestId={page.requestId} />;
  const projects = page.data.items;
  const mayAdd = can(me?.roles, "createProject");
  const running = projects.some((row) => runIsWorking(row.latest_run));

  return (
    <section className="space-y-6">
      <PageTitle title="Portfolio">
        Every project with what it needs next: run, approve the reviews found, build the page from approved reviews, then approve and
        publish it. <AutoRefresh active={running} />
      </PageTitle>
      {projects.length === 0 ? (
        <EmptyState>No projects yet. {mayAdd ? "Add one below or import the input file." : "A researcher can add projects."}</EmptyState>
      ) : (
        <Table label="Projects">
          <thead>
            <tr>
              <Th>Project</Th>
              <Th>Next step</Th>
              <Th>Latest run</Th>
              <Th>Waiting for a decision</Th>
              <Th>Page</Th>
              <Th>Coverage</Th>
              <Th>Spend 30 days</Th>
            </tr>
          </thead>
          <tbody>
            {projects.map((row) => {
              const pending = row.pending_review;
              const next = nextStep(row, row.project.id, row.project.slug, info.page_reviews_max);
              return (
                <tr key={row.project.id} data-testid="portfolio-row">
                  <Td>
                    <Link href={`/console/projects/${row.project.id}/runs`} className="font-medium text-accent underline">
                      {row.project.project_name}
                    </Link>
                    <div className="text-ink-muted">
                      {row.project.locality}, {row.project.city}
                    </div>
                  </Td>
                  <Td className="max-w-[16rem]">
                    <Link href={next.href} target={next.href.startsWith("/projects/") ? "_blank" : undefined} className="text-accent underline">
                      {next.title}
                    </Link>
                    <div className="text-xs text-ink-muted">step {next.step} of 4</div>
                  </Td>
                  <Td>
                    {row.latest_run ? (
                      <Link href={`/console/runs/${row.latest_run.id}`} className="space-y-1">
                        <StatusBadge status={row.latest_run.stage} text={stageLabel(row.latest_run.stage)} />
                        <div className="text-ink-muted">{formatTime(row.latest_run.updated_at)}</div>
                      </Link>
                    ) : (
                      <span className="text-ink-muted">never run</span>
                    )}
                  </Td>
                  <Td>
                    <ul className="space-y-0.5">
                      <li>
                        <Link href={`/console/projects/${row.project.id}/reviews?review_status=pending`}>{pending.review_excerpts} reviews</Link>
                      </li>
                      {info.analysis_mode === "full" || pending.findings ? (
                        <li>
                          <Link href={`/console/projects/${row.project.id}/findings?review_status=pending`}>{pending.findings} findings</Link>
                        </li>
                      ) : null}
                      <li className="text-ink-muted">
                        {pending.links} matches · {pending.alias_proposals} names · {pending.corrections} corrections
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
                  <Td>
                    <CoverageList rows={row.coverage} stage={row.latest_run?.stage} />
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
