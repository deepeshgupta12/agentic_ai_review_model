import type { Metadata } from "next";

import { Icon } from "@/components/icons";
import { safeNextPath } from "@/lib/paths";

import { LoginForm } from "./LoginForm";

export const metadata: Metadata = { title: "Sign in" };

export default async function LoginPage({ searchParams }: { searchParams: Promise<{ next?: string }> }) {
  const { next } = await searchParams;
  return (
    <main className="flex min-h-screen items-center justify-center bg-shell bg-[radial-gradient(ellipse_at_top,rgb(20_184_166/0.25),transparent_60%)] px-4">
      <section className="w-full max-w-sm rounded-xl border border-line bg-surface p-7 shadow-lift">
        <span
          aria-hidden="true"
          className="mb-4 inline-flex h-10 w-10 items-center justify-center rounded-xl bg-linear-to-br from-teal-400 to-emerald-600 text-white"
        >
          <Icon name="quote" className="h-5 w-5" strokeWidth={2.2} />
        </span>
        <h1 className="mb-1 text-xl font-semibold tracking-tight">Project Intelligence console</h1>
        <p className="mb-6 text-ink-muted">Sign in with your console account.</p>
        <LoginForm next={safeNextPath(next)} />
      </section>
    </main>
  );
}
