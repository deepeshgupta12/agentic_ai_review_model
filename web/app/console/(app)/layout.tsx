import Link from "next/link";
import { redirect } from "next/navigation";

import { apiGet, backendMode, type Schemas } from "@/lib/api-server";

import { LogoutButton } from "./LogoutButton";

const NAV = [
  { href: "/console", label: "Portfolio" },
  { href: "/console/operations", label: "Operations" },
];

export default async function ConsoleLayout({ children }: { children: React.ReactNode }) {
  const me = await apiGet<Schemas["UserView"]>("/v1/auth/me");
  if (me.status === 401 || !me.data) {
    redirect("/console/login");
  }
  const mode = await backendMode();
  const user = me.data;

  return (
    <div className="min-h-screen bg-surface-sunken">
      {mode !== "live" ? (
        <div role="status" className="bg-fixture px-4 py-1 text-center text-xs font-medium text-white">
          {mode === "fixture" ? "Fixture mode: sample data only; nothing can be published" : `Backend ${mode}`}
        </div>
      ) : null}
      <header className="border-b border-line bg-surface">
        <div className="mx-auto flex max-w-6xl items-center gap-6 px-4 py-3">
          <span className="font-semibold">Project Intelligence</span>
          <nav aria-label="Console" className="flex gap-4">
            {NAV.map((item) => (
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
      <main className="mx-auto max-w-6xl px-4 py-6">{children}</main>
    </div>
  );
}
