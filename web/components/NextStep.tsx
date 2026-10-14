import Link from "next/link";

import { type NextStep, STEPS } from "@/lib/flow";

const TONE = {
  todo: "border-accent",
  wait: "border-line",
  done: "border-ok",
  stop: "border-warn",
};

/** The project's place in the flow (run, approve reviews, build the page, approve and publish) and the one thing to
 * do next. The backend still checks every action; this only points the way. */
export function NextStepBanner({ next }: { next: NextStep }) {
  return (
    <section aria-label="Next step" data-testid="next-step" className={`mb-4 rounded-lg border-l-4 bg-surface p-3 ${TONE[next.tone]}`}>
      <ol className="mb-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-ink-muted" aria-label="Steps">
        {STEPS.map((step, index) => {
          const number = index + 1;
          const state = number < next.step || next.tone === "done" ? "done" : number === next.step ? "current" : "later";
          return (
            <li key={step} aria-current={state === "current" ? "step" : undefined} className={state === "current" ? "font-semibold text-ink" : ""}>
              {state === "done" ? "✓" : `${number}.`} {step}
            </li>
          );
        })}
      </ol>
      <div className="flex flex-wrap items-center gap-3">
        <div className="min-w-0 flex-1">
          <p className="font-medium">{next.title}</p>
          {next.detail ? <p className="text-ink-muted">{next.detail}</p> : null}
        </div>
        <Link
          href={next.href}
          target={next.href.startsWith("/projects/") ? "_blank" : undefined}
          className={`rounded px-3 py-1.5 font-medium ${next.tone === "todo" ? "bg-accent text-white" : "border border-line"}`}
        >
          {next.action}
        </Link>
      </div>
    </section>
  );
}
