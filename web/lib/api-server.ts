import "server-only";

import { cookies } from "next/headers";

import type { components } from "./api-schema";

export type Schemas = components["schemas"];

const API = process.env.API_INTERNAL_URL ?? "http://localhost:8000";

export type ApiResult<T> = { status: number; data: T | null };

/** GET from the backend as the signed-in user (the session cookie is forwarded). Never cached. */
export async function apiGet<T>(path: string): Promise<ApiResult<T>> {
  const cookieStore = await cookies();
  const cookieHeader = cookieStore
    .getAll()
    .map((c) => `${c.name}=${encodeURIComponent(c.value)}`)
    .join("; ");
  const response = await fetch(`${API}${path}`, {
    headers: { cookie: cookieHeader, accept: "application/json" },
    cache: "no-store",
  });
  const data = response.ok ? ((await response.json()) as T) : null;
  return { status: response.status, data };
}

/** Public, cookie-free GET (the public project page). */
export async function apiGetPublic<T>(path: string): Promise<ApiResult<T>> {
  const response = await fetch(`${API}${path}`, { headers: { accept: "application/json" }, cache: "no-store" });
  const data = response.ok ? ((await response.json()) as T) : null;
  return { status: response.status, data };
}

export async function backendMode(): Promise<string> {
  try {
    const response = await fetch(`${API}/healthz`, { cache: "no-store" });
    const body = (await response.json()) as { mode?: string };
    return body.mode ?? "unknown";
  } catch {
    return "unreachable";
  }
}
