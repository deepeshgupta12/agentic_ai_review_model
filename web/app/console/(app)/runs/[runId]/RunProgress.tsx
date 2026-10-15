"use client";

import { AutoRefresh } from "@/components/AutoRefresh";
import { StatusBadge } from "@/components/StatusBadge";
import { runIsWorking, stageLabel } from "@/lib/format";

const STAGES = ["collecting", "analysing", "findings_review", "formatting", "final_review", "approved", "publishing", "published"];

type Run = { stage: string; outcome_note: string | null; content_revision_id: string | null; updated_at: string };

/** Stage timeline. While the system works on the run the page refreshes itself (AutoRefresh: one refresh after the
 * other, none while the tab is hidden), so the coverage table moves live; in a stage that waits for a person it stays
 * still and the page says what to do (audit, 14 Oct 2026). */
export function RunProgress({ run }: { run: Run }) {
  const stage = run.stage;
  const reached = STAGES.indexOf(stage);
  return (
    <ol className="flex flex-wrap items-center gap-2" aria-label="Stages">
      {STAGES.map((s, i) => (
        <li key={s} className={`flex items-center gap-1 ${i <= reached ? "" : "opacity-40"}`} aria-current={s === stage ? "step" : undefined}>
          {s === stage ? <StatusBadge status={s} text={stageLabel(s)} /> : <span className="text-xs">{stageLabel(s)}</span>}
          {i < STAGES.length - 1 ? <span className="text-ink-muted">→</span> : null}
        </li>
      ))}
      {!STAGES.includes(stage) ? <StatusBadge status={stage} text={stageLabel(stage)} /> : null}
      <li className="ml-2">
        <AutoRefresh active={runIsWorking(run)} />
      </li>
    </ol>
  );
}
