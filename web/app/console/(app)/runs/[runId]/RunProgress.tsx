import { Icon } from "@/components/icons";
import { STOPPED, runIsWorking } from "@/lib/format";

// A run's stages as people follow them (contracts/v1/state_machines.json workflow_stage, in order).
const STEPS = [
  { label: "Collect", stages: ["collecting"] },
  { label: "Read reviews", stages: ["analysing"] },
  { label: "Decide reviews", stages: ["findings_review"] },
  { label: "Build the page", stages: ["formatting"] },
  { label: "Approve the page", stages: ["final_review"] },
  { label: "Publish", stages: ["approved", "publishing", "published"] },
];

type Run = { stage: string; outcome_note: string | null; content_revision_id: string | null; updated_at: string };

type State = "done" | "working" | "waiting" | "stopped" | "later" | "skipped";

/** The run's stages as a stepper: done, the current one (working, waiting for a person, or stopped) and the rest.
 * A run that ended early (nothing usable found, cancelled) says so at the step it reached. While the system works the
 * page refreshes itself (AutoRefresh on the run page). */
export function RunProgress({ run }: { run: Run }) {
  const stage = run.stage;
  const working = runIsWorking(run);
  const stopped = STOPPED.test(run.outcome_note ?? "");
  // insufficient evidence ends after reading; a cancelled run shows no step as reached
  const at = stage === "insufficient_evidence" ? 1 : STEPS.findIndex((s) => s.stages.includes(stage));
  const state = (index: number): State => {
    if (stage === "published") return "done";
    if (stage === "cancelled") return "later";
    if (index < at) return "done";
    if (index > at) return stage === "insufficient_evidence" ? "skipped" : "later";
    if (stage === "insufficient_evidence" || stopped) return "stopped";
    return working ? "working" : "waiting";
  };
  const circle: Record<State, string> = {
    done: "bg-ok text-white",
    working: "bg-info text-white ring-4 ring-info/15",
    waiting: "bg-accent text-white ring-4 ring-accent/15",
    stopped: "bg-warn text-white ring-4 ring-warn/15",
    later: "bg-surface text-ink-muted ring-1 ring-line-strong",
    skipped: "bg-surface-sunken text-ink-muted/60 ring-1 ring-line",
  };
  const caption: Partial<Record<State, string>> = {
    working: "in progress",
    waiting: "waiting for you",
    stopped: stage === "insufficient_evidence" ? "nothing usable" : "stopped",
  };
  return (
    <ol className="flex items-start" aria-label="Stages">
      {STEPS.map((step, index) => {
        const s = state(index);
        return (
          <li
            key={step.label}
            aria-current={s === "working" || s === "waiting" || s === "stopped" ? "step" : undefined}
            className="relative flex flex-1 flex-col items-center gap-1.5 text-center"
          >
            {index > 0 ? (
              <span
                aria-hidden="true"
                className={`absolute top-4 -left-1/2 h-0.5 w-full -translate-y-1/2 ${s === "later" || s === "skipped" ? "bg-line" : "bg-ok/60"}`}
              />
            ) : null}
            <span className={`relative z-10 inline-flex h-8 w-8 items-center justify-center rounded-full text-xs font-semibold ${circle[s]}`}>
              {s === "done" ? (
                <Icon name="check" className="h-4 w-4" strokeWidth={3} />
              ) : s === "stopped" ? (
                <Icon name="stop" className="h-4 w-4" strokeWidth={2.4} />
              ) : (
                index + 1
              )}
              {s === "working" ? <span aria-hidden="true" className="absolute inset-0 animate-ping rounded-full bg-info/30" /> : null}
            </span>
            <span className={`text-xs leading-tight ${s === "later" || s === "skipped" ? "text-ink-muted" : "font-medium text-ink"}`}>{step.label}</span>
            {caption[s] ? (
              <span className={`text-[11px] ${s === "working" ? "text-info" : s === "stopped" ? "text-warn" : "text-accent"}`}>{caption[s]}</span>
            ) : null}
          </li>
        );
      })}
    </ol>
  );
}
