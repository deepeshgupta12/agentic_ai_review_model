import type { Metadata } from "next";
import Link from "next/link";

import { ActionDialog } from "@/components/ActionDialog";
import { StatusBadge } from "@/components/StatusBadge";
import { EmptyState, ErrorState, MoreLink, PageTitle, Table, Td, Th } from "@/components/ui";
import { apiGet, apiGetAll, type Schemas } from "@/lib/api-server";
import { formatTime } from "@/lib/format";

export const metadata: Metadata = { title: "Corrections" };

export default async function CorrectionsPage({ searchParams }: { searchParams: Promise<{ status?: string; cursor?: string }> }) {
  const search = await searchParams;
  const [page, projects] = await Promise.all([
    apiGet<Schemas["CorrectionPage"]>("/v1/corrections", { ...search, limit: 50 }),
    apiGetAll<Schemas["ProjectSummary"]>("/v1/projects"),
  ]);
  if (!page.data) return <ErrorState status={page.status} error={page.error} requestId={page.requestId} />;
  const names = Object.fromEntries((projects.data?.items ?? []).map((p) => [p.project.id, p.project.project_name]));

  return (
    <section className="space-y-4">
      <PageTitle title="Corrections">
        Reports from readers of the public pages. Resolve or dismiss with a reason; a correction to the content goes through the normal edit
        and approval path.
      </PageTitle>
      <form className="flex items-end gap-3" aria-label="Filter corrections">
        <label>
          <span className="mb-1 block text-ink-muted">Status</span>
          <select name="status" defaultValue={search.status ?? ""} className="rounded border border-line px-2 py-1">
            <option value="">all</option>
            {["received", "in_review", "resolved", "dismissed"].map((s) => (
              <option key={s} value={s}>
                {s.replaceAll("_", " ")}
              </option>
            ))}
          </select>
        </label>
        <button type="submit" className="rounded border border-line bg-surface px-3 py-1">
          Filter
        </button>
      </form>
      {page.data.items.length === 0 ? (
        <EmptyState>No corrections reported.</EmptyState>
      ) : (
        <Table label="Corrections">
          <thead>
            <tr>
              <Th>Received</Th>
              <Th>Project</Th>
              <Th>Message</Th>
              <Th>Contact</Th>
              <Th>Status</Th>
              <Th>Decide</Th>
            </tr>
          </thead>
          <tbody>
            {page.data.items.map((c) => (
              <tr key={c.id}>
                <Td>{formatTime(c.created_at)}</Td>
                <Td>
                  <Link href={`/console/projects/${c.project_id}/content${c.revision_id ? `/${c.revision_id}` : ""}`} className="text-accent underline">
                    {names[c.project_id] ?? c.project_id}
                  </Link>
                </Td>
                <Td className="max-w-md whitespace-pre-wrap">{c.message}</Td>
                <Td>{c.contact ?? "none"}</Td>
                <Td>
                  <StatusBadge status={c.status} />
                </Td>
                <Td>
                  {["received", "in_review"].includes(c.status) ? (
                    <div className="flex gap-2">
                      <ActionDialog label="Resolve" title="Resolve this correction" path={`/v1/corrections/${c.id}/decisions`} body={{ action: "resolve" }} reason="required" tone="primary" />
                      <ActionDialog label="Dismiss" title="Dismiss this correction" path={`/v1/corrections/${c.id}/decisions`} body={{ action: "dismiss" }} reason="required" />
                    </div>
                  ) : null}
                </Td>
              </tr>
            ))}
          </tbody>
        </Table>
      )}
      <MoreLink cursor={page.data.next_cursor} params={search as Record<string, string>} path="/console/corrections" />
    </section>
  );
}
