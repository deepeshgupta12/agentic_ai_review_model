import Link from "next/link";
import { notFound } from "next/navigation";

import { ProjectTabs } from "@/components/ProjectTabs";
import { StatusBadge } from "@/components/StatusBadge";
import { ErrorState } from "@/components/ui";
import { apiGet, type Schemas } from "@/lib/api-server";

export default async function ProjectLayout({ children, params }: { children: React.ReactNode; params: Promise<{ projectId: string }> }) {
  const { projectId } = await params;
  const detail = await apiGet<Schemas["ProjectDetail"]>(`/v1/projects/${projectId}`);
  if (detail.status === 404) notFound();
  if (!detail.data) return <ErrorState status={detail.status} error={detail.error} requestId={detail.requestId} />;
  const page = await apiGet<Schemas["ProjectPage"]>("/v1/projects", { limit: 100 });
  const summary = page.data?.items.find((p) => p.project.id === projectId);
  const project = detail.data.project;
  return (
    <div>
      <div className="mb-3 flex flex-wrap items-baseline gap-3">
        <h1 className="text-xl font-semibold">{project.project_name}</h1>
        <span className="text-ink-muted">
          {project.locality}, {project.city}
        </span>
        {summary?.latest_run ? (
          <Link href={`/console/runs/${summary.latest_run.id}`} className="flex items-center gap-1 text-ink-muted">
            latest run <StatusBadge status={summary.latest_run.stage} />
          </Link>
        ) : (
          <span className="text-ink-muted">no run yet</span>
        )}
        <Link href={`/projects/${project.slug}`} className="ml-auto text-accent underline" target="_blank">
          Public page
        </Link>
      </div>
      <ProjectTabs
        projectId={projectId}
        counts={{
          findings: summary?.pending_review.findings,
          reviews: summary?.pending_review.review_excerpts,
          evidence: summary?.pending_review.links,
          setup: summary?.pending_review.alias_proposals,
        }}
      />
      {children}
    </div>
  );
}
