"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

// The flow first (D68, D69): run, decide the reviews, build the page, publish. The rest is for checking and setup.
const FLOW = [
  ["runs", "Runs"],
  ["reviews", "Reviews"],
  ["content", "Page"],
  ["publishing", "Publishing"],
] as const;
const MORE = [
  ["evidence", "Sources"],
  ["videos", "Videos"],
  ["findings", "Findings"],
  ["setup", "Setup"],
] as const;

export function ProjectTabs({
  projectId,
  counts,
  showFindings,
}: {
  projectId: string;
  counts: Partial<Record<string, number>>;
  showFindings: boolean;
}) {
  const path = usePathname();
  const tab = ([slug, label]: readonly [string, string]) => {
    const href = `/console/projects/${projectId}/${slug}`;
    const active = path.startsWith(href);
    const count = counts[slug];
    return (
      <Link
        key={slug}
        href={href}
        aria-current={active ? "page" : undefined}
        className={`inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-[13px] font-medium transition ${
          active ? "bg-surface text-ink shadow-card ring-1 ring-line" : "text-ink-muted hover:bg-surface/70 hover:text-ink"
        }`}
      >
        {label}
        {count ? (
          <span className="inline-flex min-w-5 items-center justify-center rounded-full bg-warn px-1.5 text-[11px] font-semibold leading-[18px] text-white">
            {count}
            <span className="sr-only"> waiting</span>
          </span>
        ) : null}
      </Link>
    );
  };
  return (
    <nav aria-label="Project" className="mb-6 flex flex-wrap items-center gap-1 rounded-lg bg-idle-soft/80 p-1 ring-1 ring-inset ring-line">
      {FLOW.map(tab)}
      <span aria-hidden="true" className="mx-1.5 h-5 border-l border-line-strong" />
      {MORE.filter(([slug]) => slug !== "findings" || showFindings).map(tab)}
    </nav>
  );
}
