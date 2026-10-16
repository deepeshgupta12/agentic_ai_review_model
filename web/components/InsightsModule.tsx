import type { components } from "@/lib/api-schema";
import { categoryLabel, formatDated, formatDay, moment } from "@/lib/format";

type Payload = components["schemas"]["ContentPayload"];

/** A link to a moment in a video (YouTube's t parameter); other links unchanged. */
function at(url: string, ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return url;
  try {
    const parsed = new URL(url);
    if (/(^|\.)youtube\.com$|(^|\.)youtu\.be$/.test(parsed.hostname)) {
      parsed.searchParams.set("t", `${Math.floor(ms / 1000)}s`);
      return parsed.toString();
    }
  } catch {
    return url;
  }
  return url;
}

function Items({ title, items, empty }: { title: string; items: Payload["advantages"]; empty: string }) {
  return (
    <section aria-labelledby={`${title}-heading`} className="mt-6">
      <h3 id={`${title}-heading`} className="mb-2 text-lg font-semibold">
        {title}
      </h3>
      {items.length === 0 ? (
        <p className="text-ink-muted">{empty}</p>
      ) : (
        <ul className="space-y-3">
          {items.map((item, index) => (
            <li key={index} className="border-l-2 border-line pl-3">
              <p>{item.text}</p>
              {item.caveat ? <p className="mt-1 text-[15px] text-ink-muted">Note: {item.caveat}</p> : null}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

type Props = {
  payload: Payload;
  /** Delivery markers (docs/09): set on the public page; the console preview passes mode "preview". */
  revisionId?: string;
  payloadHash?: string;
  mode?: "active" | "preview";
  correction?: React.ReactNode;
};

/** The project insights module: the public template, also used for the console's private preview (docs/08). It
 * renders only what the frozen payload holds; no model call, no extra data. */
export function InsightsModule({ payload, revisionId, payloadHash, mode = "active", correction }: Props) {
  const markers =
    mode === "active"
      ? { "data-insights-state": "active", "data-insights-revision": revisionId, "data-insights-hash": payloadHash }
      : { "data-insights-state": "preview" };
  const window = payload.evidence_window;
  return (
    <section {...markers} className="text-[17px] leading-7" aria-labelledby="insights-heading">
      <h2 id="insights-heading" className="text-2xl font-semibold leading-8">
        {payload.heading}
      </h2>
      <p className="mt-1 text-[15px] text-ink-muted">
        {payload.overview
          ? `Public discussion from ${formatDay(window.from)} to ${formatDay(window.to)} · Last reviewed ${formatDay(payload.reviewed_on)}`
          : `Updated ${formatDay(payload.reviewed_on)}`}
      </p>
      {payload.attribution ? <p className="mt-2 text-[15px] text-ink-muted">{payload.attribution}</p> : null}

      {payload.overview ? <p className="mt-5">{payload.overview.text}</p> : null}

      {payload.advantages.length || payload.considerations.length ? (
        <div className="grid gap-x-8 md:grid-cols-2">
          <Items title="Advantages" items={payload.advantages} empty="No advantage was supported well enough to list." />
          <Items title="Considerations" items={payload.considerations} empty="No consideration was supported well enough to list." />
        </div>
      ) : null}

      <section aria-labelledby="reviews-heading" className="mt-8">
        <h3 id="reviews-heading" className="mb-3 text-lg font-semibold">
          What buyers are saying
        </h3>
        {payload.reviews.length === 0 ? (
          <p className="text-ink-muted">No review is shown for this project yet.</p>
        ) : (
          <ol className="space-y-4">
            {payload.reviews.map((review, index) => (
              <li key={index} data-testid="public-review">
                <p className="text-[15px] font-medium">Person {index + 1}</p>
                <blockquote className="border-l-2 border-ink-muted pl-3">
                  <p>{review.text}</p>
                </blockquote>
                {review.aspects?.length ? (
                  <p className="mt-1 text-xs text-ink-muted" data-review-categories={review.aspects.join(",")}>
                    {review.aspects.map(categoryLabel).join(" · ")}
                  </p>
                ) : null}
              </li>
            ))}
          </ol>
        )}
      </section>

      {payload.questions.length ? (
        <section aria-labelledby="questions-heading" className="mt-8">
          <h3 id="questions-heading" className="mb-2 text-lg font-semibold">
            Buyer questions
          </h3>
          <dl className="space-y-3">
            {payload.questions.map((q, index) => (
              <div key={index}>
                <dt className="font-medium">{q.question}</dt>
                <dd>{q.answer}</dd>
              </div>
            ))}
          </dl>
        </section>
      ) : null}

      {payload.sources.length ? (
        <section aria-labelledby="sources-heading" className="mt-8">
          <h3 id="sources-heading" className="mb-2 text-lg font-semibold">
            Sources behind these points
          </h3>
          <ul className="space-y-1 text-[15px]">
            {payload.sources.map((source, index) => (
              <li key={index}>
                <a href={at(source.url, source.timestamp_ms)} rel="nofollow ugc noopener" target="_blank" className="text-accent underline">
                  {source.title}
                </a>
                <span className="text-ink-muted">
                  {" "}
                  · {source.platform} · {formatDated(source.published)}
                  {source.timestamp_ms !== null && source.timestamp_ms !== undefined ? ` · at ${moment(source.timestamp_ms)}` : ""}
                </span>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {payload.overview ? <p className="mt-8 text-[15px] text-ink-muted">{payload.coverage_note}</p> : null}
      {correction}
    </section>
  );
}
