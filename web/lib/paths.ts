/** Only console paths are allowed as post-login destinations, so a crafted link cannot redirect off-site. */
export function safeNextPath(value: string | null | undefined): string {
  if (!value || !value.startsWith("/console") || value.startsWith("//") || value.includes("\\")) {
    return "/console";
  }
  if (value.startsWith("/console/login")) {
    return "/console";
  }
  return value;
}

/** Read one cookie from a document.cookie-style string. */
export function readCookie(cookieHeader: string, name: string): string | null {
  for (const part of cookieHeader.split(";")) {
    const [key, ...rest] = part.trim().split("=");
    if (key === name) {
      return decodeURIComponent(rest.join("="));
    }
  }
  return null;
}

/** Safe message from the contract error envelope, or a fallback. */
export function errorMessage(body: unknown, fallback: string): string {
  if (body && typeof body === "object" && "error" in body) {
    const error = (body as { error?: { message?: unknown } }).error;
    if (error && typeof error.message === "string" && error.message.length > 0) {
      return error.message;
    }
  }
  return fallback;
}
