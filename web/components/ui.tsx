import Link from "next/link";

/** Small presentational pieces shared by console screens (D25: calm, dense, text before colour). */

export function PageTitle({ title, children }: { title: string; children?: React.ReactNode }) {
  return (
    <div className="mb-4">
      <h1 className="text-lg font-semibold">{title}</h1>
      {children ? <p className="mt-1 max-w-3xl text-ink-muted">{children}</p> : null}
    </div>
  );
}

export function Panel({ title, children, actions }: { title?: string; children: React.ReactNode; actions?: React.ReactNode }) {
  return (
    <section className="rounded-lg border border-line bg-surface">
      {title || actions ? (
        <header className="flex items-center justify-between gap-3 border-b border-line px-4 py-2">
          {title ? <h2 className="font-semibold">{title}</h2> : <span />}
          {actions}
        </header>
      ) : null}
      <div className="p-4">{children}</div>
    </section>
  );
}

/** Why something is empty and what to do next (docs/09 shared states). */
export function EmptyState({ children }: { children: React.ReactNode }) {
  return <p className="rounded border border-dashed border-line bg-surface p-4 text-ink-muted">{children}</p>;
}

/** A failed read: forbidden says only that a role is missing; errors carry the request ID. */
export function ErrorState({ status, error, requestId }: { status: number; error: string | null; requestId?: string | null }) {
  if (status === 403) {
    return <p className="rounded border border-line bg-surface p-4 text-ink-muted" role="status">Your role does not include this view.</p>;
  }
  return (
    <p role="alert" className="rounded border border-danger bg-surface p-4 text-danger">
      {error ?? "Something went wrong."}
      {requestId ? <span className="ml-2 font-mono text-xs">request {requestId}</span> : null}
    </p>
  );
}

export function Mono({ children }: { children: React.ReactNode }) {
  return <span className="font-mono text-xs">{children}</span>;
}

export function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-[10rem_1fr] gap-2 py-1">
      <dt className="text-ink-muted">{label}</dt>
      <dd>{children}</dd>
    </div>
  );
}

export function Table({ children, label }: { children: React.ReactNode; label: string }) {
  return (
    <div className="overflow-x-auto rounded-lg border border-line bg-surface">
      <table aria-label={label} className="w-full border-collapse text-[13px] leading-[18px]">
        {children}
      </table>
    </div>
  );
}

export function Th({ children }: { children?: React.ReactNode }) {
  return <th className="border-b border-line px-3 py-2 text-left font-medium text-ink-muted">{children}</th>;
}

export function Td({ children, className = "" }: { children?: React.ReactNode; className?: string }) {
  return <td className={`border-b border-line px-3 py-2 align-top ${className}`}>{children}</td>;
}

/** "Next page" link that keeps the other query parameters. */
export function MoreLink({ cursor, params, path }: { cursor: string | null; params: Record<string, string | undefined>; path: string }) {
  if (!cursor) return null;
  const query = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v && k !== "cursor") query.set(k, v);
  query.set("cursor", cursor);
  return (
    <Link className="mt-3 inline-block text-accent underline" href={`${path}?${query.toString()}`}>
      Next page
    </Link>
  );
}

export function Notice({ tone = "warn", children }: { tone?: "warn" | "ok" | "danger" | "idle"; children: React.ReactNode }) {
  const tones = { warn: "border-warn text-warn", ok: "border-ok text-ok", danger: "border-danger text-danger", idle: "border-idle text-idle" };
  return <p className={`rounded border bg-surface px-3 py-2 ${tones[tone]}`}>{children}</p>;
}
