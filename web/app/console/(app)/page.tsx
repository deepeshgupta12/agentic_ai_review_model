import type { Metadata } from "next";
import Link from "next/link";

import { AutoRefresh } from "@/components/AutoRefresh";
import { CoverageList } from "@/components/CoverageList";
import { Icon } from "@/components/icons";
import { FlowSteps } from "@/components/NextStep";
import { StatusBadge } from "@/components/StatusBadge";
import { BUTTON, EmptyState, ErrorState, PageTitle, Stat } from "@/components/ui";
import { apiGetAll, backendInfo, currentUser, type Schemas } from "@/lib/api-server";
import { nextStep } from "@/lib/flow";
import { ago, runBadge, runIsWorking } from "@/lib/format";
import { can } from "@/lib/roles";

import { AddProjectForm } from "./AddProjectForm";
import { ImportForm } from "./ImportForm";

export const metadata: Metadata = { title: "Portfolio" };

const NEXT_TONE = {
  todo: "border-accent/25 bg-accent-soft/70",
  wait: "border-info/20 bg-info-soft/70",
  done: "border-ok/25 bg-ok-soft/70",
  stop: "border-warn/25 bg-warn-soft/70",
};

export default async function PortfolioPage() {
  const [page, me, info] = await Promise.all([
    apiGetAll<Schemas["ProjectSummary"]>("/v1/projects"),
    currentUser(),
    backendInfo(),
  ]);
  if (!page.data) return <ErrorState status={page.status} error={page.error} requestId={page.requestId} />;
  const projects = page.data.items;
  const mayAdd = can(me?.roles, "createProject");
  const running = projects.filter((row) => runIsWorking(row.latest_run)).length;
  const waiting = projects.reduce((sum, row) => sum + row.pending_review.review_excerpts + row.pending_review.findings, 0);
  const live = projects.filter((row) => row.publication.serving_state === "active").length;
  const spend = projects.reduce((sum, row) => sum + row.spend_usd_30d, 0);

  return (
    <section className="space-y-8">
      <PageTitle title="Portfolio" eyebrow="Projects" actions={<AutoRefresh active={running > 0} />}>
        Every project with what it needs next: run, approve the reviews found, build the page from approved reviews, then approve and
        publish it.
      </PageTitle>

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <Stat label="Projects" icon="layers" value={projects.length} hint={`${live} with a live page`} tone="accent" />
        <Stat label="Runs working" icon="clock" value={running} hint={running ? "numbers update live" : "nothing running now"} tone={running ? "info" : "neutral"} />
        <Stat label="Waiting for a decision" icon="inbox" value={waiting} hint="reviews and findings to approve or reject" tone={waiting ? "warn" : "neutral"} />
        <Stat label="Spend, 30 days" icon="coins" value={`$${spend.toFixed(2)}`} hint="model calls across projects" tone="neutral" />
      </div>

      {projects.length === 0 ? (
        <EmptyState>No projects yet. {mayAdd ? "Add one below or import the input file." : "A researcher can add projects."}</EmptyState>
      ) : (
        <ul className="grid gap-5 xl:grid-cols-2" aria-label="Projects">
          {projects.map((row) => {
            const pending = row.pending_review;
            const next = nextStep(row, row.project.id, row.project.slug, info.page_reviews_max);
            const badge = row.latest_run ? runBadge(row.latest_run) : null;
            const external = next.href.startsWith("/projects/");
            const others = [
              [pending.links, "matches"],
              [pending.alias_proposals, "names"],
              [pending.corrections, "corrections"],
            ] as const;
            return (
              <li key={row.project.id} data-testid="portfolio-row" className="flex flex-col rounded-lg border border-line bg-surface shadow-card transition hover:shadow-lift">
                <div className="flex items-start gap-3 p-5 pb-4">
                  <span
                    aria-hidden="true"
                    className="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-linear-to-br from-teal-500 to-emerald-700 font-semibold text-white"
                  >
                    {row.project.project_name.slice(0, 1).toUpperCase()}
                  </span>
                  <div className="min-w-0 flex-1">
                    <h2 className="truncate text-base font-semibold">
                      <Link href={`/console/projects/${row.project.id}/runs`} className="hover:text-accent hover:underline">
                        {row.project.project_name}
                      </Link>
                    </h2>
                    <p className="flex items-center gap-1 text-[13px] text-ink-muted">
                      <Icon name="pin" className="h-3.5 w-3.5" />
                      {row.project.locality}, {row.project.city}
                    </p>
                  </div>
                  {row.latest_run && badge ? (
                    <Link href={`/console/runs/${row.latest_run.id}`} className="flex flex-col items-end gap-1 text-right">
                      <StatusBadge status={badge.status} text={badge.text} />
                      <span className="text-[11px] text-ink-muted">{ago(row.latest_run.updated_at)}</span>
                    </Link>
                  ) : (
                    <StatusBadge status="none" text="never run" />
                  )}
                </div>

                <div className="px-5">
                  <FlowSteps next={next} compact />
                </div>

                <div className={`mx-5 mt-4 flex flex-wrap items-center gap-3 rounded-lg border px-4 py-3 ${NEXT_TONE[next.tone]}`}>
                  <div className="min-w-0 flex-1">
                    <p className="font-semibold">{next.title}</p>
                    {next.detail ? <p className="text-[13px] text-ink-muted">{next.detail}</p> : null}
                  </div>
                  <Link href={next.href} target={external ? "_blank" : undefined} className={next.tone === "todo" ? BUTTON.primary : BUTTON.secondary}>
                    {next.action}
                    <Icon name={external ? "external" : "arrow"} />
                  </Link>
                </div>

                <div className="grid gap-4 p-5 sm:grid-cols-[minmax(0,1fr)_minmax(0,14rem)]">
                  <div className="min-w-0">
                    <p className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-ink-muted">Sources of the latest run</p>
                    <CoverageList rows={row.coverage} stage={row.latest_run?.stage} />
                  </div>
                  <div className="space-y-4">
                    <div>
                      <p className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-ink-muted">Waiting for a decision</p>
                      <div className="flex flex-wrap gap-1.5">
                        <Link
                          href={`/console/projects/${row.project.id}/reviews?review_status=pending`}
                          className={`inline-flex items-center gap-1 rounded-md px-2 py-1 text-[13px] ring-1 ring-inset ${
                            pending.review_excerpts ? "bg-warn-soft text-warn ring-warn/25" : "bg-surface-sunken text-ink-muted ring-line"
                          }`}
                        >
                          <span className="font-semibold">{pending.review_excerpts}</span> reviews
                        </Link>
                        {info.analysis_mode === "full" || pending.findings ? (
                          <Link
                            href={`/console/projects/${row.project.id}/findings?review_status=pending`}
                            className={`inline-flex items-center gap-1 rounded-md px-2 py-1 text-[13px] ring-1 ring-inset ${
                              pending.findings ? "bg-warn-soft text-warn ring-warn/25" : "bg-surface-sunken text-ink-muted ring-line"
                            }`}
                          >
                            <span className="font-semibold">{pending.findings}</span> findings
                          </Link>
                        ) : null}
                      </div>
                      <p className="mt-1.5 text-xs text-ink-muted">{others.map(([n, what]) => `${n} ${what}`).join(" · ")}</p>
                    </div>
                    <div>
                      <p className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-ink-muted">Public page</p>
                      <div className="flex flex-wrap items-center gap-1.5">
                        <StatusBadge status={row.publication.serving_state} />
                        {row.publication.delivery_status ? <StatusBadge status={row.publication.delivery_status} /> : null}
                      </div>
                      <p className="mt-1.5 text-xs text-ink-muted">
                        approved r{row.publication.approved_revision ?? "–"} · live r{row.publication.active_revision ?? "–"}
                      </p>
                    </div>
                  </div>
                </div>

                <div className="mt-auto flex items-center justify-between gap-2 border-t border-line px-5 py-2.5 text-xs text-ink-muted">
                  <span>Spend, 30 days: ${row.spend_usd_30d.toFixed(2)}</span>
                  <Link href={`/console/projects/${row.project.id}/runs`} className="inline-flex items-center gap-1 font-medium text-accent hover:underline">
                    Open project <Icon name="arrow" className="h-3.5 w-3.5" />
                  </Link>
                </div>
              </li>
            );
          })}
        </ul>
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
