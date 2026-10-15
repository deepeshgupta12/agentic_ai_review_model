"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

/** The console's sections, the current one marked. Project and run screens belong to the portfolio. */
export function ConsoleNav({ items }: { items: { href: string; label: string }[] }) {
  const path = usePathname();
  const current = (href: string) =>
    href === "/console" ? path === "/console" || path.startsWith("/console/projects") || path.startsWith("/console/runs") : path.startsWith(href);
  return (
    <nav aria-label="Console" className="flex flex-wrap gap-1">
      {items.map((item) => {
        const active = current(item.href);
        return (
          <Link
            key={item.href}
            href={item.href}
            aria-current={active ? "page" : undefined}
            className={`rounded-md px-3 py-1.5 text-[13px] font-medium transition ${
              active ? "bg-white/12 text-white shadow-[inset_0_0_0_1px_rgb(255_255_255/0.08)]" : "text-slate-400 hover:bg-white/6 hover:text-white"
            }`}
          >
            {item.label}
          </Link>
        );
      })}
    </nav>
  );
}
