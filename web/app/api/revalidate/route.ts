import { createHmac, timingSafeEqual } from "node:crypto";

import { revalidatePath } from "next/cache";
import { NextResponse } from "next/server";

// Signed revalidation route (docs/09): called only by the backend's delivery worker. The body is
// {slug, revision_id}; X-Revalidate-Signature is the hex HMAC-SHA256 of the raw body with REVALIDATION_SECRET.
// An acknowledgement is not proof of delivery: the worker then reads the page's markers.
export async function POST(request: Request) {
  const secret = process.env.REVALIDATION_SECRET;
  if (!secret) {
    return NextResponse.json({ error: { code: "access_pending", message: "Revalidation is not configured" } }, { status: 503 });
  }
  const raw = await request.text();
  const given = request.headers.get("x-revalidate-signature") ?? "";
  const expected = createHmac("sha256", secret).update(raw).digest("hex");
  const valid = given.length === expected.length && timingSafeEqual(Buffer.from(given), Buffer.from(expected));
  if (!valid) {
    return NextResponse.json({ error: { code: "forbidden", message: "Bad signature" } }, { status: 401 });
  }
  let slug: unknown;
  try {
    slug = (JSON.parse(raw) as { slug?: unknown }).slug;
  } catch {
    slug = null;
  }
  if (typeof slug !== "string" || !/^[a-z0-9]+(-[a-z0-9]+)*$/.test(slug)) {
    return NextResponse.json({ error: { code: "validation_failed", message: "Bad slug" } }, { status: 422 });
  }
  revalidatePath(`/projects/${slug}`);
  return NextResponse.json({ revalidated: true });
}
