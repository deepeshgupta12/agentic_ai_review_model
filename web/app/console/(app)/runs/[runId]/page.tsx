import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { ActionDialog } from "@/components/ActionDialog";
import { AutoRefresh } from "@/components/AutoRefresh";
import { Icon } from "@/components/icons";
import { SourceCard } from "@/components/SourceCard";
import { StatusBadge } from "@/components/StatusBadge";
import { BUTTON, Card, ErrorState, Notice, ProgressBar, Stat } from "@/components/ui";
import { apiGet, currentUser, type Schemas } from "@/lib/api-server";
import { ago, coverageState, duration, formatDay, formatTime, runBadge, runIsWorking, since, STOPPED } from "@/lib/format";
import { can } from "@/lib/roles";

import { RunProgress } from "./RunProgress";

export const metadata: Metadata = { title: "Run" };

// The stages a researcher may cancel from (contracts/v1/state_machines.json workflow_stage).
const CANCELLABLE = ["collecting", "analysing", "findings_review", "formatting", "final_review"];

/** What to change before continuing a stopped run, read from the reason the backend wrote. */
function budgetAdvice(note: string): string | null {
  if (note.includes("RUN_BUDGET_USD")) return "Raise RUN_BUDGET_USD in .env and restart the stack (docker compose up -d), then continue.";
  if (/model budget/i.test(note)) return "Raise MODEL_BUDGET_USD in .env and restart the stack (docker compose up -d), then continue.";
  return null;
}

/** What the run's stage asks of people next, with the place to do it. */
function nextAction(run: Schemas["WorkflowRun"], slug: string | undefined): { text: string; href: string; action: string } | null {
  const base = `/console/projects/${run.project_id}`;
  switch (run.stage) {
    case "findings_review":
      return { text: "The reviews found are waiting for a moderator's decisions.", href: `${base}/reviews?review_status=pending`, action: "Decide the reviews" };
    case "formatting":
    case "final_review":
      return { text: "The page is being built from the approved reviews, or waits for its final approval.", href: `${base}/content`, action: "Open the page" };
    case "approved":
      return { text: "The page is approved and waits for a publisher.", href: `${base}/publishing`, action: "Publish" };
    case "published":
      return slug ? { text: "The page is live.", href: `/projects/${slug}`, action: "View the public page" } : null;
    default:
      return null;
  }
}

const ORDER: Record<string, number> = { running: 0, queued: 2 };

