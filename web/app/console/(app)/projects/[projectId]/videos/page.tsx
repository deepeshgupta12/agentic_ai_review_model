import type { Metadata } from "next";
import Link from "next/link";

import { StatusBadge } from "@/components/StatusBadge";
import { EmptyState, ErrorState, MoreLink, Table, Td, Th } from "@/components/ui";
import { apiGet, type Schemas } from "@/lib/api-server";
import { formatDated, label, moment } from "@/lib/format";

export const metadata: Metadata = { title: "Videos" };

const STATUSES = ["discovered", "access_pending", "metadata_only", "transcribed", "analysed", "error"];

export default async function VideosPage({
  params,
  searchParams,
}: {
  params: Promise<{ projectId: string }>;
  searchParams: Promise<{ access_status?: string; format?: string; cursor?: string }>;
}) {
  const { projectId } = await params;
  const search = await searchParams;
  const page = await apiGet<Schemas["MediaPage"]>(`/v1/projects/${projectId}/media`, { ...search, limit: 50 });
  if (!page.data) return <ErrorState status={page.status} error={page.error} requestId={page.requestId} />;
  const input = "rounded border border-line px-2 py-1";

  return (
    <div className="space-y-4">
      <form className="flex flex-wrap items-end gap-3" aria-label="Filter videos">
        <label>
          <span className="mb-1 block text-ink-muted">Access</span>
          <select name="access_status" defaultValue={search.access_status ?? ""} className={input}>
            <option value="">any</option>
            {STATUSES.map((s) => (
              <option key={s} value={s}>
                {label(s)}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span className="mb-1 block text-ink-muted">Format</span>
          <select name="format" defaultValue={search.format ?? ""} className={input}>
            <option value="">any</option>
            <option value="video">video</option>
            <option value="short">Short</option>
            <option value="unknown">unknown</option>
          </select>
        </label>
        <button type="submit" className="rounded border border-line bg-surface px-3 py-1">
          Filter
        </button>
      </form>
      {page.data.items.length === 0 ? (
        <EmptyState>No videos for this project with these filters.</EmptyState>
      ) : (
        <Table label="Videos">
          <thead>
            <tr>
              <Th>Video</Th>
              <Th>Channel</Th>
              <Th>Format</Th>
              <Th>Access</Th>
              <Th>Match</Th>
              <Th>Analysed segments</Th>
            </tr>
          </thead>
          <tbody>
            {page.data.items.map((item) => {
              const media = item.source.media;
              const status = media?.access_status ?? "discovered";
              return (
                <tr key={`${item.source.id}@${item.source.revision}`}>
                  <Td className="max-w-sm">
                    <Link href={`/console/projects/${projectId}/evidence/${item.source.id}/${item.source.revision}`} className="text-accent underline">
                      {item.source.title ?? item.source.canonical_url}
                    </Link>
                    <div className="text-ink-muted">{formatDated(item.source.publication_date)}</div>
                  </Td>
                  <Td>{media?.channel.title ?? media?.channel.native_id ?? "unknown"}</Td>
                  <Td>
                    {label(media?.format ?? "unknown")}
                    <div className="text-xs text-ink-muted">basis: {label(media?.format_basis ?? "unknown")}</div>
                  </Td>
                  <Td>
                    <StatusBadge status={status} />
                    {status === "metadata_only" || status === "discovered" || status === "access_pending" ? (
                      <div className="mt-1 text-xs text-ink-muted">Title and description only: no evidence of what is said in the video.</div>
                    ) : null}
                  </Td>
                  <Td>
                    <StatusBadge status={item.link_status} />
                  </Td>
                  <Td>
                    {item.segments.length === 0 ? (
                      <span className="text-ink-muted">none</span>
                    ) : (
                      <ul className="space-y-0.5">
                        {item.segments.slice(0, 8).map((s) => (
                          <li key={s.id}>
                            <a
                              href={`${item.source.canonical_url}${item.source.canonical_url.includes("?") ? "&" : "?"}t=${Math.floor(s.time.start_ms / 1000)}s`}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="text-accent underline"
                            >
                              {moment(s.time.start_ms)}
                            </a>{" "}
                            <span className="text-ink-muted">{label(s.modality)}</span>
                          </li>
                        ))}
                        {item.segments.length > 8 ? <li className="text-ink-muted">and {item.segments.length - 8} more</li> : null}
                      </ul>
                    )}
                  </Td>
                </tr>
              );
            })}
          </tbody>
        </Table>
      )}
      <MoreLink cursor={page.data.next_cursor} params={search as Record<string, string>} path={`/console/projects/${projectId}/videos`} />
    </div>
  );
}
