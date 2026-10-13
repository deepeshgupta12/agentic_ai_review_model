import { ActionDialog } from "./ActionDialog";

/** Approve, reject and request changes on one exact revision (docs/09: approve and reject always open a dialog;
 * approval is disabled while the backend says the revision may not be approved). */
export function DecisionButtons({
  path,
  revision,
  subject,
  approvable,
  blockedReason,
}: {
  path: string;
  revision: number;
  subject: string;
  approvable: boolean;
  blockedReason?: string;
}) {
  return (
    <div className="flex flex-wrap gap-2">
      <ActionDialog
        label="Approve"
        title={`Approve ${subject} (revision ${revision})`}
        path={path}
        body={{ revision, action: "approve" }}
        reason="optional"
        tone="primary"
        disabled={!approvable}
        disabledReason={blockedReason}
        testId="approve"
        description="You approve this exact revision after reading the evidence beside it. A later edit needs a new approval."
      />
      <ActionDialog
        label="Request changes"
        title={`Request changes to ${subject}`}
        path={path}
        body={{ revision, action: "changes_requested" }}
        reason="required"
      />
      <ActionDialog label="Reject" title={`Reject ${subject}`} path={path} body={{ revision, action: "reject" }} reason="required" tone="danger" testId="reject" />
    </div>
  );
}
