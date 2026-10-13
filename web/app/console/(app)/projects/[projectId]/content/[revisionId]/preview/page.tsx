import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { InsightsModule } from "@/components/InsightsModule";
import { ErrorState } from "@/components/ui";
import { apiGet, type Schemas } from "@/lib/api-server";
import { shortHash } from "@/lib/format";

// Private preview (docs/03 render_private_preview): the real public template with this revision's payload, behind
// sign-in and noindex. It never sets the public delivery markers.
export const metadata: Metadata = { title: "Preview", robots: { index: false, follow: false } };

export default async function PreviewPage({ params }: { params: Promise<{ projectId: string; revisionId: string }> }) {
  const { revisionId } = await params;
  const view = await apiGet<Schemas["ContentRevisionView"]>(`/v1/content-revisions/${revisionId}`);
  if (view.status === 404) notFound();
  if (!view.data) return <ErrorState status={view.status} error={view.error} requestId={view.requestId} />;
  const { revision } = view.data;
  return (
    <div>
      <p className="mb-4 rounded border border-warn bg-surface px-3 py-2 text-warn">
        Preview of revision {revision.revision} ({revision.lifecycle.replaceAll("_", " ")}, hash {shortHash(revision.payload_sha256)}). Not public.
      </p>
      <div className="mx-auto max-w-[68ch] rounded-lg border border-line bg-surface px-6 py-8">
        <InsightsModule payload={revision.payload} mode="preview" />
      </div>
    </div>
  );
}
