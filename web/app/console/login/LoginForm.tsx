"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { postJson } from "@/lib/api-browser";

export function LoginForm({ next }: { next: string }) {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    const form = new FormData(event.currentTarget);
    const result = await postJson("/v1/auth/login", { email: form.get("email"), password: form.get("password") });
    setBusy(false);
    if (!result.ok) {
      setError(result.message);
      return;
    }
    router.replace(next);
    router.refresh();
  }

  return (
    <form onSubmit={onSubmit} className="space-y-4" noValidate>
      <label className="block">
        <span className="mb-1 block text-ink-muted">Email</span>
        <input name="email" type="email" autoComplete="username" required className="w-full rounded border border-line-strong px-3 py-2" />
      </label>
      <label className="block">
        <span className="mb-1 block text-ink-muted">Password</span>
        <input name="password" type="password" autoComplete="current-password" required className="w-full rounded border border-line-strong px-3 py-2" />
      </label>
      {error ? (
        <p role="alert" className="text-danger">
          {error}
        </p>
      ) : null}
      <button type="submit" disabled={busy} className="w-full rounded bg-accent px-3 py-2.5 font-medium text-white shadow-sm transition hover:bg-accent-strong disabled:opacity-60">
        {busy ? "Signing in…" : "Sign in"}
      </button>
    </form>
  );
}
