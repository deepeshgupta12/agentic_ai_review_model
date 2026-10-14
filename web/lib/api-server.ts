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

/** Every item of a paged list (the API pages at most 100), following next_cursor up to `pages` pages. */
export async function apiGetAll<T>(path: string, query?: Query, pages = 10): Promise<ApiResult<{ items: T[] }>> {
  const items: T[] = [];
  let cursor: string | null = null;
  for (let page = 0; page < pages; page++) {
    const result: ApiResult<{ items: T[]; next_cursor: string | null }> = await apiGet(path, { ...query, limit: 100, cursor });
    if (!result.data) return { ...result, data: null };
    items.push(...result.data.items);
    cursor = result.data.next_cursor;
    if (!cursor) break;
  }
  return { status: 200, data: { items }, error: null, requestId: null };
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

export type BackendInfo = {
  mode: string;
  /** "reviews" (default, D68) or "full" (claims and findings as well). */
  analysis_mode: string;
  page_reviews_max: number;
  review_words_min: number;
  review_words_max: number;
};

/** The backend's mode and the page's review limits (D69), read from /healthz so the console never copies them. */
export async function backendInfo(): Promise<BackendInfo> {
  const fallback = { analysis_mode: "reviews", page_reviews_max: 20, review_words_min: 30, review_words_max: 80 };
  try {
    const response = await fetch(`${API}/healthz`, { cache: "no-store" });
    const body = (await response.json()) as Partial<BackendInfo>;
    return { ...fallback, ...body, mode: body.mode ?? "unknown" };
  } catch {
    return { ...fallback, mode: "unreachable" };
  }
}

export async function backendMode(): Promise<string> {
  return (await backendInfo()).mode;
}

/** The signed-in user (the console layout guarantees one). */
export async function currentUser(): Promise<Schemas["UserView"] | null> {
  const me = await apiGet<Schemas["UserView"]>("/v1/auth/me");
  return me.data;
}
