import Link from "next/link";

import { Icon } from "@/components/icons";
import { BUTTON } from "@/components/ui";
import { type NextStep, STEPS } from "@/lib/flow";

const TONE = {
  todo: { ring: "border-accent/30", band: "bg-accent", label: "Your next step", text: "text-accent" },
  wait: { ring: "border-info/25", band: "bg-info", label: "Working", text: "text-info" },
  done: { ring: "border-ok/30", band: "bg-ok", label: "Done", text: "text-ok" },
  stop: { ring: "border-warn/30", band: "bg-warn", label: "Needs attention", text: "text-warn" },
};

type State = "done" | "current" | "later";

/** The four steps as a row of numbered circles joined by lines. */
export function FlowSteps({ next, compact = false }: { next: NextStep; compact?: boolean }) {
  const state = (number: number): State => (number < next.step || next.tone === "done" ? "done" : number === next.step ? "current" : "later");
  return (
    <ol className="flex items-start" aria-label="Steps">
      {STEPS.map((step, index) => {
        const number = index + 1;
        const s = state(number);
        const circle =
          s === "done"
            ? "bg-ok text-white"
            : s === "current"
              ? next.tone === "wait"
                ? "bg-info text-white ring-4 ring-info/15"
                : next.tone === "stop"
                  ? "bg-warn text-white ring-4 ring-warn/15"
                  : "bg-accent text-white ring-4 ring-accent/15"
              : "bg-surface text-ink-muted ring-1 ring-line-strong";
        return (
          <li
            key={step}
            aria-current={s === "current" ? "step" : undefined}
            className={`relative flex flex-1 flex-col items-center text-center ${compact ? "gap-1" : "gap-1.5"}`}
          >
            {index > 0 ? (
              <span
                aria-hidden="true"
                className={`absolute -left-1/2 h-0.5 w-full -translate-y-1/2 ${compact ? "top-2.5" : "top-3.5"} ${s === "later" ? "bg-line" : "bg-ok/60"}`}
              />
            ) : null}
            <span
              className={`relative z-10 inline-flex items-center justify-center rounded-full font-semibold ${compact ? "h-5 w-5 text-[10px]" : "h-7 w-7 text-xs"} ${circle}`}
            >
              {s === "done" ? <Icon name="check" className={compact ? "h-3 w-3" : "h-3.5 w-3.5"} strokeWidth={3} /> : number}
              {s === "current" && next.tone === "wait" ? (
                <span aria-hidden="true" className="absolute inset-0 animate-ping rounded-full bg-info/30" />
              ) : null}
            </span>
            <span className={`${compact ? "text-[11px]" : "text-xs"} leading-tight ${s === "current" ? "font-semibold text-ink" : s === "done" ? "text-ink" : "text-ink-muted"}`}>
              {step}
            </span>
          </li>
        );
      })}
    </ol>
  );
}

/** The project's place in the flow (run, approve reviews, build the page, approve and publish) and the one thing to
 * do next. The backend still checks every action; this only points the way. */
export function NextStepBanner({ next }: { next: NextStep }) {
  const tone = TONE[next.tone];
  const external = next.href.startsWith("/projects/");
  return (
    <section aria-label="Next step" data-testid="next-step" className={`mb-5 overflow-hidden rounded-lg border bg-surface shadow-card ${tone.ring}`}>
      <div className={`h-1 ${tone.band}`} aria-hidden="true" />
      <div className="grid gap-5 p-5 lg:grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)] lg:items-center">
        <div className="min-w-0">
          <p className={`text-[11px] font-semibold uppercase tracking-wider ${tone.text}`}>
            {tone.label} · step {next.step} of {STEPS.length}
          </p>
          <p className="mt-1 text-lg font-semibold tracking-tight">{next.title}</p>
          {next.detail ? <p className="mt-0.5 text-ink-muted">{next.detail}</p> : null}
          <Link href={next.href} target={external ? "_blank" : undefined} className={`mt-3 ${next.tone === "todo" ? BUTTON.primary : BUTTON.secondary}`}>
            {next.action}
            <Icon name={external ? "external" : "arrow"} />
          </Link>
        </div>
        <FlowSteps next={next} />
      </div>
    </section>
  );
}
