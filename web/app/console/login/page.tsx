import type { Metadata } from "next";

import { safeNextPath } from "@/lib/paths";

import { LoginForm } from "./LoginForm";

export const metadata: Metadata = { title: "Sign in" };

export default async function LoginPage({ searchParams }: { searchParams: Promise<{ next?: string }> }) {
  const { next } = await searchParams;
  return (
    <main className="flex min-h-screen items-center justify-center bg-surface-sunken px-4">
      <section className="w-full max-w-sm rounded-lg border border-line bg-surface p-6">
        <h1 className="mb-1 text-lg font-semibold">Project Intelligence console</h1>
        <p className="mb-6 text-ink-muted">Sign in with your console account.</p>
        <LoginForm next={safeNextPath(next)} />
      </section>
    </main>
  );
}
