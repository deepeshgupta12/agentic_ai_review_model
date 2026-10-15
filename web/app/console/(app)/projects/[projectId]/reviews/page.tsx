import type { Metadata } from "next";

import { DecisionButtons } from "@/components/DecisionButtons";
import { EvidenceList } from "@/components/EvidenceList";
import { StatusBadge } from "@/components/StatusBadge";
import { EmptyState, ErrorState, MoreLink } from "@/components/ui";
import { apiGet, backendInfo, currentUser, type Schemas } from "@/lib/api-server";
import { fitsPage, wordCount } from "@/lib/flow";
import { creditLine, label } from "@/lib/format";
import { can } from "@/lib/roles";

import { ReviewEditor } from "./ReviewEditor";

export const metadata: Metadata = { title: "Reviews" };

/** The site of a source address; an address the URL parser refuses does not break the page (audit, 14 Oct 2026). */
function hostOf(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return "the web";
  }
}

const KIND: Record<string, string> = { comment: "comment", video: "video", short: "video", user_review: "review" };

export default async function ReviewsPage({
  params,
  searchParams,
}: {
  params: Promise<{ projectId: string }>;
  searchParams: Promise<{ review_status?: string; cursor?: string }>;
}) {
  const { projectId } = await params;
  const search = await searchParams;
  const [page, me, info] = await Promise.all([
    apiGet<Schemas["ReviewExcerptPage"]>(`/v1/projects/${projectId}/review-excerpts`, { ...search, limit: 20 }),
    currentUser(),
    backendInfo(),
  ]);
  if (!page.data) return <ErrorState status={page.status} error={page.error} requestId={page.requestId} />;
  const mayDecide = can(me?.roles, "decideReviewExcerpt");

  return (
    <div className="space-y-4">
      <p className="max-w-3xl text-ink-muted">
        Each is one person&apos;s review from a portal, Reddit, Quora, a forum or YouTube, in their own words (D28). Approve the ones that are
        real reviews of this project; positive and negative are decided the same way. A flagged review or a rendering mismatch cannot be
        approved. The page shows reviews of {info.review_words_min} to {info.review_words_max} words.
      </p>
      <form className="flex items-end gap-3" aria-label="Filter reviews">
        <label>
          <span className="mb-1 block text-ink-muted">Status</span>
          <select name="review_status" defaultValue={search.review_status ?? ""} className="rounded border border-line px-2 py-1">
            <option value="">open and decided</option>
            {["pending", "approved", "changes_requested", "rejected", "superseded"].map((s) => (
              <option key={s} value={s}>
                {label(s)}
              </option>
            ))}
          </select>
        </label>
        <button type="submit" className="rounded border border-line bg-surface px-3 py-1">
          Filter
        </button>
      </form>
      {page.data.items.length === 0 ? (
        <EmptyState>No first-person reviews with these filters.</EmptyState>
      ) : (
        page.data.items.map((view) => {
          const r = view.review;
          const flagged = r.consistency_flags.length > 0;
          const blocked = flagged ? `construction-status flag: ${r.consistency_flags.map(label).join(", ")}` : view.rendering_check === "mismatch" ? "the shown words do not match the original" : "";
          const credit = {
            speaker_label: r.speaker_label,
            platform: hostOf(view.source_url),
            kind: KIND[r.source_kind] ?? "post",
            published: r.published,
            timestamp_ms: r.timestamp_ms,
            translated_from: r.rendering === "translated" ? r.original_language : null,
          };
          return (
            <article key={`${r.id}@${r.revision}`} data-testid="review" className="grid gap-4 rounded-lg border border-line bg-surface p-4 xl:grid-cols-2">
              <div className="space-y-2">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="rounded border border-line px-1.5 text-xs font-medium">{r.polarity}</span>
                  <StatusBadge status={r.review_status} />
                  <StatusBadge status={view.rendering_check} />
                  <span className="text-xs text-ink-muted">
                    {label(r.rendering)} · revision {r.revision} · {r.aspects.map(label).join(", ")} · {wordCount(r.text)} words
                  </span>
                  {r.text && !fitsPage(r.text, info) ? (
                    <span className="text-xs text-warn">
                      outside {info.review_words_min} to {info.review_words_max} words: can be approved, not shown on the page
                    </span>
                  ) : null}
                </div>
                <blockquote className="border-l-2 border-ink-muted pl-3 text-[15px] leading-6">“{r.text ?? "(erased)"}”</blockquote>
                <p className="text-ink-muted">{creditLine(credit)}</p>
                {r.rendering !== "verbatim" ? (
                  <div className="rounded bg-surface-sunken p-2">
                    <p className="mb-1 text-xs text-ink-muted">Author&apos;s original words ({r.original_language})</p>
                    <p className="whitespace-pre-wrap">{r.original_text ?? "(erased)"}</p>
                  </div>
                ) : null}
                {flagged ? <p className="text-warn">Flagged: {r.consistency_flags.map(label).join(", ")}</p> : null}
                <p className="text-xs">
                  <a href={view.source_url} target="_blank" rel="noopener noreferrer" className="text-accent underline">
                    source (moderators only; never shown publicly)
                  </a>
                </p>
                {view.decisions.length ? (
                  <p className="text-xs text-ink-muted">
                    Decisions:{" "}
                    {view.decisions.map((d) => `${d.action} r${d.target.revision}${d.target.revision !== r.revision ? " (superseded)" : ""}${d.reason ? `: ${d.reason}` : ""}`).join(" · ")}
                  </p>
                ) : null}
                {mayDecide && r.review_status === "pending" ? (
                  <DecisionButtons
                    path={`/v1/review-excerpts/${r.id}/decisions`}
                    revision={r.revision}
                    subject="this review"
                    approvable={!blocked}
                    blockedReason={blocked}
                  />
                ) : null}
                {can(me?.roles, "reviseReviewExcerpt") && r.review_status !== "superseded" && r.text ? (
                  <ReviewEditor review={r} evidence={view.evidence} />
                ) : null}
              </div>
              <div>
                <h3 className="mb-2 font-medium">The spans it shows</h3>
                <EvidenceList projectId={projectId} evidence={view.evidence} />
              </div>
            </article>
          );
        })
      )}
      <MoreLink cursor={page.data.next_cursor} params={search as Record<string, string>} path={`/console/projects/${projectId}/reviews`} />
    </div>
  );
}
