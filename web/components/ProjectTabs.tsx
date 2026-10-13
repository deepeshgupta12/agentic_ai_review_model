"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const TABS = [
  ["setup", "Setup"],
  ["runs", "Runs"],
  ["evidence", "Evidence"],
  ["videos", "Videos"],
  ["findings", "Findings"],
  ["reviews", "Reviews"],
  ["content", "Content"],
  ["publishing", "Publishing"],
] as const;

export function ProjectTabs({ projectId, counts }: { projectId: string; counts: Partial<Record<string, number>> }) {
  const path = usePathname();
  return (
    <nav aria-label="Project" className="mb-5 flex flex-wrap gap-1 border-b border-line">
      {TABS.map(([slug, label]) => {
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
      })}
    </nav>
  );
}
