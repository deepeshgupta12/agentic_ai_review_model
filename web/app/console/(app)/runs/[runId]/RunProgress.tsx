"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { StatusBadge } from "@/components/StatusBadge";
import { stageLabel } from "@/lib/format";

const STAGES = ["collecting", "analysing", "findings_review", "formatting", "final_review", "approved", "publishing", "published"];
// Stages in which the system is working: the page refreshes on every poll so coverage counts move as sources are read.
const WORKING = ["collecting", "analysing", "formatting", "publishing"];

/** Stage timeline that follows the run by polling getRun every few seconds (the documented fallback for SSE,
 * docs/03). While the system works the whole page refreshes, so the coverage table updates as it goes. */
export function RunProgress({ runId, initialStage, terminal }: { runId: string; initialStage: string; terminal: string[] }) {
  const router = useRouter();
  const [stage, setStage] = useState(initialStage);

  useEffect(() => {
    if (terminal.includes(stage)) return;
    const timer = setInterval(async () => {
      const response = await fetch(`/v1/runs/${runId}`, { credentials: "same-origin", cache: "no-store" }).catch(() => null);
      if (!response?.ok) return;
      const body = (await response.json()) as { stage: string };
      if (body.stage !== stage) setStage(body.stage);
      if (body.stage !== stage || WORKING.includes(body.stage)) router.refresh();
    }, 5000);
    return () => clearInterval(timer);
  }, [runId, stage, terminal, router]);

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
    </ol>
  );
}
