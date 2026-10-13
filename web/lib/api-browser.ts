import { errorMessage, readCookie } from "./paths";

export type BrowserResult<T> = {
  ok: boolean;
  status: number;
  data: T | null;
  message: string | null;
  code: string | null;
  currentVersion: number | null;
};

type Options = { idempotent?: boolean; idempotencyKey?: string };

/** A fresh Idempotency-Key for one user action (a retry of the same action reuses it). */
export function newKey(prefix = "ui"): string {
  const random = typeof crypto !== "undefined" && "randomUUID" in crypto ? crypto.randomUUID() : String(Date.now());
  return `${prefix}-${random}`;
}

/** A mutation through the same-origin /v1 proxy, with the session's CSRF token (docs/03). */
export async function send<T>(method: "POST" | "PATCH", path: string, body?: unknown, options: Options = {}): Promise<BrowserResult<T>> {
  const csrf = readCookie(document.cookie, "sy_csrf");
  const headers: Record<string, string> = { "content-type": "application/json" };
  if (csrf) headers["X-CSRF-Token"] = csrf;
  if (options.idempotent || options.idempotencyKey) headers["Idempotency-Key"] = options.idempotencyKey ?? newKey();
  let response: Response;
  try {
    response = await fetch(path, {
      method,
      credentials: "same-origin",
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    return { ok: false, status: 0, data: null, message: "The server could not be reached", code: null, currentVersion: null };
  }
  const text = await response.text();
  let parsed: unknown = null;
  try {
    parsed = text ? JSON.parse(text) : null;
  } catch {
    parsed = null;
  }
  const error = (parsed as { error?: { code?: string; current_version?: number; fields?: { path: string; message: string }[] } } | null)?.error;
  const fieldNotes = (error?.fields ?? []).map((f) => `${f.path}: ${f.message}`).join("; ");
  const base = errorMessage(parsed, `Request failed (${response.status})`);
  return {
    ok: response.ok,
    status: response.status,
    data: response.ok ? (parsed as T) : null,
    message: response.ok ? null : fieldNotes && !base.includes(fieldNotes) ? `${base} (${fieldNotes})` : base,
    code: response.ok ? null : (error?.code ?? null),
    currentVersion: error?.current_version ?? null,
  };
}

/** POST through the same-origin /v1 proxy (kept for the sign-in and sign-out forms). */
export async function postJson<T>(path: string, body?: unknown): Promise<BrowserResult<T>> {
  return send<T>("POST", path, body);
}
