import type { Metadata } from "next";

import { apiGetPublic, type Schemas } from "@/lib/api-server";

export const metadata: Metadata = { title: "Project insights", robots: { index: false, follow: false } };

// Public project page (docs/09). It reads only the active, eligible revision from
// getPublicInsights and never calls a model. Until Step 11 implements publication,
// every slug renders the empty state.
export default async function ProjectPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const insights = await apiGetPublic<Schemas["PublicInsights"]>(`/v1/public/projects/${encodeURIComponent(slug)}/insights`);

  if (!insights.data) {
    return (
      <main className="mx-auto max-w-[68ch] px-4 py-10">
        <section data-insights-state="empty" className="rounded-lg border border-line p-6">
          <h1 className="mb-2 text-lg font-semibold">What buyers discuss</h1>
          <p className="text-ink-muted">No reviewed insights are published for this project yet.</p>
        </section>
      </main>
    );
  }

  const { payload, revision_id: revisionId, payload_sha256: hash } = insights.data;
  return (
    <main className="mx-auto max-w-[68ch] px-4 py-10 text-[17px] leading-7">
      <section data-insights-state="active" data-insights-revision={revisionId} data-insights-hash={hash}>
        <h1 className="mb-2 text-2xl font-semibold">{payload.heading}</h1>
        <p className="text-ink-muted">{payload.attribution}</p>
      </section>
    </main>
  );
}
