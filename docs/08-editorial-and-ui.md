# Console experience, public page, SEO/AEO content and editorial rules

All moderator screens are routes inside the Next.js console (`web/app/console/*`), behind the backend session. Designs are produced in-repo during Step 02 (component specs, then implemented screens); there is no external design system to match. The public project page (`web/app/projects/[slug]`) is the POC's publication target and doubles as the reference implementation of the module contract for a future the client PDP integration.

## Console screens

| Screen | Necessary actions and information |
|---|---|
| Portfolio | Five projects, latest run, coverage, pending review, active revision, stale/failed state and spend |
| Project setup | Input fields (name, alternate names, locality, city, optional micromarket/developer/phase/RERA), generated slug, approved aliases, alias/phase-name proposals with evidence and collision warnings (approve/reject/revoke), languages, source selection and refresh settings |
| Evidence explorer | Filters, original/translated text, exact excerpt/context, source/date/policy, origin cluster and contradictions |
| Video library | Platform/channel, project match, format certainty, transcript access, analysis status and timestamp jumps |
| Findings review | Pros/cons/neutral, exact supporting claims, conflicting evidence, independent origins, approve/edit/reject and reason |
| Content editor | Approved findings, controlled editing, changed revision, validation issues, page preview (actual page template) and final approval |
| Publishing | Current approved vs active vs delivered revision, retry, history, rollback and unpublish |
| Operations | Connector coverage and access state, quotas, failed jobs, freshness, deletion progress, model cost and evaluation results |
| Administration | Users/roles, thresholds, source policies and entitlements, retention, prompt versions and audit records |

Show empty, loading, access-pending, partial, error, stale and forbidden states distinctly. Hide or disable actions according to permissions, and enforce them again in the backend. Use accessible labels, keyboard paths and readable side-by-side evidence. Handle optimistic conflicts with a reload/diff flow. Fixture mode is visibly labelled on every console screen.

## Public page module

- Route `/projects/[slug]`, server-rendered, reads `GET /v1/public/projects/{slug}/insights` at render time and embeds `data-insights-revision` / `data-insights-hash` markers for delivery verification.
- Renders: project-specific overview with its time window, evidence-supported advantages and considerations (no forced equal counts), buyer questions with concise answers, permitted source links and video timestamps, last-reviewed date, editorial attribution, a short coverage description, and a correction link posting to the public corrections endpoint.
- No active revision ⇒ a clear empty state (or the module is omitted), never a draft.
- Private preview is the same template rendered inside the console with the draft payload, `noindex`, behind authentication. In the POC, the public page itself is `noindex` unless the product owner decides otherwise (I14).
- Mobile and desktop layouts, escaping, link safety and long-name handling are tested.

## Editorial rules

- Treat reported opinions as attributed observations. A single person's impression cannot become a universal project fact; copied posts cannot become independent consensus.
- Retain useful negative findings under the same evidence rules as positive ones. Require a reason for rejection; allow empty pros/cons lists.
- Proposed recurring-opinion threshold is three independent origin clusters. Calibrate it; it is not a factual verification rule.
- Verify possession dates, prices, approvals and serious allegations against appropriate current primary evidence and route unresolved cases to editorial escalation.
- No aggregate ratings from scraped sentiment, fabricated resident counts, investment promises or invented quotes. Do not imply the sample represents all buyers.
- Every substantive output block carries exact finding/claim references. Preserve caveats through shortening, translation and manual editing.
- Wording follows construction status (D27): before possession write "prospective buyers" or "owners awaiting possession", never "residents" or "living here"; in a partly ready project name the phase.
- First-person reviews (D28) are one real author's words with a credit line (who, platform, date). Show positive and negative ones; do not choose only one side. No dashes or hyphens in displayed review text; no merged, invented or model-paraphrased reviews.
- Q&A questions may be generated from supported topics; answers cannot add new facts. Do not claim these are actual searched user questions without search-query evidence.

## SEO/AEO implementation

Use clear headings and concise direct answers grounded in approved information. The public page never calls an LLM at request time.

Treat metadata and JSON-LD as part of the reviewed payload. Because there is no existing page graph in the POC, the JSON-LD proposal is self-contained: match schema.org types to the visible content (for example a `WebPage`/`Article`-style entity with `about` the project, `FAQPage`-style Q&A only if current Google guidance still supports it, and no aggregate ratings). Recheck current official search/schema guidance at implementation; do not promise ranking uplift, AI-answer inclusion or rich-result eligibility. Design the payload so a later PDP integration can merge it into the real page's entity graph without restructuring.

## Final editorial quality checklist

Compare each claim with its approved wording and evidence; check project/phase, negation, numbers, date, units, attribution, caveats and source window. Flag unsupported changes with the affected block and reason. Deterministic checks enforce references/eligibility; AI QA can flag semantic concerns but cannot approve publication.

Reviewer identity comes from the backend session. Preserve versioned decisions and reasons. A final approval binds the immutable payload described in the publication specification. New formatting after approval must create a new revision rather than silently changing what the moderator approved.
