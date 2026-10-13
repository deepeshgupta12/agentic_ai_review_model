import type { Metadata } from "next";

import { CorrectionForm } from "@/components/CorrectionForm";
import { InsightsModule } from "@/components/InsightsModule";
import { apiGetPublic, type Schemas } from "@/lib/api-server";

// Public project page (docs/09). It reads only the active, eligible revision from getPublicInsights at render time
// and never calls a model or reads a draft. The module root carries the delivery markers the publication worker
// verifies; with nothing active it shows the empty state and the rest of the page stays usable. The uncached fetch
// makes the page render on every request, so the page never serves a stale revision.

async function insights(slug: string) {
  return apiGetPublic<Schemas["PublicInsights"]>(`/v1/public/projects/${encodeURIComponent(slug)}/insights`);
}

export async function generateMetadata({ params }: { params: Promise<{ slug: string }> }): Promise<Metadata> {
  const { slug } = await params;
  const result = await insights(slug);
  const meta = result.data?.payload.metadata;
  const index = meta?.robots === "index";
  return {
    title: meta?.title ?? "Project insights",
    description: meta?.description,
    alternates: { canonical: meta?.canonical_path ?? `/projects/${slug}` },
    robots: { index, follow: index },
  };
}

export default async function ProjectPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const result = await insights(slug);

  if (!result.data) {
    return (
      <main className="mx-auto max-w-[68ch] px-4 py-10">
        <section data-insights-state="empty" className="rounded-lg border border-line p-6">
          <h1 className="mb-2 text-lg font-semibold">What buyers are saying</h1>
          <p className="text-ink-muted">No reviewed insights are published for this project yet.</p>
        </section>
      </main>
    );
  }

  const { payload, revision_id: revisionId, payload_sha256: hash } = result.data;
  return (
    <main className="mx-auto max-w-[68ch] px-4 py-10">
      <p className="mb-1 text-sm text-ink-muted">{payload.project.name}</p>
      <InsightsModule
        payload={payload}
        revisionId={revisionId}
        payloadHash={hash}
        correction={<CorrectionForm slug={slug} revisionId={revisionId} />}
      />
      {/* JSON-LD exactly as approved in the payload (docs/09 metadata); "<" is escaped so text cannot close the tag */}
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(payload.json_ld).replace(/</g, "\\u003c") }}
      />
    </main>
  );
}
