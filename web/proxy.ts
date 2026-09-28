import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

// Optimistic check only: no session cookie means go to login. The console layout
// verifies the session with the backend on every request (docs/03).
export function proxy(request: NextRequest) {
  if (request.nextUrl.pathname.startsWith("/console/login")) {
    return NextResponse.next();
  }
  if (!request.cookies.has("sy_session")) {
    const login = new URL("/console/login", request.url);
    login.searchParams.set("next", request.nextUrl.pathname);
    return NextResponse.redirect(login);
  }
  return NextResponse.next();
}

export const config = {
  matcher: ["/console/:path*"],
};
