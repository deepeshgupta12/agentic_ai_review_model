import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { ActionDialog } from "@/components/ActionDialog";
import { Highlighted } from "@/components/Highlighted";
import { StatusBadge } from "@/components/StatusBadge";
import { EmptyState, ErrorState, Field, Mono, Panel } from "@/components/ui";
import { apiGet, currentUser, type Schemas } from "@/lib/api-server";
import { formatDated, formatTime, label, moment } from "@/lib/format";
import { can } from "@/lib/roles";

export const metadata: Metadata = { title: "Source" };

export default async function SourcePage({ params }: { params: Promise<{ projectId: string; sourceId: string; revision: string }> }) {
  const { projectId, sourceId, revision } = await params;
  const [detail, me] = await Promise.all([
    apiGet<Schemas["SourceRevisionDetail"]>(`/v1/sources/${sourceId}/revisions/${revision}`),
    currentUser(),
  ]);
  if (detail.status === 404) notFound();
  if (!detail.data) return <ErrorState status={detail.status} error={detail.error} requestId={detail.requestId} />;
  const { source, permitted_text: text, links, evidence } = detail.data;
  const own = evidence.filter((e) => e.evidence.project_id === projectId);
  const spans = own
    .filter((e) => e.anchor_view.kind === "text")
    .map((e) => {
      const view = e.anchor_view as Schemas["TextAnchorView"];
      return { start: view.utf16_start, end: view.utf16_end, eligible: e.eligible };
    });
  const projectLinks = links.filter((l) => l.project_id === projectId);

  return (
    <div className="grid gap-6 xl:grid-cols-[1fr_24rem]">
      <div className="space-y-4">
        <Panel title={source.title ?? "Untitled source"}>
          {text === null ? (
            <EmptyState>
              {source.lifecycle === "active"
                ? source.media
                  ? "A video: its words are the transcript segments below, when a transcript route exists."
                  : "Metadata only: no text was captured, so this source is not evidence of what it says."
                : `This source was ${source.lifecycle}; its words were erased.`}
            </EmptyState>
          ) : (
            <Highlighted text={text} spans={spans} />
          )}
        </Panel>
        <Panel title="Evidence spans for this project">
          {own.length === 0 ? (
            <EmptyState>No evidence from this source for this project.</EmptyState>
          ) : (
            <ul className="space-y-3">
              {own.map((e) => (
                <li key={`${e.evidence.id}@${e.evidence.revision}`} className="rounded border border-line p-3">
                  <div className="mb-1 flex flex-wrap items-center gap-2">
                    <StatusBadge status={e.eligible ? "eligible" : "ineligible"} />
                    <span className="text-ink-muted">
                      {label(e.evidence.modality)} · {e.evidence.language}
                      {e.anchor_view.kind === "time" ? ` · at ${moment((e.anchor_view as Schemas["TimeAnchor"]).start_ms)}` : ""}
                      {e.evidence.origin_cluster ? ` · origin ${e.evidence.origin_cluster.id}` : ""}
                    </span>
                  </div>
                  <p className="whitespace-pre-wrap">{e.evidence.excerpt_text ?? "(erased)"}</p>
                  {!e.eligible ? <p className="mt-1 text-danger">Not eligible: {e.ineligibility_reasons.map(label).join(", ")}</p> : null}
                </li>
              ))}
            </ul>
          )}
        </Panel>
      </div>
      <div className="space-y-4">
        <Panel title="Source">
          <dl>
            <Field label="Link">
              <a href={source.canonical_url} target="_blank" rel="noopener noreferrer" className="break-all text-accent underline">
                {source.canonical_url}
              </a>
            </Field>
            <Field label="Kind">{label(source.source_kind)}</Field>
            <Field label="Published">{formatDated(source.publication_date)}</Field>
            <Field label="Collected">{formatTime(source.collected_at)}</Field>
            <Field label="Policy">
              {source.policy.family} v{source.policy.policy_version}
            </Field>
            <Field label="State">
              <StatusBadge status={source.lifecycle} />
            </Field>
            <Field label="Revision">
              <Mono>
                {source.id} r{source.revision}
              </Mono>
            </Field>
          </dl>
          {can(me?.roles, "withdrawSource") && source.lifecycle === "active" ? (
            <div className="mt-3">
              <ActionDialog
                label="Withdraw source"
                title="Withdraw this source revision"
                path={`/v1/sources/${source.id}/withdrawals`}
                body={{ scope: "source_revision", revision: source.revision }}
                reason="required"
                idempotent
                tone="danger"
                description="Its words are erased, and every finding, review and page revision that rests on it is re-checked; a published page stops showing it."
              />
            </div>
          ) : null}
        </Panel>
        <Panel title="Project match">
          {projectLinks.length === 0 ? (
            <EmptyState>Not linked to this project.</EmptyState>
          ) : (
            <ul className="space-y-3">
              {projectLinks.map((link) => (
                <li key={link.id} className="space-y-1">
                  <div className="flex items-center gap-2">
                    <StatusBadge status={link.status} />
                    <span className="text-ink-muted">{label(link.match.method)}</span>
                  </div>
                  <p className="text-ink-muted">{link.match.rationale}</p>
                  {link.phase.rera_id ? <p>Phase {link.phase.rera_id} ({link.phase.certainty})</p> : null}
                  {can(me?.roles, "decideSourceLink") ? (
                    <div className="flex flex-wrap gap-2">
                      {link.status !== "accepted" ? (
                        <ActionDialog
                          label="Accept match"
                          title="Accept this project match"
                          path={`/v1/project-source-links/${link.id}/decisions`}
                          body={{ action: "accept", expected_version: link.version, split_segments: null, remap_project_id: null, phase_rera_id: link.phase.rera_id }}
                          reason="optional"
                          tone="primary"
                        />
                      ) : null}
                      {link.status !== "rejected" ? (
                        <ActionDialog
                          label="Reject match"
                          title="This source is not about this project"
                          path={`/v1/project-source-links/${link.id}/decisions`}
                          body={{ action: "reject", expected_version: link.version, split_segments: null, remap_project_id: null, phase_rera_id: null }}
                          reason="required"
                          tone="danger"
                        />
                      ) : null}
                    </div>
                  ) : null}
                </li>
              ))}
            </ul>
          )}
        </Panel>
      </div>
    </div>
  );
}
