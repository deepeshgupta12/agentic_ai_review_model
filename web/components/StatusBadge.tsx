const TONES: Record<string, string> = {
  live: "text-ok border-ok",
  verified: "text-ok border-ok",
  approved: "text-ok border-ok",
  completed: "text-ok border-ok",
  access_pending: "text-warn border-warn",
  delivery_pending: "text-warn border-warn",
  partial: "text-warn border-warn",
  stale: "text-warn border-warn",
  retry_wait: "text-warn border-warn",
  failed: "text-danger border-danger",
  rejected: "text-danger border-danger",
  withdrawn: "text-danger border-danger",
  unavailable: "text-idle border-idle",
};

/** A status always shows its text, never colour alone (WCAG, D25). */
export function StatusBadge({ status }: { status: string }) {
  const tone = TONES[status] ?? "text-ink-muted border-line";
  return (
    <span className={`inline-flex items-center rounded border px-1.5 py-0.5 font-mono text-xs ${tone}`}>
      {status.replaceAll("_", " ")}
    </span>
  );
}
