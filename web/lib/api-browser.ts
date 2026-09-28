import { errorMessage, readCookie } from "./paths";

export type BrowserResult<T> = { ok: boolean; status: number; data: T | null; message: string | null };

/** POST to the same-origin /v1 proxy with the session's CSRF token (docs/03). */
export async function postJson<T>(path: string, body?: unknown): Promise<BrowserResult<T>> {
  const csrf = readCookie(document.cookie, "sy_csrf");
  const response = await fetch(path, {
    method: "POST",
    credentials: "same-origin",
    headers: {
      "content-type": "application/json",
      ...(csrf ? { "X-CSRF-Token": csrf } : {}),
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const text = await response.text();
  const parsed: unknown = text ? JSON.parse(text) : null;
  return {
    ok: response.ok,
    status: response.status,
    data: response.ok ? (parsed as T) : null,
    message: response.ok ? null : errorMessage(parsed, `Request failed (${response.status})`),
  };
}
