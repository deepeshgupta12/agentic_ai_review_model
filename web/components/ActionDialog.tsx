"use client";

import { useRouter } from "next/navigation";
import { useRef, useState } from "react";

import { BUTTON } from "@/components/ui";
import { newKey, send } from "@/lib/api-browser";

type Props = {
  /** Button text. */
  label: string;
  /** Dialog heading. */
  title: string;
  path: string;
  method?: "POST" | "PATCH";
  body: Record<string, unknown>;
  /** Whether the action asks for a reason (docs/09: approve and reject always open a dialog). */
  reason?: "required" | "optional" | "none";
  /** What the dialog explains before the person confirms. */
  description?: React.ReactNode;
  idempotent?: boolean;
  tone?: "primary" | "danger" | "neutral";
  disabled?: boolean;
  disabledReason?: string;
  /** Where to go afterwards; the current page is refreshed when omitted. */
  then?: (data: unknown) => string | null;
  testId?: string;
};

const TONES = { primary: BUTTON.primary, danger: BUTTON.danger, neutral: BUTTON.secondary };

/** A button that opens a confirmation dialog and sends one mutation. A 409 never overwrites anything: it says what
 * changed and offers a reload (docs/09 conflicts). */
export function ActionDialog(props: Props) {
  const { label, title, path, method = "POST", body, reason = "none", description, idempotent, tone = "neutral" } = props;
  const router = useRouter();
  const dialog = useRef<HTMLDialogElement>(null);
  const key = useRef<string>(newKey());
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [conflict, setConflict] = useState(false);

  async function confirm() {
    if (reason === "required" && !text.trim()) {
      setError("A reason is required.");
      return;
    }
    setBusy(true);
    setError(null);
    const payload = reason === "none" ? body : { ...body, reason: text.trim() || null };
    const result = await send(method, path, payload, idempotent ? { idempotencyKey: key.current } : {});
    setBusy(false);
    if (!result.ok) {
      setError(result.message);
      setConflict(result.status === 409);
      return;
    }
    dialog.current?.close();
    key.current = newKey();
    setText("");
    const next = props.then?.(result.data) ?? null;
    if (next) router.push(next);
    router.refresh();
  }

  return (
    <>
      <button
        type="button"
        data-testid={props.testId}
        disabled={props.disabled}
        title={props.disabled ? props.disabledReason : undefined}
        onClick={() => {
          setError(null);
          setConflict(false);
          dialog.current?.showModal();
        }}
        className={TONES[tone]}
      >
        {label}
      </button>
      <dialog ref={dialog} aria-label={title} className="m-auto w-full max-w-lg rounded-xl border border-line p-0">
        <form
          method="dialog"
          className="space-y-4 p-6"
          onSubmit={(event) => {
            event.preventDefault();
            void confirm();
          }}
        >
          <h2 className="text-lg font-semibold tracking-tight">{title}</h2>
          {description ? <div className="text-ink-muted">{description}</div> : null}
          {reason !== "none" ? (
            <label className="block">
              <span className="mb-1 block text-ink-muted">Reason{reason === "required" ? " (required)" : " (optional)"}</span>
              <textarea
                value={text}
                onChange={(e) => setText(e.target.value)}
                rows={3}
                className="w-full rounded border border-line-strong px-3 py-2"
                required={reason === "required"}
              />
            </label>
          ) : null}
          {error ? (
            <p role="alert" className="rounded-md bg-danger-soft px-3 py-2 text-danger">
              {error}
              {conflict ? (
                <button type="button" className="ml-2 underline" onClick={() => router.refresh()}>
                  Reload to see the current version
                </button>
              ) : null}
            </p>
          ) : null}
          <div className="flex justify-end gap-2 border-t border-line pt-4">
            <button type="button" className={BUTTON.secondary} onClick={() => dialog.current?.close()}>
              Cancel
            </button>
            <button type="submit" disabled={busy} className={TONES[tone]}>
              {busy ? "Working…" : label}
            </button>
          </div>
        </form>
      </dialog>
    </>
  );
}
