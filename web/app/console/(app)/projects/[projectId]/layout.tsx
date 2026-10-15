import Link from "next/link";
import { notFound } from "next/navigation";

import { NextStepBanner } from "@/components/NextStep";
import { ProjectTabs } from "@/components/ProjectTabs";
import { StatusBadge } from "@/components/StatusBadge";
import { ErrorState } from "@/components/ui";
import { apiGet, apiGetAll, backendInfo, type Schemas } from "@/lib/api-server";
import { nextStep } from "@/lib/flow";
import { stageLabel } from "@/lib/format";

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
  return (
    <div>
      <div className="mb-3 flex flex-wrap items-baseline gap-3">
        <h1 className="text-xl font-semibold">{project.project_name}</h1>
        <span className="text-ink-muted">
          {project.locality}, {project.city}
        </span>
        {summary?.latest_run ? (
          <Link href={`/console/runs/${summary.latest_run.id}`} className="flex items-center gap-1 text-ink-muted">
            latest run <StatusBadge status={summary.latest_run.stage} text={stageLabel(summary.latest_run.stage)} />
          </Link>
        ) : (
          <span className="text-ink-muted">no run yet</span>
        )}
        <Link href={`/projects/${project.slug}`} className="ml-auto text-accent underline" target="_blank">
          Public page
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
