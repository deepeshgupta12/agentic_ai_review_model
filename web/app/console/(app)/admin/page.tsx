import type { Metadata } from "next";

import { StatusBadge } from "@/components/StatusBadge";
import { EmptyState, ErrorState, Mono, MoreLink, PageTitle, Panel, Table, Td, Th } from "@/components/ui";
import { apiGet, currentUser, type Schemas } from "@/lib/api-server";
import { formatTime } from "@/lib/format";
import { can } from "@/lib/roles";

import { PolicyVersionForm } from "./PolicyVersionForm";
import { UserForms } from "./UserForms";

export const metadata: Metadata = { title: "Administration" };

type Search = { target_type?: string; target_id?: string; cursor?: string };

export default async function AdminPage({ searchParams }: { searchParams: Promise<Search> }) {
  const search = await searchParams;
  const me = await currentUser();
  const [users, policies, audit] = await Promise.all([
    can(me?.roles, "listUsers") ? apiGet<Schemas["UserPage"]>("/v1/admin/users", { limit: 100 }) : null,
    apiGet<Schemas["PolicyPage"]>("/v1/admin/source-policies", { limit: 100 }),
    can(me?.roles, "listAuditEvents") ? apiGet<Schemas["AuditEventPage"]>("/v1/admin/audit-events", { ...search, limit: 50 }) : null,
  ]);

  return (
    <section className="space-y-6">
      <PageTitle title="Administration">Users and roles, source policies and the audit record.</PageTitle>
      {users ? (
        users.data ? (
          <UserForms users={users.data.items} myId={me?.id ?? ""} />
        ) : (
          <ErrorState status={users.status} error={users.error} />
        )
      ) : null}

      <Panel title="Source policies (current and earlier versions)">
        {!policies.data ? (
          <ErrorState status={policies.status} error={policies.error} />
        ) : (
          <Table label="Source policies">
            <thead>
              <tr>
                <Th>Family</Th>
                <Th>Version</Th>
                <Th>Collect</Th>
                <Th>AI use</Th>
                <Th>Quote</Th>
                <Th>robots.txt</Th>
                <Th>Hosts</Th>
                <Th>Basis</Th>
              </tr>
            </thead>
            <tbody>
              {policies.data.items.map((p) => (
                <tr key={p.id}>
                  <Td>
                    <Mono>{p.family}</Mono>
                  </Td>
                  <Td>v{p.policy_version}</Td>
                  <Td>{p.collection_allowed ? "yes" : "no"}</Td>
                  <Td>{p.ai_processing_allowed ? "yes" : "no"}</Td>
                  <Td>{p.quotation_allowed ? "yes" : "no"}</Td>
                  <Td>{p.robots_txt.replaceAll("_", " ")}</Td>
                  <Td className="max-w-[14rem] text-ink-muted">{p.host_scope === "any_public_host" ? "any public host" : `${p.hosts.length} hosts`}</Td>
                  <Td className="max-w-md text-ink-muted">{p.basis}</Td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
        {can(me?.roles, "createSourcePolicyVersion") ? <PolicyVersionForm policies={policies.data?.items ?? []} /> : null}
      </Panel>

      {audit ? (
        <Panel title="Audit record">
          <form className="mb-3 flex flex-wrap items-end gap-3" aria-label="Search audit">
            <input name="target_type" defaultValue={search.target_type} placeholder="target type (e.g. finding)" className="rounded border border-line px-2 py-1" />
            <input name="target_id" defaultValue={search.target_id} placeholder="target ID" className="rounded border border-line px-2 py-1" />
            <button type="submit" className="rounded border border-line bg-surface px-3 py-1">
              Search
            </button>
          </form>
          {!audit.data ? (
            <ErrorState status={audit.status} error={audit.error} />
          ) : audit.data.items.length === 0 ? (
            <EmptyState>No audit events match.</EmptyState>
          ) : (
            <Table label="Audit events">
              <thead>
                <tr>
                  <Th>When</Th>
                  <Th>Action</Th>
                  <Th>Target</Th>
                  <Th>Actor</Th>
                  <Th>Details</Th>
                </tr>
              </thead>
              <tbody>
                {audit.data.items.map((e) => (
                  <tr key={e.id}>
                    <Td>{formatTime(e.at)}</Td>
                    <Td>
                      <StatusBadge status={e.action} />
                    </Td>
                    <Td>
                      <Mono>
                        {e.target.type} {e.target.id}
                        {e.target.revision ? ` r${e.target.revision}` : ""}
                      </Mono>
                    </Td>
                    <Td>{e.actor.kind === "user" ? `${e.actor.role} ${e.actor.user_id?.slice(-6)}` : e.actor.kind}</Td>
                    <Td className="max-w-md text-xs text-ink-muted">
                      {Object.entries(e.details)
                        .filter(([, v]) => v !== null)
                        .map(([k, v]) => `${k}: ${String(v)}`)
                        .join(" · ")}
                    </Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          )}
          <MoreLink cursor={audit.data?.next_cursor ?? null} params={search as Record<string, string>} path="/console/admin" />
        </Panel>
      ) : null}
    </section>
  );
}
