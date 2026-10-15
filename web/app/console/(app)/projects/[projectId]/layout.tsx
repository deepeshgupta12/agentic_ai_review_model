import Link from "next/link";
import { notFound } from "next/navigation";

import { Icon } from "@/components/icons";
import { NextStepBanner } from "@/components/NextStep";
import { ProjectTabs } from "@/components/ProjectTabs";
import { StatusBadge } from "@/components/StatusBadge";
import { BUTTON, ErrorState } from "@/components/ui";
import { apiGet, apiGetAll, backendInfo, type Schemas } from "@/lib/api-server";
import { nextStep } from "@/lib/flow";
import { ago, runBadge } from "@/lib/format";

export default async function ProjectLayout({ children, params }: { children: React.ReactNode; params: Promise<{ projectId: string }> }) {
  const { projectId } = await params;
  const [detail, page, info] = await Promise.all([
    apiGet<Schemas["ProjectDetail"]>(`/v1/projects/${projectId}`),
    apiGetAll<Schemas["ProjectSummary"]>("/v1/projects"),
    backendInfo(),
  ]);
  if (detail.status === 404) notFound();
  if (!detail.data) return <ErrorState status={detail.status} error={detail.error} requestId={detail.requestId} />;
  const summary = page.data?.items.find((p) => p.project.id === projectId);
  const project = detail.data.project;
  // Findings exist only in the full analysis (D68); the tab stays while any finding waits for a decision.
  const showFindings = info.analysis_mode === "full" || (summary?.pending_review.findings ?? 0) > 0;
  const run = summary?.latest_run;
  const badge = run ? runBadge(run) : null;
  return (
    <div>
      <nav aria-label="Breadcrumb" className="mb-3 flex items-center gap-1.5 text-xs text-ink-muted">
        <Link href="/console" className="hover:text-ink hover:underline">
          Portfolio
        </Link>
        <span aria-hidden="true">/</span>
        <span className="text-ink">{project.project_name}</span>
      </nav>
      <div className="mb-5 flex flex-wrap items-center gap-4">
        <span
          aria-hidden="true"
          className="inline-flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-linear-to-br from-teal-500 to-emerald-700 text-lg font-semibold text-white shadow-card"
        >
          {project.project_name.slice(0, 1).toUpperCase()}
        </span>
        <div className="min-w-0 flex-1">
          <h1 className="text-2xl font-semibold tracking-tight">{project.project_name}</h1>
          <p className="mt-0.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-ink-muted">
            <span className="inline-flex items-center gap-1">
              <Icon name="pin" className="h-3.5 w-3.5" />
              {project.locality}, {project.city}
            </span>
            {run && badge ? (
              <Link href={`/console/runs/${run.id}`} className="inline-flex items-center gap-1.5 hover:text-ink">
                latest run <StatusBadge status={badge.status} text={badge.text} />
                <span className="text-xs">updated {ago(run.updated_at)}</span>
              </Link>
            ) : (
              <span>no run yet</span>
            )}
          </p>
        </div>
        <Link href={`/projects/${project.slug}`} className={BUTTON.secondary} target="_blank">
          Public page <Icon name="external" />
        </Link>
      </div>
      {summary ? <NextStepBanner next={nextStep(summary, projectId, project.slug, info.page_reviews_max)} /> : null}
      <ProjectTabs
        projectId={projectId}
        showFindings={showFindings}
        counts={{
          reviews: summary?.pending_review.review_excerpts,
          findings: summary?.pending_review.findings,
          evidence: summary?.pending_review.links,
          setup: summary?.pending_review.alias_proposals,
        }}
      />
      {children}
    </div>
  );
}
