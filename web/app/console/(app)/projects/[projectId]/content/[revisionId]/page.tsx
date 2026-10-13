import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { ActionDialog } from "@/components/ActionDialog";
import { StatusBadge } from "@/components/StatusBadge";
import { ErrorState, Field, Mono, Panel } from "@/components/ui";
import { apiGet, currentUser, type Schemas } from "@/lib/api-server";
import { formatTime, shortHash } from "@/lib/format";
import { can } from "@/lib/roles";

import { ApprovePanel } from "./ApprovePanel";
import { ContentEditor } from "./ContentEditor";

export const metadata: Metadata = { title: "Content revision" };

export default async function RevisionPage({ params }: { params: Promise<{ projectId: string; revisionId: string }> }) {
  const { projectId, revisionId } = await params;
  const [view, state, me] = await Promise.all([
    apiGet<Schemas["ContentRevisionView"]>(`/v1/content-revisions/${revisionId}`),
    apiGet<Schemas["PublicationStateView"]>(`/v1/projects/${projectId}/publication`),
    currentUser(),
  ]);
  if (view.status === 404) notFound();
  if (!view.data) return <ErrorState status={view.status} error={view.error} requestId={view.requestId} />;
  const { revision, qa_issues: issues } = view.data;
  const blocking = issues.filter((i) => i.severity === "blocking");

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center gap-3">
        <Link href={`/console/projects/${projectId}/content`} className="text-accent underline">
          all revisions
        </Link>
        <h2 className="text-lg font-semibold">Revision {revision.revision}</h2>
        <StatusBadge status={revision.lifecycle} />
        <StatusBadge status={revision.qa.status} />
        <Link href={view.data.preview_path} className="text-accent underline">
          Preview with the page template
        </Link>
      </div>
      <div className="grid gap-6 xl:grid-cols-[1fr_22rem]">
        <ContentEditor
          revision={revision}
          issues={issues}
          editable={can(me?.roles, "createContentRevision") && !["superseded", "withdrawn"].includes(revision.lifecycle)}
        />
        <div className="space-y-4">
          <Panel title="Exact revision">
            <dl>
              <Field label="Revision">
                <Mono>
                  {revision.id} r{revision.revision}
                </Mono>
              </Field>
              <Field label="Payload hash">
                <Mono>{shortHash(revision.payload_sha256)}</Mono>
              </Field>
              <Field label="Manifest hash">
                <Mono>{shortHash(revision.manifest_sha256)}</Mono>
              </Field>
              <Field label="Evidence epoch">
                <Mono>{revision.manifest.eligibility_epoch}</Mono>
              </Field>
              <Field label="Rests on">
                {revision.manifest.findings.length} findings, {revision.manifest.reviews.length} reviews, {revision.manifest.sources.length} sources
              </Field>
              <Field label="Created">{formatTime(revision.created_at)}</Field>
            </dl>
          </Panel>
          {revision.lifecycle === "final_review" && state.data ? (
            <ApprovePanel
              revision={revision}
              state={state.data.state}
              mayApprove={can(me?.roles, "approveContentRevision")}
              mayPublish={can(me?.roles, "publish")}
              projectId={projectId}
            />
          ) : null}
          {revision.lifecycle === "final_review" && can(me?.roles, "decideContentRevision") ? (
            <Panel title="Other decisions">
              <div className="flex flex-wrap gap-2">
                <ActionDialog
                  label="Request changes"
                  title={`Request changes to revision ${revision.revision}`}
                  path={`/v1/content-revisions/${revision.id}/decisions`}
                  body={{ revision: revision.revision, action: "changes_requested" }}
                  reason="required"
                />
                <ActionDialog
                  label="Reject"
                  title={`Reject revision ${revision.revision}`}
                  path={`/v1/content-revisions/${revision.id}/decisions`}
                  body={{ revision: revision.revision, action: "reject" }}
                  reason="required"
                  tone="danger"
                />
              </div>
            </Panel>
          ) : null}
          {blocking.length ? (
            <p className="rounded border border-danger bg-surface p-3 text-danger">
              {blocking.length} blocking QA issue(s): edit the blocks marked below; the revision cannot reach final review until they are fixed.
            </p>
          ) : null}
        </div>
      </div>
    </div>
  );
}
