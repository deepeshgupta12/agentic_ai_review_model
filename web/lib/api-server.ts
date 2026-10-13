import "server-only";

import { cookies } from "next/headers";

import type { components } from "./api-schema";

export type Schemas = components["schemas"];

const API = process.env.API_INTERNAL_URL ?? "http://localhost:8000";

export type ApiResult<T> = { status: number; data: T | null; error: string | null; requestId: string | null };

type Query = Record<string, string | number | null | undefined>;

/** Path plus the query parameters that have a value. */
export function withQuery(path: string, query?: Query): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query ?? {})) {
    if (value !== null && value !== undefined && value !== "") {
      params.set(key, String(value));
    }
  }
  const text = params.toString();
  return text ? `${path}?${text}` : path;
}

async function read<T>(response: Response): Promise<ApiResult<T>> {
  const text = await response.text();
  let body: unknown = null;
  try {
    body = text ? JSON.parse(text) : null;
  } catch {
    body = null;
  }
  if (response.ok) {
    return { status: response.status, data: body as T, error: null, requestId: null };
  }
  const envelope = (body as { error?: { message?: string; request_id?: string } } | null)?.error;
  return {
    status: response.status,
    data: null,
    error: envelope?.message ?? `Request failed (${response.status})`,
    requestId: envelope?.request_id ?? null,
  };
}

/** GET from the backend as the signed-in user (the session cookie is forwarded). Never cached. */
export async function apiGet<T>(path: string, query?: Query): Promise<ApiResult<T>> {
  const cookieStore = await cookies();
  const cookieHeader = cookieStore
    .getAll()
    .map((c) => `${c.name}=${encodeURIComponent(c.value)}`)
    .join("; ");
  try {
    const response = await fetch(`${API}${withQuery(path, query)}`, {
      headers: { cookie: cookieHeader, accept: "application/json" },
      cache: "no-store",
    });
    return read<T>(response);
  } catch {
    return { status: 503, data: null, error: "The backend is unreachable", requestId: null };
  }
}

/** Public, cookie-free GET (the public project page). */
export async function apiGetPublic<T>(path: string): Promise<ApiResult<T>> {
  try {
    const response = await fetch(`${API}${path}`, { headers: { accept: "application/json" }, cache: "no-store" });
    return read<T>(response);
  } catch {
    return { status: 503, data: null, error: "The backend is unreachable", requestId: null };
  }
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

/** The signed-in user (the console layout guarantees one). */
export async function currentUser(): Promise<Schemas["UserView"] | null> {
  const me = await apiGet<Schemas["UserView"]>("/v1/auth/me");
  return me.data;
}
