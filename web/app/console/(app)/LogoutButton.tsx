"use client";

import { useRouter } from "next/navigation";

import { postJson } from "@/lib/api-browser";

export function LogoutButton() {
  const router = useRouter();
  return (
    <button
      type="button"
      className="rounded border border-line px-2 py-1 text-ink-muted hover:text-ink"
      onClick={async () => {
        await postJson("/v1/auth/logout");
        router.replace("/console/login");
        router.refresh();
      }}
    >
      Sign out
    </button>
  );
}
