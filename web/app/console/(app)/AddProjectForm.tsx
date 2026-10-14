"use client";

import { useRouter } from "next/navigation";
import { useRef, useState } from "react";

import { Panel } from "@/components/ui";
import { newKey, send } from "@/lib/api-browser";

type Created = { projects: { project_id: string; slug: string; project_name: string; created: boolean }[] };

const STATES = [
  "Andhra Pradesh", "Bihar", "Delhi", "Goa", "Gujarat", "Haryana", "Karnataka", "Kerala", "Madhya Pradesh", "Maharashtra",
  "Punjab", "Rajasthan", "Tamil Nadu", "Telangana", "Uttar Pradesh", "Uttarakhand", "West Bengal",
];

/** Names: one per line or comma separated. */
function lines(value: FormDataEntryValue | null): string[] {
  return String(value ?? "")
    .split(/[\n,]/)
    .map((s) => s.trim())
    .filter(Boolean);
}

/** RERA lines: one per line only, since a registered name may contain a comma ("Privana West, Phase 1"). */
function reraLines(value: FormDataEntryValue | null): string[] {
  return String(value ?? "")
    .split("\n")
    .map((s) => s.trim())
    .filter(Boolean);
}

/** Add one project from the console (D58): the required fields of the input file, state for the RERA reader, the
 * optional ones, and RERA numbers as "number | registered name" lines. Its full run starts on the Runs tab. */
export function AddProjectForm() {
  const router = useRouter();
  const key = useRef(newKey("add-project"));
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const optional = (name: string) => String(form.get(name) ?? "").trim() || null;
    const rera = reraLines(form.get("rera"))
      .map((line) => {
        const [id, ...name] = line.split("|").map((s) => s.trim());
        return { id, registered_name: name.join(" ").trim() || String(form.get("project_name")).trim() };
      })
      .filter((r) => r.id);
    const body = {
      project_name: String(form.get("project_name") ?? "").trim(),
      alternate_names: lines(form.get("alternate_names")),
      locality: String(form.get("locality") ?? "").trim(),
      city: String(form.get("city") ?? "").trim(),
      state: optional("state"),
      micromarket: optional("micromarket"),
      developer: optional("developer"),
      rera_ids: rera,
    };
    setBusy(true);
    setError(null);
    const result = await send<Created>("POST", "/v1/projects", body, { idempotencyKey: key.current });
    setBusy(false);
    if (!result.ok || !result.data) {
      setError(result.message);
      return;
    }
    key.current = newKey("add-project");
    router.push(`/console/projects/${result.data.projects[0].project_id}/runs`);
    router.refresh();
  }

  const input = "w-full rounded border border-line px-2 py-1";
  return (
    <Panel title="Add a project">
      <form onSubmit={submit} className="space-y-3" data-testid="add-project-form">
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="block">
            <span className="mb-1 block text-ink-muted">Project name (required)</span>
            <input name="project_name" required className={input} />
          </label>
          <label className="block">
            <span className="mb-1 block text-ink-muted">Locality (required)</span>
            <input name="locality" required className={input} placeholder="Sector 79" />
          </label>
          <label className="block">
            <span className="mb-1 block text-ink-muted">City (required)</span>
            <input name="city" required className={input} />
          </label>
          <label className="block">
            <span className="mb-1 block text-ink-muted">State</span>
            <input name="state" list="indian-states" className={input} />
            <datalist id="indian-states">
              {STATES.map((s) => (
                <option key={s} value={s} />
              ))}
            </datalist>
          </label>
          <label className="block">
            <span className="mb-1 block text-ink-muted">Micromarket (optional)</span>
            <input name="micromarket" className={input} />
          </label>
          <label className="block">
            <span className="mb-1 block text-ink-muted">Developer (optional)</span>
            <input name="developer" className={input} />
          </label>
        </div>
        <label className="block">
          <span className="mb-1 block text-ink-muted">Alternate names (one per line or comma separated)</span>
          <textarea name="alternate_names" rows={2} className={input} />
        </label>
        <label className="block">
          <span className="mb-1 block text-ink-muted">RERA numbers (optional, one per line: number | registered name)</span>
          <textarea name="rera" rows={2} className={input} />
        </label>
        {error ? (
          <p role="alert" className="text-danger">
            {error}
          </p>
        ) : null}
        <button type="submit" disabled={busy} className="rounded bg-accent px-3 py-1.5 font-medium text-white disabled:opacity-60">
          {busy ? "Adding…" : "Add project"}
        </button>
      </form>
    </Panel>
  );
}
