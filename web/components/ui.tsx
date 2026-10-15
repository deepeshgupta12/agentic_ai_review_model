import Link from "next/link";

import { Icon, type IconName } from "@/components/icons";
import type { Tone } from "@/components/StatusBadge";

/** Presentational pieces shared by console screens (D25: calm and readable, text before colour). */

/** Button looks, for buttons and for links that act as buttons. */
export const BUTTON = {
  primary:
    "inline-flex items-center justify-center gap-1.5 rounded bg-accent px-3.5 py-2 font-medium text-white shadow-sm transition hover:bg-accent-strong disabled:cursor-not-allowed disabled:opacity-50",
  secondary:
    "inline-flex items-center justify-center gap-1.5 rounded border border-line-strong/70 bg-surface px-3.5 py-2 font-medium text-ink shadow-sm transition hover:border-line-strong hover:bg-surface-sunken disabled:cursor-not-allowed disabled:opacity-50",
  danger:
    "inline-flex items-center justify-center gap-1.5 rounded border border-danger/40 bg-surface px-3.5 py-2 font-medium text-danger shadow-sm transition hover:bg-danger-soft disabled:cursor-not-allowed disabled:opacity-50",
  ghost: "inline-flex items-center gap-1 rounded px-2 py-1 font-medium text-accent transition hover:bg-accent-soft",
} as const;

export function PageTitle({
  title,
  eyebrow,
  children,
  actions,
}: {
  title: string;
  eyebrow?: React.ReactNode;
  children?: React.ReactNode;
  actions?: React.ReactNode;
}) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div className="min-w-0">
        {eyebrow ? <p className="mb-1 text-xs font-semibold uppercase tracking-wider text-accent">{eyebrow}</p> : null}
        <h1 className="text-2xl font-semibold tracking-tight text-ink">{title}</h1>
        {children ? <div className="mt-1.5 max-w-3xl text-ink-muted">{children}</div> : null}
      </div>
      {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
    </div>
  );
}

export function Panel({
  title,
  description,
  children,
  actions,
  icon,
}: {
  title?: string;
  description?: React.ReactNode;
  children: React.ReactNode;
  actions?: React.ReactNode;
  icon?: IconName;
}) {
  return (
    <section className="overflow-hidden rounded-lg border border-line bg-surface shadow-card">
      {title || actions ? (
        <header className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-5 py-3">
          <div className="flex min-w-0 items-center gap-2.5">
            {icon ? (
              <span aria-hidden="true" className="inline-flex h-7 w-7 items-center justify-center rounded-md bg-accent-soft text-accent">
                <Icon name={icon} />
              </span>
            ) : null}
            <div className="min-w-0">
              {title ? <h2 className="text-[15px] font-semibold">{title}</h2> : null}
              {description ? <p className="text-xs text-ink-muted">{description}</p> : null}
            </div>
          </div>
          {actions}
        </header>
      ) : null}
      <div className="p-5">{children}</div>
    </section>
  );
}

/** A white card with no header. */
export function Card({ children, className = "", testId }: { children: React.ReactNode; className?: string; testId?: string }) {
  return (
    <div data-testid={testId} className={`rounded-lg border border-line bg-surface shadow-card ${className}`}>
      {children}
    </div>
  );
}

const STAT_TONE: Record<Tone | "accent", string> = {
  ok: "bg-ok-soft text-ok",
  warn: "bg-warn-soft text-warn",
  danger: "bg-danger-soft text-danger",
  idle: "bg-idle-soft text-idle",
  info: "bg-info-soft text-info",
  neutral: "bg-surface-sunken text-ink-muted",
  accent: "bg-accent-soft text-accent",
};

/** One headline number with its label and an optional line under it. */
export function Stat({
  label,
  value,
  hint,
  icon,
  tone = "accent",
  children,
}: {
  label: string;
  value: React.ReactNode;
  hint?: React.ReactNode;
  icon?: IconName;
  tone?: Tone | "accent";
  children?: React.ReactNode;
}) {
  return (
    <div className="rounded-lg border border-line bg-surface p-4 shadow-card">
      <div className="flex items-start justify-between gap-2">
        <p className="text-xs font-medium uppercase tracking-wide text-ink-muted">{label}</p>
        {icon ? (
          <span aria-hidden="true" className={`inline-flex h-7 w-7 items-center justify-center rounded-md ${STAT_TONE[tone]}`}>
            <Icon name={icon} />
          </span>
        ) : null}
      </div>
      <p className="mt-1 text-2xl font-semibold tabular-nums tracking-tight">{value}</p>
      {hint ? <p className="mt-0.5 text-xs text-ink-muted">{hint}</p> : null}
      {children}
    </div>
  );
}

const BAR_TONE: Record<Tone | "accent", string> = {
  ok: "bg-ok",
  warn: "bg-warn",
  danger: "bg-danger",
  idle: "bg-idle",
  info: "bg-info",
  neutral: "bg-line-strong",
  accent: "bg-accent",
};

