import Link from "next/link";

import type { components } from "@/lib/api-schema";
import { label, moment } from "@/lib/format";

type EvidenceView = components["schemas"]["EvidenceView"];

/** Exact evidence excerpts beside a finding or review, each linking to its whole source. */
export function EvidenceList({ projectId, evidence, contradicting = [] }: { projectId: string; evidence: EvidenceView[]; contradicting?: string[] }) {
  if (evidence.length === 0) return <p className="text-ink-muted">No evidence span is available.</p>;
  return (
    <ul className="space-y-2">
      {evidence.map((e) => {
        const against = contradicting.includes(e.evidence.id);
        const time = e.anchor_view.kind === "time" ? ` at ${moment((e.anchor_view as components["schemas"]["TimeAnchor"]).start_ms)}` : "";
        return (
          <li key={`${e.evidence.id}@${e.evidence.revision}`} className={`rounded border p-2 ${against ? "border-warn" : "border-line"}`}>
            <p className="mb-1 text-xs text-ink-muted">
              {against ? "Contradicting · " : ""}
              {label(e.evidence.modality)} · {e.evidence.language}
              {time}
              {!e.eligible ? <span className="text-danger"> · not eligible: {e.ineligibility_reasons.map(label).join(", ")}</span> : null}
            </p>
            <p className="whitespace-pre-wrap text-[13px] leading-5">{e.evidence.excerpt_text ?? "(erased)"}</p>
            <Link
              href={`/console/projects/${projectId}/evidence/${e.evidence.source.id}/${e.evidence.source.revision}`}
              className="text-xs text-accent underline"
            >
              open the source
            </Link>
          </li>
        );
      })}
    </ul>
  );
}
