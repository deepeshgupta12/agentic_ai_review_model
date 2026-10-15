import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { ActionDialog } from "@/components/ActionDialog";
import { StatusBadge } from "@/components/StatusBadge";
import { ErrorState, Mono, Panel, Table, Td, Th } from "@/components/ui";
import { apiGet, currentUser, type Schemas } from "@/lib/api-server";
import { connectorName, coverageState, formatTime, STOPPED, stageLabel } from "@/lib/format";
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

export default async function RunPage({ params }: { params: Promise<{ runId: string }> }) {
  const { runId } = await params;
  const [run, me] = await Promise.all([apiGet<Schemas["WorkflowRun"]>(`/v1/runs/${runId}`), currentUser()]);
  if (run.status === 404) notFound();
  if (!run.data) return <ErrorState status={run.status} error={run.error} requestId={run.requestId} />;
  const r = run.data;
  const project = await apiGet<Schemas["ProjectDetail"]>(`/v1/projects/${r.project_id}`);
  const next = nextAction(r, project.data?.project.slug);
  // An analysis or page building that stopped (budget, model access, a failure) waits until someone continues it.
  const note = r.outcome_note ?? "";
  const stopped = ["analysing", "formatting"].includes(r.stage) && STOPPED.test(note);
  const advice = stopped ? budgetAdvice(note) : null;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-lg font-semibold">Run of {project.data?.project.project_name ?? "the project"}</h1>
        <Mono>{r.id}</Mono>
        <StatusBadge status={r.stage} text={stageLabel(r.stage)} />
        <Link href={`/console/projects/${r.project_id}/runs`} className="text-accent underline">
          all runs of this project
        </Link>
        {can(me?.roles, "cancelRun") && CANCELLABLE.includes(r.stage) ? (
          <ActionDialog label="Cancel run" title="Cancel this run" path={`/v1/runs/${r.id}/cancel`} body={{}} reason="required" tone="danger" />
        ) : null}
      </div>
      {stopped ? (
        <div data-testid="analysis-stopped" className="flex flex-wrap items-center gap-3 rounded-lg border-l-4 border-warn bg-surface p-3">
          <p className="flex-1">
            {note}
            {advice ? ` ${advice}` : ""}
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
        <div data-testid="run-next" className="flex flex-wrap items-center gap-3 rounded-lg border-l-4 border-accent bg-surface p-3">
          <p className="flex-1">{next.text}</p>
          <Link href={next.href} target={next.href.startsWith("/projects/") ? "_blank" : undefined} className="rounded bg-accent px-3 py-1.5 font-medium text-white">
            {next.action}
          </Link>
        </div>
      ) : null}
      {r.stage === "insufficient_evidence" ? (
        <p className="rounded border border-idle bg-surface p-3">
          No usable first-person review was found. This is a valid result and no page content is created. The coverage below shows what was
          and was not read; check the project&apos;s names and sources in Setup before running again.
        </p>
      ) : null}
      <Panel title="Progress">
        <RunProgress run={r} />
        <p className="mt-3 text-ink-muted">{r.outcome_note}</p>
        <p className="mt-1 text-ink-muted">
          Window {formatTime(r.window.from)} to {formatTime(r.window.to)} · model spend ${r.budget.spent_usd.toFixed(3)} of ${r.budget.max_usd.toFixed(2)}
          {r.budget.exhausted ? " · budget reached" : ""}
        </p>
        {r.content_revision_id ? (
          <Link href={`/console/projects/${r.project_id}/content/${r.content_revision_id}`} className="mt-2 inline-block text-accent underline">
            Open the generated page content
          </Link>
        ) : null}
      </Panel>
      <Panel title="Coverage by source">
        <Table label="Coverage">
          <thead>
            <tr>
              <Th>Source</Th>
              <Th>Status</Th>
              <Th>Queries</Th>
              <Th>Read</Th>
              <Th>Matched</Th>
              <Th>Analysed</Th>
              <Th>Metadata only</Th>
              <Th>Last success</Th>
              <Th>Note</Th>
            </tr>
          </thead>
          <tbody>
            {r.coverage.map((c) => (
              <tr key={c.connector_id}>
                <Td>
                  {connectorName(c.connector_id)}
                  <div className="font-mono text-[11px] text-ink-muted">{c.connector_id}</div>
                </Td>
                <Td>
                  <StatusBadge status={coverageState(c, r.stage).status} text={coverageState(c, r.stage).text} />
                </Td>
                <Td>{c.attempted_queries}</Td>
                <Td>{c.fetched}</Td>
                <Td>{c.matched}</Td>
                <Td>{c.analysed}</Td>
                <Td>{c.metadata_only}</Td>
                <Td>{formatTime(c.last_success_at)}</Td>
                <Td className="max-w-xs break-words text-ink-muted">{coverageState(c, r.stage).detail}</Td>
              </tr>
            ))}
          </tbody>
        </Table>
        <p className="mt-2 text-xs text-ink-muted">Access pending, partial and unavailable are not zero discussion: they say a source was not fully read.</p>
      </Panel>
    </div>
  );
}
