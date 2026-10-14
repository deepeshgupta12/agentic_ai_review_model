import { redirect } from "next/navigation";

/** A project opens at its runs: the first step of the flow; the banner above every tab says what comes next. */
export default async function ProjectHome({ params }: { params: Promise<{ projectId: string }> }) {
  const { projectId } = await params;
  redirect(`/console/projects/${projectId}/runs`);
}
