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
        className={`-mb-px border-b-2 px-3 py-2 ${active ? "border-accent font-medium text-ink" : "border-transparent text-ink-muted hover:text-ink"}`}
      >
        {label}
        {count ? <span className="ml-1 rounded bg-warn px-1 text-xs text-white">{count}</span> : null}
      </Link>
    );
  };
  return (
    <nav aria-label="Project" className="mb-5 flex flex-wrap items-end gap-1 border-b border-line">
      {FLOW.map(tab)}
      <span aria-hidden="true" className="mx-2 mb-2 h-5 border-l border-line" />
      {MORE.filter(([slug]) => slug !== "findings" || showFindings).map(tab)}
    </nav>
  );
}
