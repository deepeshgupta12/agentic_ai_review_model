import type { Metadata } from "next";
import Link from "next/link";

import { StatusBadge } from "@/components/StatusBadge";
import { EmptyState, ErrorState, MoreLink, Table, Td, Th } from "@/components/ui";
import { apiGet, type Schemas } from "@/lib/api-server";
import { formatDated, label } from "@/lib/format";

export const metadata: Metadata = { title: "Evidence" };

const KINDS = ["forum_post", "forum_thread", "comment", "article", "news_article", "blog_post", "video", "short", "search_result", "registration_record"];
const ASPECTS = [
  "connectivity", "location", "layout", "construction_quality", "construction_progress", "possession", "amenities", "maintenance",
  "density", "parking", "water", "power", "service_management", "value_perception", "other",
];

type Search = {
  connector_id?: string;
  source_kind?: string;
  aspect?: string;
  language?: string;
  published_from?: string;
  published_to?: string;
  cursor?: string;
};

export default async function EvidencePage({ params, searchParams }: { params: Promise<{ projectId: string }>; searchParams: Promise<Search> }) {
  const { projectId } = await params;
  const search = await searchParams;
  const page = await apiGet<Schemas["SourcePage"]>(`/v1/projects/${projectId}/sources`, { ...search, limit: 50 });
  const input = "rounded border border-line px-2 py-1";

  return (
    <div className="space-y-4">
      <form className="flex flex-wrap items-end gap-3" aria-label="Filter sources">
        <label>
          <span className="mb-1 block text-ink-muted">Source</span>
          <input name="connector_id" defaultValue={search.connector_id} placeholder="e.g. youtube_data_api" className={input} />
        </label>
        <label>
          <span className="mb-1 block text-ink-muted">Kind</span>
          <select name="source_kind" defaultValue={search.source_kind ?? ""} className={input}>
            <option value="">any</option>
            {KINDS.map((k) => (
              <option key={k} value={k}>
                {label(k)}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span className="mb-1 block text-ink-muted">Aspect</span>
          <select name="aspect" defaultValue={search.aspect ?? ""} className={input}>
            <option value="">any</option>
            {ASPECTS.map((a) => (
              <option key={a} value={a}>
                {label(a)}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span className="mb-1 block text-ink-muted">Language</span>
          <input name="language" defaultValue={search.language} placeholder="hi, en, hi-Latn" className={`${input} w-28`} />
        </label>
        <label>
          <span className="mb-1 block text-ink-muted">From</span>
          <input type="date" name="published_from" defaultValue={search.published_from} className={input} />
        </label>
        <label>
          <span className="mb-1 block text-ink-muted">To</span>
          <input type="date" name="published_to" defaultValue={search.published_to} className={input} />
        </label>
        <button type="submit" className="rounded border border-line bg-surface px-3 py-1">
          Filter
        </button>
      </form>
      {!page.data ? (
        <ErrorState status={page.status} error={page.error} requestId={page.requestId} />
      ) : page.data.items.length === 0 ? (
        <EmptyState>No sources match. Collection may not have run, or the filters exclude everything.</EmptyState>
      ) : (
        <Table label="Sources">
          <thead>
            <tr>
              <Th>Source</Th>
              <Th>Kind</Th>
              <Th>Date</Th>
              <Th>Match</Th>
              <Th>Aspects</Th>
              <Th>Capture</Th>
            </tr>
          </thead>
          <tbody>
            {page.data.items.map((s) => (
              <tr key={`${s.source.id}@${s.source.revision}`}>
                <Td className="max-w-md">
                  <Link href={`/console/projects/${projectId}/evidence/${s.source.id}/${s.source.revision}`} className="text-accent underline">
                    {s.title ?? s.canonical_url}
                  </Link>
                  <div className="truncate font-mono text-xs text-ink-muted">{s.connector_id}</div>
                </Td>
                <Td>{label(s.source_kind)}</Td>
                <Td>{formatDated(s.publication_date)}</Td>
                <Td>
                  <StatusBadge status={s.link_status} />
                </Td>
                <Td className="text-ink-muted">{s.aspects.map(label).join(", ") || "none yet"}</Td>
                <Td>
                  <StatusBadge status={s.lifecycle === "active" ? s.capture_level : s.lifecycle} />
                </Td>
              </tr>
            ))}
          </tbody>
        </Table>
      )}
      <MoreLink cursor={page.data?.next_cursor ?? null} params={search as Record<string, string>} path={`/console/projects/${projectId}/evidence`} />
    </div>
  );
}
