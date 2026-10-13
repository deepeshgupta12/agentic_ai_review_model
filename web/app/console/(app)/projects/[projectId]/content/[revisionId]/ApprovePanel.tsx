"use client";

import { useRouter } from "next/navigation";
import { useRef, useState } from "react";

import { Panel } from "@/components/ui";
import { newKey, send } from "@/lib/api-browser";
import type { components } from "@/lib/api-schema";
import { shortHash } from "@/lib/format";

type Revision = components["schemas"]["ContentRevision"];
type State = components["schemas"]["PublicationState"];

/** Final approval (docs/09): shows and sends exactly the revision, payload hash, manifest hash, evidence epoch and
 * state version. A 409 says what changed and nothing is approved. With both roles, approve-and-publish makes two
 * separate audited calls. */
export function ApprovePanel({
  revision,
  state,
  mayApprove,
  mayPublish,
  projectId,
}: {
  revision: Revision;
  state: State;
  mayApprove: boolean;
  mayPublish: boolean;
  projectId: string;
}) {
  const router = useRouter();
  const dialog = useRef<HTMLDialogElement>(null);
  const publishKey = useRef(newKey("publish"));
  const [andPublish, setAndPublish] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  if (!mayApprove) {
    return (
      <Panel title="Final approval">
        <p className="text-ink-muted">A moderator approves this exact revision.</p>
      </Panel>
    );
  }

  async function approve() {
    setBusy(true);
    setError(null);
    const approval = await send("POST", `/v1/content-revisions/${revision.id}/approvals`, {
      revision: revision.revision,
      payload_sha256: revision.payload_sha256,
      manifest_sha256: revision.manifest_sha256,
      eligibility_epoch: state.eligibility_epoch,
      expected_state_version: state.version,
    });
    if (!approval.ok) {
      setBusy(false);
      setError(approval.message);
      return;
    }
    if (andPublish) {
      const published = await send(
        "POST",
        "/v1/publications",
        {
          project_id: projectId,
          locale: "en-IN",
          revision_id: revision.id,
          payload_sha256: revision.payload_sha256,
          expected_state_version: state.version + 1,
        },
        { idempotencyKey: publishKey.current },
      );
      if (!published.ok) {
        setBusy(false);
        setError(`Approved, but not published: ${published.message}`);
        router.refresh();
        return;
      }
    }
    setBusy(false);
    dialog.current?.close();
    router.push(andPublish ? `/console/projects/${projectId}/publishing` : `/console/projects/${projectId}/content/${revision.id}`);
    router.refresh();
  }

  return (
    <Panel title="Final approval">
      <button type="button" data-testid="final-approve" className="rounded bg-accent px-3 py-1.5 font-medium text-white" onClick={() => dialog.current?.showModal()}>
        Approve revision {revision.revision}
      </button>
      <dialog ref={dialog} aria-label="Final approval" className="w-full max-w-lg rounded-lg border border-line p-0 backdrop:bg-black/30">
        <div className="space-y-3 p-5">
          <h2 className="text-base font-semibold">Approve exactly this content</h2>
          <dl className="grid grid-cols-[10rem_1fr] gap-1 font-mono text-xs">
            <dt>revision</dt>
            <dd>{revision.revision}</dd>
            <dt>payload hash</dt>
            <dd>{shortHash(revision.payload_sha256)}</dd>
            <dt>manifest hash</dt>
            <dd>{shortHash(revision.manifest_sha256)}</dd>
            <dt>evidence epoch</dt>
            <dd>{state.eligibility_epoch}</dd>
            <dt>state version</dt>
            <dd>{state.version}</dd>
          </dl>
          <p className="text-ink-muted">Any later edit becomes a new revision that needs its own approval.</p>
          {mayPublish ? (
            <label className="flex items-center gap-2">
              <input type="checkbox" checked={andPublish} onChange={(e) => setAndPublish(e.target.checked)} />
              Also publish it now (two separate, audited actions)
            </label>
          ) : null}
          {error ? (
            <p role="alert" className="text-danger">
              {error}
            </p>
          ) : null}
          <div className="flex justify-end gap-2">
            <button type="button" className="rounded border border-line px-3 py-1" onClick={() => dialog.current?.close()}>
              Cancel
            </button>
            <button type="button" disabled={busy} onClick={approve} className="rounded bg-accent px-3 py-1 font-medium text-white disabled:opacity-60">
              {busy ? "Working…" : andPublish ? "Approve and publish" : "Approve"}
            </button>
          </div>
        </div>
      </dialog>
    </Panel>
  );
}
