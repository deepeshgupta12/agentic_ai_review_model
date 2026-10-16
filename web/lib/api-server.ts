import "server-only";

import { cookies } from "next/headers";
import { cache } from "react";

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

const BUSY = "The server did not answer in time; it may be busy with a run. Refresh the page in a moment.";
const ATTEMPT_MS = 15_000;
const BACKOFF_MS = [1_000, 3_000];

/** One GET to the backend, tried up to three times (waiting 1 s, then 3 s) with its own timeout per attempt. The
 * timeout signal also keeps Next from handing the first attempt's failure to the retries (it memoizes identical
 * fetches, failures included); React's cache shares one answer between a page and its layout in the same render
 * (audit, 14 Oct 2026). */
const getOnce = cache(async (url: string, cookie: string): Promise<ApiResult<unknown>> => {
  for (let attempt = 0; attempt <= BACKOFF_MS.length; attempt++) {
    try {
      const response = await fetch(url, {
        headers: cookie ? { cookie, accept: "application/json" } : { accept: "application/json" },
        cache: "no-store",
        signal: AbortSignal.timeout(ATTEMPT_MS),
      });
      return await read<unknown>(response);
    } catch {
      if (attempt < BACKOFF_MS.length) await new Promise((resolve) => setTimeout(resolve, BACKOFF_MS[attempt]));
    }
  }
  return { status: 503, data: null, error: BUSY, requestId: null };
});

/** GET from the backend as the signed-in user (the session cookie is forwarded). Never cached across requests. */
export async function apiGet<T>(path: string, query?: Query): Promise<ApiResult<T>> {
  const cookieStore = await cookies();
  const cookieHeader = cookieStore
    .getAll()
    .map((c) => `${c.name}=${encodeURIComponent(c.value)}`)
    .join("; ");
  return (await getOnce(`${API}${withQuery(path, query)}`, cookieHeader)) as ApiResult<T>;
}

/** Every item of a paged list (the API pages at most 100), following next_cursor up to `pages` pages. */
export async function apiGetAll<T>(
  path: string,
  query?: Query,
  pages = 10,
): Promise<ApiResult<{ items: T[]; truncated: boolean }>> {
  const items: T[] = [];
  let cursor: string | null = null;
  for (let page = 0; page < pages; page++) {
    const result: ApiResult<{ items: T[]; next_cursor: string | null }> = await apiGet(path, { ...query, limit: 100, cursor });
    if (!result.data) return { ...result, data: null };
    items.push(...result.data.items);
    cursor = result.data.next_cursor;
    if (!cursor) break;
  }
  // `truncated` says there were more than `pages` pages, so a screen can say it shows only the first ones
  return { status: 200, data: { items, truncated: cursor !== null }, error: null, requestId: null };
}

/** Public, cookie-free GET (the public project page). */
export async function apiGetPublic<T>(path: string): Promise<ApiResult<T>> {
  return (await getOnce(`${API}${path}`, "")) as ApiResult<T>;
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
  const fallback = { analysis_mode: "reviews", page_reviews_max: 20, review_words_min: 20, review_words_max: 80 };
  const result = (await getOnce(`${API}/healthz`, "")) as ApiResult<Partial<BackendInfo>>;
  if (!result.data) return { ...fallback, mode: "unreachable" };
  return { ...fallback, ...result.data, mode: result.data.mode ?? "unknown" };
}

export async function backendMode(): Promise<string> {
  return (await backendInfo()).mode;
}

/** The signed-in user (the console layout guarantees one). */
export async function currentUser(): Promise<Schemas["UserView"] | null> {
  const me = await apiGet<Schemas["UserView"]>("/v1/auth/me");
  return me.data;
}
