import Link from "next/link";
import { redirect } from "next/navigation";

import { ErrorState } from "@/components/ui";
import { apiGet, backendMode, type Schemas } from "@/lib/api-server";
import { can } from "@/lib/roles";

import { LogoutButton } from "./LogoutButton";

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
        <a href="" className="inline-block rounded border border-line bg-surface px-3 py-1">
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
      <header className="border-b border-line bg-surface">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center gap-6 px-4 py-3">
          <Link href="/console" className="font-semibold">
            Project Intelligence
          </Link>
          <nav aria-label="Console" className="flex flex-wrap gap-4">
            {nav
              .filter((item) => item.show)
              .map((item) => (
                <Link key={item.href} href={item.href} className="text-ink-muted hover:text-ink">
                  {item.label}
                </Link>
              ))}
          </nav>
          <div className="ml-auto flex items-center gap-3">
            <span className="text-ink-muted" data-testid="signed-in-user">
              {user.display_name} · {user.roles.join(", ")}
            </span>
            <LogoutButton />
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-7xl px-4 py-6">{children}</main>
    </div>
  );
}
