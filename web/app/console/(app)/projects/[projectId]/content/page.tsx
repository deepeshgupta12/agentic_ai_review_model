import type { Metadata } from "next";
import Link from "next/link";

import { StatusBadge } from "@/components/StatusBadge";
import { EmptyState, ErrorState, Panel, Table, Td, Th } from "@/components/ui";
import { apiGet, apiGetAll, backendInfo, currentUser, type Schemas } from "@/lib/api-server";
import { formatTime, shortHash, stageLabel } from "@/lib/format";
import { can } from "@/lib/roles";

import { GenerateForm } from "./GenerateForm";

export const metadata: Metadata = { title: "Page" };

export default async function ContentPage({ params }: { params: Promise<{ projectId: string }> }) {
  const { projectId } = await params;
  const me = await currentUser();
  const [revisions, findings, reviews, runs, info] = await Promise.all([
    apiGetAll<Schemas["ContentRevisionView"]>(`/v1/projects/${projectId}/content-revisions`),
    apiGetAll<Schemas["FindingView"]>(`/v1/projects/${projectId}/findings`, { review_status: "approved" }),
    apiGetAll<Schemas["ReviewExcerptView"]>(`/v1/projects/${projectId}/review-excerpts`, { review_status: "approved" }),
    apiGet<Schemas["RunPage"]>(`/v1/projects/${projectId}/runs`, { limit: 20 }),
    backendInfo(),
  ]);
  if (!revisions.data) return <ErrorState status={revisions.status} error={revisions.error} requestId={revisions.requestId} />;
  const latestRun = runs.data?.items[0];
  // the backend continues the newest run that waits for decisions, whatever came after it (audit, 14 Oct 2026)
  const waitingRun = runs.data?.items.find((run) => run.stage === "findings_review");
  const latestRevision = revisions.data.items[0]?.revision;
  const mayGenerate = can(me?.roles, "createContentRevision");
  // Generation continues a run that waits for decisions (the backend's rule); afterwards the page changes by editing
  // its latest revision, which can add any approved review (D69) and needs a new final approval.
  const waiting = waitingRun !== undefined;
  const loadFailed = !reviews.data || !findings.data;

  return (
    <div className="space-y-6">
      {mayGenerate && waiting && loadFailed ? (
        <ErrorState
          status={reviews.status === 200 ? findings.status : reviews.status}
          error={reviews.error ?? findings.error}
          requestId={reviews.requestId ?? findings.requestId}
        />
      ) : null}
      {mayGenerate && waiting && !loadFailed ? (
        <GenerateForm
          projectId={projectId}
          findings={(findings.data?.items ?? []).map((v) => v.finding)}
          reviews={(reviews.data?.items ?? []).map((v) => v.review)}
          limits={info}
        />
      ) : null}
      {mayGenerate && !waiting && latestRevision ? (
        <Panel title="Change the page">
          <p className="text-ink-muted">
            To add, remove or reorder reviews, open the latest revision and edit it. Any approved review of this project can be added; the
            edit becomes revision {latestRevision.revision + 1} and needs its own final approval.
          </p>
          <Link href={`/console/projects/${projectId}/content/${latestRevision.id}`} className="mt-2 inline-block rounded bg-accent px-3 py-1.5 font-medium text-white">
            Open revision {latestRevision.revision}
          </Link>
        </Panel>
      ) : null}
      {mayGenerate && !waiting && !latestRevision ? (
        <EmptyState>
          {latestRun
            ? `The latest run is ${stageLabel(latestRun.stage)}. The page is built once a run reaches its review and reviews are approved.`
            : "No run yet. Start one on the Runs tab; the page is built from the reviews it finds once a moderator approves them."}
        </EmptyState>
      ) : null}
      <Panel title="Page revisions">
        {revisions.data.items.length === 0 ? (
          <EmptyState>No page content yet.</EmptyState>
        ) : (
          <Table label="Content revisions">
            <thead>
              <tr>
                <Th>Revision</Th>
                <Th>State</Th>
                <Th>Reviews</Th>
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
                    <Td>{r.payload.reviews.length}</Td>
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
