"use client";

import { useRouter } from "next/navigation";

import { postJson } from "@/lib/api-browser";

export function LogoutButton() {
  const router = useRouter();
  return (
    <button
      type="button"
      className="rounded-md border border-white/15 px-2.5 py-1 text-[13px] text-slate-300 transition hover:border-white/30 hover:bg-white/6 hover:text-white"
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
