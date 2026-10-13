import type { Metadata } from "next";

import { DecisionButtons } from "@/components/DecisionButtons";
import { EvidenceList } from "@/components/EvidenceList";
import { StatusBadge } from "@/components/StatusBadge";
import { EmptyState, ErrorState, MoreLink } from "@/components/ui";
import { apiGet, currentUser, type Schemas } from "@/lib/api-server";
import { formatTime, label } from "@/lib/format";
import { can } from "@/lib/roles";

import { FindingEditor } from "./FindingEditor";

export const metadata: Metadata = { title: "Findings" };

const STATUSES = ["pending", "approved", "changes_requested", "rejected", "superseded"];

export default async function FindingsPage({
  params,
  searchParams,
}: {
  params: Promise<{ projectId: string }>;
  searchParams: Promise<{ review_status?: string; kind?: string; cursor?: string }>;
}) {
  const { projectId } = await params;
  const search = await searchParams;
  const [page, me] = await Promise.all([
    apiGet<Schemas["FindingPage"]>(`/v1/projects/${projectId}/findings`, { ...search, limit: 20 }),
    currentUser(),
  ]);
  if (!page.data) return <ErrorState status={page.status} error={page.error} requestId={page.requestId} />;
  const mayDecide = can(me?.roles, "decideFinding");
  const input = "rounded border border-line px-2 py-1";

  return (
    <div className="space-y-4">
      <p className="max-w-3xl text-ink-muted">
        Pros, cons and neutral points written from the claims, each with the exact evidence beside it. Independent origins count spread, not
        proof. Negative findings use the same controls as positive ones; lists may be unequal or empty.
      </p>
      <form className="flex flex-wrap items-end gap-3" aria-label="Filter findings">
        <label>
          <span className="mb-1 block text-ink-muted">Status</span>
          <select name="review_status" defaultValue={search.review_status ?? ""} className={input}>
            <option value="">open and decided</option>
            {STATUSES.map((s) => (
              <option key={s} value={s}>
                {label(s)}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span className="mb-1 block text-ink-muted">Kind</span>
          <select name="kind" defaultValue={search.kind ?? ""} className={input}>
            <option value="">any</option>
            <option value="pro">pro</option>
            <option value="con">con</option>
            <option value="neutral">neutral</option>
          </select>
        </label>
        <button type="submit" className="rounded border border-line bg-surface px-3 py-1">
          Filter
        </button>
      </form>
      {page.data.items.length === 0 ? (
        <EmptyState>No findings with these filters. Findings appear after an analysis reaches findings review.</EmptyState>
      ) : (
        page.data.items.map((view) => {
          const f = view.finding;
          const contradicting = view.claims.flatMap((c) => c.contradicting_evidence.map((e) => e.id));
          return (
            <article key={`${f.id}@${f.revision}`} data-testid="finding" className="grid gap-4 rounded-lg border border-line bg-surface p-4 xl:grid-cols-2">
              <div className="space-y-2">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="rounded border border-line px-1.5 text-xs font-medium uppercase">{f.kind}</span>
                  <span className="text-ink-muted">{label(f.aspect)}</span>
                  <StatusBadge status={f.review_status} />
                  <span className="text-xs text-ink-muted">
                    revision {f.revision} · {f.created_by.kind} · {formatTime(f.created_at)}
                  </span>
                </div>
                <p className="text-[15px] leading-6">{f.wording}</p>
                <p className="text-ink-muted">
                  {label(f.attribution)} · {f.independent_origin_count} independent origin(s)
                </p>
                {f.caveats.length ? (
                  <ul className="list-disc pl-5 text-ink-muted">
                    {f.caveats.map((c) => (
                      <li key={c}>{c}</li>
                    ))}
                  </ul>
                ) : null}
                <details>
                  <summary className="cursor-pointer text-accent">{view.claims.length} claim(s)</summary>
                  <ul className="mt-2 space-y-1">
                    {view.claims.map((c) => (
                      <li key={c.id}>
                        <span className="text-xs text-ink-muted">
                          {label(c.claim_type)} · {label(c.polarity)} · {label(c.verification.status)} ·{" "}
                        </span>
                        {c.statement}
                        {c.consistency_flags.length ? <span className="ml-1 text-warn">({c.consistency_flags.map(label).join(", ")})</span> : null}
                      </li>
                    ))}
                  </ul>
                </details>
                {!view.eligible ? <p className="text-danger">Cannot be approved now: {view.ineligibility_reasons.join("; ")}</p> : null}
                {view.decisions.length ? (
                  <p className="text-xs text-ink-muted">
                    Decisions:{" "}
                    {view.decisions
                      .map((d) => `${d.action} r${d.target.revision}${d.target.revision !== f.revision ? " (superseded)" : ""}${d.reason ? `: ${d.reason}` : ""}`)
                      .join(" · ")}
                  </p>
                ) : null}
                {mayDecide && f.review_status === "pending" ? (
                  <DecisionButtons
                    path={`/v1/findings/${f.id}/decisions`}
                    revision={f.revision}
                    subject="this finding"
                    approvable={view.eligible}
                    blockedReason={view.ineligibility_reasons.join("; ")}
                  />
                ) : null}
                {can(me?.roles, "reviseFinding") && f.review_status !== "superseded" ? <FindingEditor finding={f} claims={view.claims} /> : null}
              </div>
              <div>
                <h3 className="mb-2 font-medium">Evidence</h3>
                <EvidenceList projectId={projectId} evidence={view.evidence} contradicting={contradicting} />
              </div>
            </article>
          );
        })
      )}
      <MoreLink cursor={page.data.next_cursor} params={search as Record<string, string>} path={`/console/projects/${projectId}/findings`} />
    </div>
  );
}
