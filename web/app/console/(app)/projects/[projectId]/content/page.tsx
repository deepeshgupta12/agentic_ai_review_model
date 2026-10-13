import type { Metadata } from "next";
import Link from "next/link";

import { StatusBadge } from "@/components/StatusBadge";
import { EmptyState, ErrorState, Panel, Table, Td, Th } from "@/components/ui";
import { apiGet, currentUser, type Schemas } from "@/lib/api-server";
import { formatTime, shortHash } from "@/lib/format";
import { can } from "@/lib/roles";

import { GenerateForm } from "./GenerateForm";

export const metadata: Metadata = { title: "Content" };

export default async function ContentPage({ params }: { params: Promise<{ projectId: string }> }) {
  const { projectId } = await params;
  const me = await currentUser();
  const [revisions, findings, reviews, runs] = await Promise.all([
    apiGet<Schemas["ContentRevisionPage"]>(`/v1/projects/${projectId}/content-revisions`, { limit: 50 }),
    apiGet<Schemas["FindingPage"]>(`/v1/projects/${projectId}/findings`, { review_status: "approved", limit: 100 }),
    apiGet<Schemas["ReviewExcerptPage"]>(`/v1/projects/${projectId}/review-excerpts`, { review_status: "approved", limit: 100 }),
    apiGet<Schemas["RunPage"]>(`/v1/projects/${projectId}/runs`, { limit: 1 }),
  ]);
  if (!revisions.data) return <ErrorState status={revisions.status} error={revisions.error} requestId={revisions.requestId} />;
  const latestRun = runs.data?.items[0];

  return (
    <div className="space-y-6">
      {can(me?.roles, "createContentRevision") ? (
        <GenerateForm
          projectId={projectId}
          waiting={latestRun?.stage === "findings_review"}
          stage={latestRun?.stage ?? null}
          findings={(findings.data?.items ?? []).map((v) => v.finding)}
          reviews={(reviews.data?.items ?? []).map((v) => v.review)}
        />
      ) : null}
      <Panel title="Content revisions">
        {revisions.data.items.length === 0 ? (
          <EmptyState>No page content yet. Approve findings or reviews, then generate a draft above.</EmptyState>
        ) : (
          <Table label="Content revisions">
            <thead>
              <tr>
                <Th>Revision</Th>
                <Th>State</Th>
                <Th>QA</Th>
                <Th>Made by</Th>
                <Th>Hash</Th>
                <Th>Page</Th>
              </tr>
            </thead>
            <tbody>
              {revisions.data.items.map((view) => {
                const r = view.revision;
                return (
                  <tr key={r.id}>
                    <Td>
                      <Link href={`/console/projects/${projectId}/content/${r.id}`} className="text-accent underline">
                        revision {r.revision}
                      </Link>
                      <div className="text-ink-muted">{formatTime(r.created_at)}</div>
                    </Td>
                    <Td>
                      <StatusBadge status={r.lifecycle} />
                    </Td>
                    <Td>
                      <StatusBadge status={r.qa.status} />
                      <div className="text-ink-muted">
                        {r.qa.blocking_issues} blocking · {r.qa.nonblocking_issues} notes
                      </div>
                    </Td>
                    <Td>{r.created_by.kind === "agent" ? "generated" : "moderator edit"}</Td>
                    <Td className="font-mono text-xs">{shortHash(r.payload_sha256)}</Td>
                    <Td>
                      {view.is_active ? <StatusBadge status="active" /> : null}
                      {view.is_approved ? <StatusBadge status="approved" /> : null}
                      <Link href={view.preview_path} className="ml-2 text-accent underline">
                        preview
                      </Link>
                    </Td>
                  </tr>
                );
              })}
            </tbody>
          </Table>
        )}
      </Panel>
    </div>
  );
}
