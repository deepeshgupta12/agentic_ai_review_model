# Source integration, scraping policy and media access

The production boundary is the five supplied projects. Source access is obtained **incrementally during the build**: every connector is registered as `access_pending` on day one and becomes live only when a credential or contract is configured and a real query against a supplied project has been demonstrated and recorded in PROGRESS.md.

## Suggested activation order

| Order | Source / provider | Why first | What it yields |
|---|---|---|---|
| 1 | Brave Search API | Self-serve key; enables forum/blog/news discovery for all five projects | URLs + snippets (discovery metadata only) |
| 2 | Firecrawl (or Playwright adapter) | Turns discovered public pages into full-content sources with provenance | Thread/article text, dates, author role where visible |
| 3 | YouTube Data API v3 | Self-serve key; video/short discovery, metadata and public comments | Video library + comment sources (comments are legitimate text evidence) |
| 4 | Reddit, X, Meta, Quora/LinkedIn, listening provider | Require commercial approval or contracts; add when obtained | Broader social coverage |
| 5 | Spoken video content | Requires an acquisition route decided by the product owner (I05) | Transcript evidence |

The demo can be meaningful with 1–3 alone. Insufficient chatter or unavailable access is an honest POC result.

## Connector registry

Every platform/capability gets a row in DECISIONS.md: provider, enabled/mandatory flag, content kinds, search/archive/comment/transcript capabilities, credential location, quotas, cursor method, allowed AI processing, derived publication, quotation/attribution, retention, deletion method and last successful verification. Unknown capability remains `access_pending`. Access must be demonstrated, not inferred from a vendor feature list.

| Source family | Route | Demonstration |
|---|---|---|
| Public forums/blogs/news | Brave discovery → Firecrawl/Playwright adapter for permitted domains | Full thread context, dates, author role, pagination, deleted-content handling |
| YouTube videos/Shorts | YouTube Data API for discovery/metadata/comments | Query match, quota, comments disabled, removed video, unknown format |
| Spoken video content | Creator-supplied files, licensed transcript/media feed, or content the team itself is authorised to process | Actual permitted transcript/media processed with timing preserved |
| Reddit | Commercially approved API/provider agreement | Analysis and derived-content permissions plus required fields |
| X | Entitled X API or listening provider | Search window/archive access, pagination, quota, downstream permissions |
| Meta platforms | Approved endpoints or contracted listening capabilities | Each promised public/account/comment/Reels capability |
| Quora/LinkedIn/other forums | Permitted indexed pages or licensed/partner feeds | Actual project-level coverage |
| Official project facts | Public regulatory/developer pages fetched under policy; optional fields in the input file | Correct phase, effective date and authority of each record |

## Scraping policy (applies to Firecrawl, Playwright and any custom adapter)

Scraping is permitted for the POC within these rules, enforced in code and recorded per source policy:

1. Public pages only. Never bypass login, paywalls, CAPTCHAs, rate limits, private groups or disabled access; never use a personal account session to reach non-public content.
2. Respect `robots.txt` and platform terms for the fetch; record the policy basis in `ai_source_policies` before storage or AI use. A fetching tool does not confer data rights.
3. Allow-listed hosts only, with SSRF protection, redirect limits, size/type caps and a per-host concurrency/rate cap. Identify the client honestly in the user agent.
4. Store the minimum author metadata; do not build cross-platform profiles or infer identities.
5. Quotation and derived publication follow the source policy; where quotation is not allowed, publish only paraphrased, attributed findings with a link. Version 2 of the web and YouTube policies (product owner, 28 Sep 2026, D28) allows first-person reviews in the author's words with a credit line naming platform and date; no public link is required.
6. Any acquisition route outside these rules (for example downloading third-party media) is not implemented unless the product owner records a decision in DECISIONS.md that accepts the terms-of-service risk; the code must not hard-code such a route. Recorded 28 Sep 2026: D33 (public videos and captions through yt-dlp and youtube-transcript-api, without sign-in) and D34 (competitor portal reviews). Neither changes rules 1–3.

## Common connector interface

Implement `capabilities`, `discover`, `fetch_item`, `fetch_thread`, `list_updates`, `check_availability`, and `health` where supported. Unsupported methods return explicit capability errors. Use versioned input/result types and persist provider request IDs, query/window, source-native ID, cursor and coverage.

Return original publication time or an explicit unknown-date flag, collected time, canonical URL, content/metadata, parent relationships, access level, source role signals, permitted media references and policy version. Do not rely on arbitrary raw dictionaries in downstream agents.

Commit a page's records before advancing its cursor/watermark. Replaying the page after a crash upserts the same identities. Use bounded retries, exponential backoff with jitter and Retry-After. Isolate a failing platform so other platforms can finish; mark the run partial. Token refresh, quota reservation and concurrency caps must work across workers.

## Media rules

Discovery, transcript availability and analysis completion are separate fields. A discovered video with no authorised transcript remains in the library with its status; it provides no speech evidence. Do not label a Short solely from duration.

For permitted files: validate type/size/duration, isolate processing, normalise audio with FFmpeg, transcribe with local faster-whisper (language hint from the video metadata; record model size and per-segment quality), align segments to the original timeline, keep segment IDs, then translate with the language agent if needed. Store original speech and translation separately. Timestamp precision is exact or approximate with method recorded. Promotional renders and undated footage do not establish current construction progress.

Comments are their own textual sources with parent video references. Do not attribute a viewer comment to the creator.

## Coverage reporting

Report attempted queries, fetched items, relevant matches, analysed items, metadata-only items, missing access and last successful sync by platform. `complete_for_query` means the permitted query was exhausted, not that the internet was covered. A broad outage is not evidence of zero chatter.

If a mandatory platform remains inaccessible, continue independent development and record a release dependency. Do not replace it with synthetic data or describe it as supported.
