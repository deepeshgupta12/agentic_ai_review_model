import type { Metadata } from "next";
import Link from "next/link";

import { ActionDialog } from "@/components/ActionDialog";
import { StatusBadge } from "@/components/StatusBadge";
import { EmptyState, ErrorState, Field, Mono, Notice, Panel, Table, Td, Th } from "@/components/ui";
import { apiGet, currentUser, type Schemas } from "@/lib/api-server";
import { formatTime, shortHash } from "@/lib/format";
import { can } from "@/lib/roles";

export const metadata: Metadata = { title: "Publishing" };

export default async function PublishingPage({ params }: { params: Promise<{ projectId: string }> }) {
  const { projectId } = await params;
  const [view, me, project] = await Promise.all([
    apiGet<Schemas["PublicationStateView"]>(`/v1/projects/${projectId}/publication`),
    currentUser(),
    apiGet<Schemas["ProjectDetail"]>(`/v1/projects/${projectId}`),
  ]);
  if (!view.data) return <ErrorState status={view.status} error={view.error} requestId={view.requestId} />;
  const { state, recent_operations: operations } = view.data;
  const verified = operations.find((o) => o.status === "verified" && o.kind !== "unpublish");
  const publisher = can(me?.roles, "publish");
  const canPublish = publisher && state.approved && state.approved.revision_id !== state.active?.revision_id;
  const restorable = [
    ...new Map(
      operations
        .filter((o) => o.target && o.target.revision_id !== state.active?.revision_id && ["publish", "rollback"].includes(o.kind))
        .map((o) => [o.target!.revision_id, o.target!]),
    ).values(),
  ];
  const slug = project.data?.project.slug;

  return (
    <div className="space-y-6">
      {state.pending_invalidation ? <Notice tone="danger">An evidence invalidation is pending: nothing can be approved or published until it finishes.</Notice> : null}
      {state.serving_state === "temporarily_disabled" ? (
        <Notice tone="warn">Serving is disabled because evidence behind the active revision was withdrawn. Approve and publish a new revision, or roll back to an eligible one.</Notice>
      ) : null}
      <div className="grid gap-6 lg:grid-cols-3">
        <Panel title="Approved">
          {state.approved ? (
            <dl>
              <Field label="Revision">
                <Link href={`/console/projects/${projectId}/content/${state.approved.revision_id}`} className="text-accent underline">
                  revision {state.approved.revision}
                </Link>
              </Field>
              <Field label="Hash">
                <Mono>{shortHash(state.approved.payload_sha256)}</Mono>
              </Field>
            </dl>
          ) : (
            <EmptyState>No approved revision.</EmptyState>
          )}
        </Panel>
        <Panel title="Active (what the page serves)">
          <p className="mb-2">
            <StatusBadge status={state.serving_state} />
          </p>
          {state.active ? (
            <dl>
              <Field label="Revision">revision {state.active.revision}</Field>
              <Field label="Hash">
                <Mono>{shortHash(state.active.payload_sha256)}</Mono>
              </Field>
              <Field label="Activated">{formatTime(state.active.activated_at)}</Field>
            </dl>
          ) : (
            <EmptyState>Nothing is active; the public page shows its empty state.</EmptyState>
          )}
        </Panel>
        <Panel title="Verified on the page">
          {verified ? (
            <dl>
              <Field label="Revision">
                <Mono>{verified.verification.rendered_revision_id}</Mono>
              </Field>
              <Field label="Verified">{formatTime(verified.verification.verified_at)}</Field>
            </dl>
          ) : (
            <EmptyState>No delivery verified yet.</EmptyState>
          )}
          {slug ? (
            <Link href={`/projects/${slug}`} target="_blank" className="mt-2 inline-block text-accent underline">
              Open the public page
            </Link>
          ) : null}
        </Panel>
      </div>

      {publisher ? (
        <Panel title="Actions">
          <div className="flex flex-wrap gap-3">
            {canPublish && state.approved ? (
              <ActionDialog
                label={`Publish revision ${state.approved.revision}`}
                title={`Publish revision ${state.approved.revision}`}
                path="/v1/publications"
                body={{
                  project_id: projectId,
                  locale: state.locale,
                  revision_id: state.approved.revision_id,
                  payload_sha256: state.approved.payload_sha256,
                  expected_state_version: state.version,
                }}
                idempotent
                tone="primary"
                testId="publish"
                description="The backend re-checks the approval, hash and evidence, activates the revision, then verifies that the rendered page shows it."
              />
            ) : (
              <p className="text-ink-muted">{state.approved ? "The approved revision is already active." : "Approve a revision first."}</p>
            )}
            {state.active && restorable.length ? (
              restorable.map((target) => (
                <ActionDialog
                  key={target.revision_id}
                  label={`Roll back to revision ${target.revision}`}
                  title={`Restore revision ${target.revision}`}
                  path={`/v1/publications/${state.active!.operation_id}/rollback`}
                  body={{ target_revision_id: target.revision_id, expected_state_version: state.version }}
                  reason="required"
                  idempotent
                  description="Only a revision that is still eligible, with its approval at the current evidence epoch, can be restored. Withdrawn content never returns."
                />
              ))
            ) : null}
            {state.active ? (
              <ActionDialog
                label="Unpublish"
                title="Stop showing the module"
                path={`/v1/projects/${projectId}/unpublish`}
                body={{ locale: state.locale, current_revision_id: state.active.revision_id, expected_state_version: state.version }}
                reason="required"
                idempotent
                tone="danger"
              />
            ) : null}
          </div>
          <p className="mt-2 text-xs text-ink-muted">State version {state.version} · evidence epoch {state.eligibility_epoch}</p>
        </Panel>
      ) : null}

      <Panel title="Recent operations">
        {operations.length === 0 ? (
          <EmptyState>No publication yet.</EmptyState>
        ) : (
          <Table label="Publication operations">
            <thead>
              <tr>
                <Th>Operation</Th>
                <Th>Kind</Th>
                <Th>Revision</Th>
                <Th>Status</Th>
                <Th>Activated</Th>
                <Th>Verified</Th>
                <Th>Note</Th>
              </tr>
            </thead>
            <tbody>
              {operations.map((o) => (
                <tr key={o.id}>
                  <Td>
                    <Mono>{o.id}</Mono>
                  </Td>
                  <Td>{o.kind}</Td>
                  <Td>{o.target ? `revision ${o.target.revision}` : "none"}</Td>
                  <Td>
                    <StatusBadge status={o.status} />
                  </Td>
                  <Td>{formatTime(o.activated_at)}</Td>
                  <Td>{formatTime(o.verification.verified_at)}</Td>
                  <Td className="max-w-xs text-ink-muted">{o.error?.message ?? o.reason}</Td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Panel>
    </div>
  );
}
