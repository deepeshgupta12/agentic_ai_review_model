const TONES: Record<string, string> = {
  live: "text-ok border-ok",
  verified: "text-ok border-ok",
  approved: "text-ok border-ok",
  completed: "text-ok border-ok",
  published: "text-ok border-ok",
  active: "text-ok border-ok",
  accepted: "text-ok border-ok",
  matches_original: "text-ok border-ok",
  passed: "text-ok border-ok",
  resolved: "text-ok border-ok",
  access_pending: "text-warn border-warn",
  delivery_pending: "text-warn border-warn",
  partial: "text-warn border-warn",
  stale: "text-warn border-warn",
  retry_wait: "text-warn border-warn",
  pending: "text-warn border-warn",
  needs_review: "text-warn border-warn",
  changes_requested: "text-warn border-warn",
  final_review: "text-warn border-warn",
  findings_review: "text-warn border-warn",
  waiting_review: "text-warn border-warn",
  needs_moderator: "text-warn border-warn",
  temporarily_disabled: "text-warn border-warn",
  draft: "text-warn border-warn",
  received: "text-warn border-warn",
  issues_found: "text-warn border-warn",
  failed: "text-danger border-danger",
  rejected: "text-danger border-danger",
  withdrawn: "text-danger border-danger",
  mismatch: "text-danger border-danger",
  blocking: "text-danger border-danger",
  cancelled: "text-idle border-idle",
  unavailable: "text-idle border-idle",
  superseded: "text-idle border-idle",
  unpublished: "text-idle border-idle",
  dismissed: "text-idle border-idle",
  insufficient_evidence: "text-idle border-idle",
  rolled_back: "text-idle border-idle",
};

/** A status always shows its text, never colour alone (WCAG, D25). `text` replaces the stored name when a plainer
 * word exists (run stages, lib/format STAGE_LABELS); the colour still follows the stored status. */
export function StatusBadge({ status, text }: { status: string | null | undefined; text?: string }) {
  const value = status ?? "none";
  const tone = TONES[value] ?? "text-ink-muted border-line";
  return (
    <span className={`inline-flex items-center whitespace-nowrap rounded border px-1.5 py-0.5 font-mono text-xs ${tone}`}>
      {text ?? value.replaceAll("_", " ")}
    </span>
  );
}
