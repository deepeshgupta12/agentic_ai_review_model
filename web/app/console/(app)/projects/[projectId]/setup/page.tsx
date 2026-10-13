import type { Metadata } from "next";

import { ActionDialog } from "@/components/ActionDialog";
import { StatusBadge } from "@/components/StatusBadge";
import { EmptyState, ErrorState, Field, Mono, Panel, Table, Td, Th } from "@/components/ui";
import { apiGet, currentUser, type Schemas } from "@/lib/api-server";
import { formatDay, label } from "@/lib/format";
import { can } from "@/lib/roles";

import { ConfigForm } from "./ConfigForm";

export const metadata: Metadata = { title: "Project setup" };

export default async function SetupPage({ params }: { params: Promise<{ projectId: string }> }) {
  const { projectId } = await params;
  const [detail, proposals, me, health] = await Promise.all([
    apiGet<Schemas["ProjectDetail"]>(`/v1/projects/${projectId}`),
    apiGet<Schemas["AliasProposalPage"]>(`/v1/projects/${projectId}/alias-proposals`, { limit: 50 }),
    currentUser(),
    apiGet<Schemas["ConnectorHealthList"]>("/v1/connectors/health"),
  ]);
  if (!detail.data) return <ErrorState status={detail.status} error={detail.error} requestId={detail.requestId} />;
  const { project, config } = detail.data;
  const statuses = Object.fromEntries((health.data?.connectors ?? []).map((c) => [c.connector_id, c.status]));
  const mayDecide = can(me?.roles, "decideAliasProposal");

  return (
    <div className="grid gap-6 xl:grid-cols-2">
      <Panel title="Input as supplied">
        <dl>
          <Field label="Name">{project.project_name}</Field>
          <Field label="Alternate names">{project.alternate_names.length ? project.alternate_names.join(", ") : "none"}</Field>
          <Field label="Locality, city">
            {project.locality}, {project.city}
            {"state" in project && project.state ? `, ${project.state}` : ""}
          </Field>
          <Field label="Micromarket">{project.micromarket ?? "not given"}</Field>
          <Field label="Developer">{project.developer ?? "not given"}</Field>
          <Field label="RERA registrations">
            {project.rera_registrations.length
              ? project.rera_registrations.map((r) => (
                  <div key={r.id}>
                    <Mono>{r.id}</Mono> {r.registered_name}
                  </div>
                ))
              : "none"}
          </Field>
          <Field label="Slug">
            <Mono>{project.slug}</Mono>
          </Field>
          <Field label="Configuration version">
            <Mono>{config.version}</Mono>
          </Field>
        </dl>
      </Panel>

      <Panel title="Construction status (D27)">
        {config.construction_status.length === 0 ? (
          <EmptyState>No status recorded: occupancy claims will be flagged as status unknown until one is added.</EmptyState>
        ) : (
          <ul className="space-y-1">
            {config.construction_status.map((s, i) => (
              <li key={i} className="flex flex-wrap items-center gap-2">
                <StatusBadge status={s.status} />
                <span>{s.applies_to.kind === "phase" ? `phase ${s.applies_to.rera_id}` : "whole project"}</span>
                <span className="text-ink-muted">
                  from {label(s.basis)}, {formatDay(s.as_of)}
                  {s.note ? ` · ${s.note}` : ""}
                </span>
              </li>
            ))}
          </ul>
        )}
      </Panel>

      <div className="xl:col-span-2">
        <ConfigForm config={config} connectorStatus={statuses} canEdit={can(me?.roles, "updateProjectConfig")} />
      </div>

      <Panel title="Approved names">
        <Table label="Approved names">
          <thead>
            <tr>
              <Th>Name</Th>
              <Th>Target</Th>
              <Th>Mode</Th>
              <Th>Origin</Th>
            </tr>
          </thead>
          <tbody>
            {config.aliases.map((a) => (
              <tr key={a.normalised + a.target.kind + (a.target.rera_id ?? "")}>
                <Td>{a.text}</Td>
                <Td>{a.target.kind === "phase" ? `phase ${a.target.rera_id}` : "project"}</Td>
                <Td>{label(a.mode)}</Td>
                <Td>{label(a.origin)}</Td>
              </tr>
            ))}
          </tbody>
        </Table>
      </Panel>

      <Panel title="Name proposals (D17)">
        {!proposals.data ? (
          <ErrorState status={proposals.status} error={proposals.error} />
        ) : proposals.data.items.length === 0 ? (
          <EmptyState>No proposed names. The identity agent proposes names it meets beside a strong identifier.</EmptyState>
        ) : (
          <ul className="space-y-3">
            {proposals.data.items.map((p) => (
              <li key={p.id} className="rounded border border-line p-3">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-medium">{p.alias_text}</span>
                  <StatusBadge status={p.status} />
                  <span className="text-ink-muted">
                    for {p.target.kind === "phase" ? `phase ${p.target.rera_id}` : "the project"} · {p.independent_origin_count} independent
                    origin(s) · identifier {label(p.strong_identifier.kind)}
                  </span>
                </div>
                {p.collision.status !== "none" ? (
                  <p className="mt-1 text-warn">
                    {label(p.collision.status)}: {p.collision.reason ?? "shared with another project"}; only context-required approval is offered.
                  </p>
                ) : null}
                {mayDecide ? (
                  <div className="mt-2 flex flex-wrap gap-2">
                    {p.status === "proposed" ? (
                      <>
                        {p.collision.status === "none" ? (
                          <ActionDialog
                            label="Approve standalone"
                            title={`Approve "${p.alias_text}" as a standalone name`}
                            path={`/v1/alias-proposals/${p.id}/decisions`}
                            body={{ action: "approve", mode: "standalone", expected_version: p.version }}
                            reason="optional"
                            tone="primary"
                          />
                        ) : null}
                        <ActionDialog
                          label="Approve with context"
                          title={`Approve "${p.alias_text}" only beside the project's place or developer`}
                          path={`/v1/alias-proposals/${p.id}/decisions`}
                          body={{ action: "approve", mode: "context_required", expected_version: p.version }}
                          reason="optional"
                        />
                        <ActionDialog
                          label="Reject"
                          title={`Reject "${p.alias_text}"`}
                          path={`/v1/alias-proposals/${p.id}/decisions`}
                          body={{ action: "reject", mode: null, expected_version: p.version }}
                          reason="required"
                          tone="danger"
                        />
                      </>
                    ) : p.status === "approved" ? (
                      <ActionDialog
                        label="Revoke"
                        title={`Revoke "${p.alias_text}"`}
                        path={`/v1/alias-proposals/${p.id}/decisions`}
                        body={{ action: "revoke", mode: null, expected_version: p.version }}
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
  );
}
