export type Tone = "ok" | "warn" | "danger" | "idle" | "info" | "neutral";

const TONE_OF: Record<string, Tone> = {
  live: "ok",
  verified: "ok",
  approved: "ok",
  completed: "ok",
  complete_for_query: "ok",
  published: "ok",
  active: "ok",
  accepted: "ok",
  auto_accepted: "ok",
  matches_original: "ok",
  passed: "ok",
  resolved: "ok",
  access_pending: "warn",
  delivery_pending: "warn",
  partial: "warn",
  stale: "warn",
  retry_wait: "warn",
  pending: "warn",
  needs_review: "warn",
  changes_requested: "warn",
  final_review: "warn",
  findings_review: "warn",
  waiting_review: "warn",
  needs_moderator: "warn",
  temporarily_disabled: "warn",
  draft: "warn",
  received: "warn",
  issues_found: "warn",
  budget_exhausted: "warn",
  running: "info",
  collecting: "info",
  analysing: "info",
  formatting: "info",
  publishing: "info",
  activating: "info",
  failed: "danger",
  rejected: "danger",
  withdrawn: "danger",
  mismatch: "danger",
  blocking: "danger",
  cancelled: "idle",
  unavailable: "idle",
  superseded: "idle",
  unpublished: "idle",
  dismissed: "idle",
  insufficient_evidence: "idle",
  rolled_back: "idle",
};

const PILL: Record<Tone, string> = {
  ok: "bg-ok-soft text-ok ring-ok/20",
  warn: "bg-warn-soft text-warn ring-warn/25",
  danger: "bg-danger-soft text-danger ring-danger/20",
  idle: "bg-idle-soft text-idle ring-idle/20",
  info: "bg-info-soft text-info ring-info/20",
  neutral: "bg-surface-sunken text-ink-muted ring-line-strong/60",
};

const DOT: Record<Tone, string> = {
  ok: "bg-ok",
  warn: "bg-warn",
  danger: "bg-danger",
  idle: "bg-idle",
  info: "bg-info",
  neutral: "bg-line-strong",
};

export function toneOf(status: string | null | undefined): Tone {
  return TONE_OF[status ?? ""] ?? "neutral";
}

/** A status always shows its text, never colour alone (WCAG, D25). `text` replaces the stored name when a plainer
 * word exists (run stages, lib/format STAGE_LABELS); the colour still follows the stored status. A status the system
 * is working on pulses. */
export function StatusBadge({ status, text, size = "sm" }: { status: string | null | undefined; text?: string; size?: "sm" | "md" }) {
  const value = status ?? "none";
  const tone = toneOf(value);
  const working = tone === "info";
  return (
    <span
      className={`inline-flex items-center gap-1.5 whitespace-nowrap rounded-full font-medium ring-1 ring-inset ${PILL[tone]} ${
        size === "md" ? "px-2.5 py-1 text-[13px]" : "px-2 py-0.5 text-xs"
      }`}
    >
      <span aria-hidden="true" className="relative inline-flex h-1.5 w-1.5">
        {working ? <span className={`absolute inline-flex h-full w-full animate-ping rounded-full opacity-60 ${DOT[tone]}`} /> : null}
        <span className={`relative inline-flex h-1.5 w-1.5 rounded-full ${DOT[tone]}`} />
      </span>
      {text ?? value.replaceAll("_", " ")}
    </span>
  );
}
