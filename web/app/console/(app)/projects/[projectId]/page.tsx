import { redirect } from "next/navigation";

export default async function ProjectHome({ params }: { params: Promise<{ projectId: string }> }) {
  const { projectId } = await params;
  redirect(`/console/projects/${projectId}/setup`);
}
