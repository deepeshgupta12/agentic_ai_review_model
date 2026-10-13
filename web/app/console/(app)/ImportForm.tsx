"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { Panel } from "@/components/ui";
import { newKey, send } from "@/lib/api-browser";

type Imported = { projects: { project_id: string; slug: string; project_name: string; created: boolean }[] };

/** Import the five-project input file (contracts/five-project-input-template.json): created vs updated. */
export function ImportForm() {
  const router = useRouter();
  const [result, setResult] = useState<Imported | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function onFile(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;
    setError(null);
    setResult(null);
    let body: unknown;
    try {
      body = JSON.parse(await file.text());
    } catch {
      setError("The file is not valid JSON.");
      return;
    }
    const response = await send<Imported>("POST", "/v1/projects/import", body, { idempotencyKey: newKey("import") });
    if (!response.ok || !response.data) {
      setError(response.message);
      return;
    }
    setResult(response.data);
    router.refresh();
  }

  return (
    <Panel title="Import the input file">
      <p className="mb-3 text-ink-muted">Creates or updates catalogue records from the five-project input file (schema 1.1).</p>
      <input type="file" accept="application/json,.json" onChange={onFile} aria-label="Project input file" />
      {error ? (
        <p role="alert" className="mt-2 text-danger">
          {error}
        </p>
      ) : null}
      {result ? (
        <ul className="mt-3 space-y-1">
          {result.projects.map((p) => (
            <li key={p.project_id}>
              {p.project_name}: {p.created ? "created" : "updated or unchanged"}
            </li>
          ))}
        </ul>
      ) : null}
    </Panel>
  );
}