export default async function RunPage({ params }: { params: Promise<{ runId: string }> }) {
  const { runId } = await params;
  const [run, me] = await Promise.all([apiGet<Schemas["WorkflowRun"]>(`/v1/runs/${runId}`), currentUser()]);
  if (run.status === 404) notFound();
  if (!run.data) return <ErrorState status={run.status} error={run.error} requestId={run.requestId} />;
  const r = run.data;
  const project = await apiGet<Schemas["ProjectDetail"]>(`/v1/projects/${r.project_id}`);
  const name = project.data?.project.project_name ?? "the project";
  const next = nextAction(r, project.data?.project.slug);
  // An analysis or page building that stopped (budget, model access, a failure) waits until someone continues it.
  const note = r.outcome_note ?? "";
  const stopped = ["analysing", "formatting"].includes(r.stage) && STOPPED.test(note);
  const advice = stopped ? budgetAdvice(note) : null;
  const working = runIsWorking(r);
  const badge = runBadge(r);

  // The sources that run (access pending ones are recorded as not read and never start), and how many finished.
  const states = r.coverage.map((c) => ({ c, state: coverageState(c, r.stage) }));
  const runnable = states.filter(({ c }) => c.status !== "access_pending");
  const finished = runnable.filter(({ state }) => state.text !== "queued" && state.text !== "running").length;
  const notAvailable = states.length - runnable.length;
  const total = (key: "fetched" | "matched" | "analysed") => r.coverage.reduce((sum, c) => sum + c[key], 0);
  const cards = [...states].sort(
    (a, b) => (a.c.status === "access_pending" ? 3 : (ORDER[a.state.text] ?? 1)) - (b.c.status === "access_pending" ? 3 : (ORDER[b.state.text] ?? 1)),
  );
  const spentShare = r.budget.max_usd > 0 ? r.budget.spent_usd / r.budget.max_usd : 0;
  const elapsed = since(r.created_at, working ? undefined : r.updated_at);

  return (
    <div className="space-y-6">
      <nav aria-label="Breadcrumb" className="flex items-center gap-1.5 text-xs text-ink-muted">
        <Link href="/console" className="hover:text-ink hover:underline">
          Portfolio
        </Link>
        <span aria-hidden="true">/</span>
        <Link href={`/console/projects/${r.project_id}/runs`} className="hover:text-ink hover:underline">
          {name}
        </Link>
        <span aria-hidden="true">/</span>
        <span className="text-ink">Run</span>
      </nav>

      <Card className="overflow-hidden">
        <div className="flex flex-wrap items-start gap-4 border-b border-line p-5">
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-3">
              <h1 className="text-2xl font-semibold tracking-tight">Run of {name}</h1>
              <StatusBadge status={badge.status} text={badge.text} size="md" />
              <AutoRefresh active={working} />
            </div>
            <p className="mt-1.5 flex flex-wrap items-center gap-x-4 gap-y-1 text-[13px] text-ink-muted">
              <span className="font-mono text-xs">{r.id}</span>
              <span className="inline-flex items-center gap-1">
                <Icon name="clock" className="h-3.5 w-3.5" />
                started {formatTime(r.created_at)}
              </span>
              <span>{working ? `running for ${duration(elapsed)}` : `last change ${ago(r.updated_at)}`}</span>
              <span>
                reviews from {formatDay(r.window.from)} to {formatDay(r.window.to)}
              </span>
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Link href={`/console/projects/${r.project_id}/runs`} className={BUTTON.secondary}>
              All runs of this project
            </Link>
            {can(me?.roles, "cancelRun") && CANCELLABLE.includes(r.stage) ? (
              <ActionDialog label="Cancel run" title="Cancel this run" path={`/v1/runs/${r.id}/cancel`} body={{}} reason="required" tone="danger" />
            ) : null}
          </div>
        </div>
        <div className="bg-linear-to-b from-surface-sunken/60 to-surface px-3 py-5 sm:px-6">
          <RunProgress run={r} />
        </div>
      </Card>

      {stopped ? (
        <div data-testid="analysis-stopped" className="flex flex-wrap items-center gap-4 rounded-lg border border-warn/30 bg-warn-soft p-4">
          <span aria-hidden="true" className="inline-flex h-9 w-9 items-center justify-center rounded-full bg-warn text-white">
            <Icon name="stop" />
          </span>
          <p className="min-w-0 flex-1 text-ink">
            <span className="block font-semibold text-warn">{r.stage === "formatting" ? "Page building stopped" : "Analysis stopped"}</span>
            {note}
            {advice ? <span className="mt-1 block font-medium">{advice}</span> : null}
          </p>
          {can(me?.roles, "continueAnalysis") ? (
            <ActionDialog
              label={r.stage === "formatting" ? "Continue building the page" : "Continue analysis"}
              title="Continue from where it stopped"
              path={`/v1/runs/${r.id}/analysis`}
              body={{}}
              tone="primary"
              testId="continue-analysis"
              description="It continues from its last checkpoint: the work already done is reused and not paid for again. The model budget must have money left."
            />
          ) : null}
        </div>
      ) : null}
      {next ? (
        <div data-testid="run-next" className="flex flex-wrap items-center gap-4 rounded-lg border border-accent/25 bg-accent-soft p-4">
          <span aria-hidden="true" className="inline-flex h-9 w-9 items-center justify-center rounded-full bg-accent text-white">
            <Icon name="arrow" />
          </span>
          <p className="min-w-0 flex-1 font-medium text-ink">{next.text}</p>
          <Link href={next.href} target={next.href.startsWith("/projects/") ? "_blank" : undefined} className={BUTTON.primary}>
            {next.action}
            <Icon name={next.href.startsWith("/projects/") ? "external" : "arrow"} />
          </Link>
        </div>
      ) : null}
      {r.stage === "insufficient_evidence" ? (
        <Notice tone="idle">
          No usable first-person review was found. This is a valid result and no page content is created. The sources below show what was
          and was not read; check the project&apos;s names and sources in Setup before running again.
        </Notice>
      ) : null}

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-5">
        <Stat
          label="Sources done"
          icon="layers"
          tone={finished === runnable.length ? "ok" : "info"}
          value={
            <>
              {finished}
              <span className="text-base font-medium text-ink-muted"> of {runnable.length}</span>
            </>
          }
          hint={notAvailable ? `${notAvailable} not available (no credential)` : "every planned source"}
        >
          <div className="mt-2">
            <ProgressBar value={finished} max={runnable.length} tone={finished === runnable.length ? "ok" : "info"} live={working && r.stage === "collecting"} label="Sources done" size="sm" />
          </div>
        </Stat>
        <Stat label="Read" icon="page" value={total("fetched")} hint="pages, posts and comments stored" tone="neutral" />
        <Stat label="Matched" icon="pin" value={total("matched")} hint="belong to this project" tone="accent" />
        <Stat label="Analysed" icon="quote" value={total("analysed")} hint="read for first-person reviews" tone="info" />
        <Stat
          label="Model spend"
          icon="coins"
          tone={r.budget.exhausted ? "danger" : spentShare > 0.8 ? "warn" : "neutral"}
          value={`$${r.budget.spent_usd.toFixed(3)}`}
          hint={`of $${r.budget.max_usd.toFixed(2)} for this run${r.budget.exhausted ? " · budget reached" : ""}`}
        >
          <div className="mt-2">
            <ProgressBar
              value={r.budget.spent_usd}
              max={r.budget.max_usd}
              tone={r.budget.exhausted ? "danger" : spentShare > 0.8 ? "warn" : "accent"}
              label="Model spend"
              size="sm"
            />
          </div>
        </Stat>
      </div>

      {note && !stopped ? (
        <p className="flex items-start gap-2 rounded-lg border border-line bg-surface px-4 py-3 text-ink-muted shadow-card">
          <Icon name="inbox" className="mt-0.5 h-4 w-4" />
          <span>{note}</span>
        </p>
      ) : null}
      {r.content_revision_id ? (
        <Link href={`/console/projects/${r.project_id}/content/${r.content_revision_id}`} className={BUTTON.secondary}>
          Open the generated page content <Icon name="arrow" />
        </Link>
      ) : null}

      <section aria-labelledby="sources-heading">
        <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
          <h2 id="sources-heading" className="text-lg font-semibold tracking-tight">
            Sources
          </h2>
          <p className="text-xs text-ink-muted">Access pending, partial and unavailable are not zero discussion: they say a source was not fully read.</p>
        </div>
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {cards.map(({ c }) => (
            <SourceCard key={c.connector_id} c={c} stage={r.stage} />
          ))}
        </div>
      </section>
    </div>
  );
}
