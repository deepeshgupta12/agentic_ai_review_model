import Link from "next/link";
import { redirect } from "next/navigation";

import { Icon } from "@/components/icons";
import { BUTTON, ErrorState } from "@/components/ui";
import { apiGet, backendMode, type Schemas } from "@/lib/api-server";
import { can } from "@/lib/roles";

import { ConsoleNav } from "./ConsoleNav";
import { LogoutButton } from "./LogoutButton";

function initials(name: string): string {
  const words = name.split(/[\s._@-]+/).filter(Boolean);
  return ((words[0]?.[0] ?? "") + (words[1]?.[0] ?? "")).toUpperCase() || "?";
}

export default async function ConsoleLayout({ children }: { children: React.ReactNode }) {
  const me = await apiGet<Schemas["UserView"]>("/v1/auth/me");
  if (me.status === 401) {
    redirect("/console/login");
  }
  if (!me.data) {
    // the server did not answer (busy or restarting): say so, never sign the person out (audit, 14 Oct 2026)
    return (
      <main className="mx-auto max-w-3xl space-y-3 px-4 py-10">
        <ErrorState status={me.status} error={me.error} requestId={me.requestId} />
        <a href="" className={BUTTON.secondary}>
          Try again
        </a>
      </main>
    );
  }
  const mode = await backendMode();
  const user = me.data;
  const nav = [
    { href: "/console", label: "Portfolio", show: true },
    { href: "/console/corrections", label: "Corrections", show: can(user.roles, "listCorrections") },
    { href: "/console/operations", label: "Operations", show: true },
    { href: "/console/admin", label: "Administration", show: can(user.roles, "listSourcePolicies") || can(user.roles, "listUsers") },
  ];

  return (
    <div className="min-h-screen bg-surface-sunken">
      {mode !== "live" ? (
        <div role="status" className="bg-fixture px-4 py-1 text-center text-xs font-medium text-white">
          {mode === "fixture" ? "Fixture mode: development stack; fixture data never publishes" : `Backend ${mode}`}
        </div>
      ) : null}
      <header className="sticky top-0 z-30 border-b border-shell-line bg-shell/95 backdrop-blur supports-[backdrop-filter]:bg-shell/85">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center gap-x-6 gap-y-2 px-4 py-2.5">
          <Link href="/console" className="flex items-center gap-2.5 text-white">
            <span
              aria-hidden="true"
              className="inline-flex h-8 w-8 items-center justify-center rounded-lg bg-linear-to-br from-teal-400 to-emerald-600 text-white shadow-[0_0_0_1px_rgb(255_255_255/0.12)]"
            >
              <Icon name="quote" className="h-4 w-4" strokeWidth={2.2} />
            </span>
            <span className="leading-tight">
              <span className="block text-[14px] font-semibold tracking-tight">Project Intelligence</span>
              <span className="block text-[11px] text-slate-400">Reviews console</span>
            </span>
          </Link>
          <ConsoleNav items={nav.filter((item) => item.show).map(({ href, label }) => ({ href, label }))} />
          <div className="ml-auto flex items-center gap-3">
            <span className="flex items-center gap-2 text-[13px] text-slate-300" data-testid="signed-in-user">
              <span aria-hidden="true" className="inline-flex h-7 w-7 items-center justify-center rounded-full bg-teal-500/20 text-[11px] font-semibold text-teal-200 ring-1 ring-teal-400/30">
                {initials(user.display_name)}
              </span>
              <span>
                {user.display_name} <span className="text-slate-500">·</span> <span className="text-slate-400">{user.roles.join(", ")}</span>
              </span>
            </span>
            <LogoutButton />
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-7xl px-4 py-8">{children}</main>
    </div>
  );
}
