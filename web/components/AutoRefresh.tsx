"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState, useTransition } from "react";

/** Re-render the page from the server while something it shows is still changing (a run that collects or reads
 * reviews), so its numbers move live. The next refresh starts only after the previous one finished, never while the
 * tab is hidden, and not at all once nothing is working (audit, 14 Oct 2026: refreshes piled up on a busy server). */
export function AutoRefresh({ active, seconds = 5 }: { active: boolean; seconds?: number }) {
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  const [visible, setVisible] = useState(() => typeof document === "undefined" || !document.hidden);

  useEffect(() => {
    const update = () => setVisible(!document.hidden);
    document.addEventListener("visibilitychange", update);
    return () => document.removeEventListener("visibilitychange", update);
  }, []);

  useEffect(() => {
    if (!active || pending || !visible) return;
    const timer = setTimeout(() => startTransition(() => router.refresh()), seconds * 1000);
    return () => clearTimeout(timer);
  }, [active, pending, visible, seconds, router]);

  return active ? (
    <span role="status" className="inline-flex items-center gap-1.5 rounded-full bg-ok-soft px-2.5 py-1 text-xs font-medium text-ok ring-1 ring-inset ring-ok/20" data-testid="live">
      <span aria-hidden="true" className="relative inline-flex h-2 w-2">
        <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-ok opacity-60" />
        <span className="relative inline-flex h-2 w-2 rounded-full bg-ok" />
      </span>
      updating live
    </span>
  ) : null;
}