/** A bar for "done of total". `live` stripes it while it still moves. The text beside it says the numbers. */
export function ProgressBar({
  value,
  max,
  tone = "accent",
  live = false,
  label,
  size = "md",
}: {
  value: number;
  max: number;
  tone?: Tone | "accent";
  live?: boolean;
  label: string;
  size?: "sm" | "md";
}) {
  const share = max > 0 ? Math.max(0, Math.min(1, value / max)) : 0;
  return (
    <div
      role="progressbar"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={max}
      aria-valuenow={Math.min(value, max)}
      className={`w-full overflow-hidden rounded-full bg-idle-soft ${size === "sm" ? "h-1.5" : "h-2"}`}
    >
      <div
        className={`h-full rounded-full transition-[width] duration-700 ease-out ${BAR_TONE[tone]} ${live ? "bar-live" : ""}`}
        style={{ width: `${Math.max(share * 100, value > 0 ? 3 : 0)}%` }}
      />
    </div>
  );
}

/** Why something is empty and what to do next (docs/09 shared states). */
export function EmptyState({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex items-center gap-3 rounded-lg border border-dashed border-line-strong bg-surface/60 px-5 py-6 text-ink-muted">
      <span aria-hidden="true" className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-idle-soft text-idle">
        <Icon name="inbox" />
      </span>
      <p>{children}</p>
    </div>
  );
}

/** A failed read: forbidden says only that a role is missing; errors carry the request ID. */
export function ErrorState({ status, error, requestId }: { status: number; error: string | null; requestId?: string | null }) {
  if (status === 403) {
    return (
      <p className="rounded-lg border border-line bg-surface p-4 text-ink-muted shadow-card" role="status">
        Your role does not include this view.
      </p>
    );
  }
  return (
    <div role="alert" className="flex items-start gap-3 rounded-lg border border-danger/30 bg-danger-soft p-4 text-danger">
      <Icon name="stop" className="mt-0.5 h-5 w-5" />
      <p>
        {error ?? "Something went wrong."}
        {requestId ? <span className="ml-2 font-mono text-xs opacity-80">request {requestId}</span> : null}
      </p>
    </div>
  );
}

export function Mono({ children }: { children: React.ReactNode }) {
  return <span className="font-mono text-xs">{children}</span>;
}

export function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-[10rem_1fr] gap-2 border-b border-line/70 py-2 last:border-b-0">
      <dt className="text-ink-muted">{label}</dt>
      <dd>{children}</dd>
    </div>
  );
}

export function Table({ children, label }: { children: React.ReactNode; label: string }) {
  return (
    <div className="overflow-x-auto rounded-lg border border-line bg-surface shadow-card">
      <table
        aria-label={label}
        className="w-full border-collapse text-[13px] leading-[18px] [&_tbody_tr:hover]:bg-surface-sunken/70 [&_tbody_tr:last-child_td]:border-b-0"
      >
        {children}
      </table>
    </div>
  );
}

export function Th({ children }: { children?: React.ReactNode }) {
  return (
    <th className="border-b border-line bg-surface-sunken/80 px-3 py-2.5 text-left text-[11px] font-semibold uppercase tracking-wide text-ink-muted">
      {children}
    </th>
  );
}

export function Td({ children, className = "" }: { children?: React.ReactNode; className?: string }) {
  return <td className={`border-b border-line px-3 py-2.5 align-top ${className}`}>{children}</td>;
}

/** "Next page" link that keeps the other query parameters. */
export function MoreLink({ cursor, params, path }: { cursor: string | null; params: Record<string, string | undefined>; path: string }) {
  if (!cursor) return null;
  const query = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v && k !== "cursor") query.set(k, v);
  query.set("cursor", cursor);
  return (
    <Link className={`mt-3 ${BUTTON.secondary}`} href={`${path}?${query.toString()}`}>
      Next page <Icon name="arrow" />
    </Link>
  );
}

const NOTICE: Record<"warn" | "ok" | "danger" | "idle", { box: string; icon: IconName }> = {
  warn: { box: "border-warn/30 bg-warn-soft text-warn", icon: "stop" },
  ok: { box: "border-ok/30 bg-ok-soft text-ok", icon: "check" },
  danger: { box: "border-danger/30 bg-danger-soft text-danger", icon: "stop" },
  idle: { box: "border-line bg-idle-soft text-ink-muted", icon: "inbox" },
};

export function Notice({ tone = "warn", children }: { tone?: "warn" | "ok" | "danger" | "idle"; children: React.ReactNode }) {
  return (
    <div className={`flex items-start gap-2.5 rounded-lg border px-4 py-3 ${NOTICE[tone].box}`}>
      <Icon name={NOTICE[tone].icon} className="mt-0.5 h-4 w-4" />
      <p>{children}</p>
    </div>
  );
}
