# Source integration, scraping policy and media access

The production boundary is the five supplied projects. Source access is obtained **incrementally during the build**: every connector is registered as `access_pending` on day one and becomes live only when a credential or contract is configured and a real query against a supplied project has been demonstrated and recorded in PROGRESS.md.

## Suggested activation order

| Order | Source / provider | Why first | What it yields |
|---|---|---|---|
| 1 | Brave Search API | Self-serve key; enables forum/blog/news discovery for all five projects | URLs + snippets (discovery metadata only) |
| 2 | Web reader `web_fetch` (local HTTP + Trafilatura, D40); Firecrawl and Playwright optional | Turns discovered public pages into full-content sources with provenance | Thread/article text, dates stated in markup, author name where visible |
| 3 | YouTube Data API v3 | Self-serve key; video/short discovery, metadata and public comments | Video library + comment sources (comments are legitimate text evidence) |
| 4 | Reddit, X, Meta, Quora/LinkedIn, listening provider | Require commercial approval or contracts; add when obtained | Broader social coverage |
| 5 | Spoken video content | Requires an acquisition route decided by the product owner (I05) | Transcript evidence |

The demo can be meaningful with 1–3 alone. Insufficient chatter or unavailable access is an honest POC result.

## Connector registry

Every platform/capability gets a row in DECISIONS.md: provider, enabled/mandatory flag, content kinds, search/archive/comment/transcript capabilities, credential location, quotas, cursor method, allowed AI processing, derived publication, quotation/attribution, retention, deletion method and last successful verification. Unknown capability remains `access_pending`. Access must be demonstrated, not inferred from a vendor feature list.

| Source family | Route | Demonstration |
|---|---|---|
| Public forums/blogs/news | Brave discovery → web reader for allow-listed hosts (D40, D41) | Full thread context, dates, author role, pagination, deleted-content handling |
| YouTube videos/Shorts | YouTube Data API for discovery/metadata/comments | Query match, quota, comments disabled, removed video, unknown format |
| Spoken video content | Creator-supplied files, licensed transcript/media feed, or content the team itself is authorised to process | Actual permitted transcript/media processed with timing preserved |
| Reddit | Commercially approved API/provider agreement | Analysis and derived-content permissions plus required fields |
| X | Entitled X API or listening provider | Search window/archive access, pagination, quota, downstream permissions |
| Meta platforms | Approved endpoints or contracted listening capabilities | Each promised public/account/comment/Reels capability |
| Instagram public posts | Brave discovery → Scrapfly scrape API (unblocker, residential proxies; D54) | A real public post of a supplied project read, with its robots.txt verdict and credits recorded |
| New web mentions (free listening) | The product owner's Google Alerts, delivered by RSS → web reader for allow-listed pages (D56) | A real alert feed for a supplied project read, with the mentions it named |
| Quora/LinkedIn/other forums | Permitted indexed pages or licensed/partner feeds | Actual project-level coverage |
| Official project facts | Public regulatory/developer pages fetched under policy; optional fields in the input file | Correct phase, effective date and authority of each record |

## Scraping policy (applies to the web reader, Firecrawl, Playwright and any custom adapter)

Scraping is permitted for the POC within these rules, enforced in code and recorded per source policy:

1. Public pages only. Never bypass login, paywalls, CAPTCHAs, rate limits, private groups or disabled access; never use a personal account session to reach non-public content.
2. Ask `robots.txt` for every page and record its verdict in the fetch log. It blocks the fetch only where the family's policy version says `robots_txt: obey`; the web reader's families record it without enforcing it (product owner, 1 Oct 2026, D46). Platform terms are reviewed when a host is added; record the policy basis in `ai_source_policies` before storage or AI use. A fetching tool does not confer data rights.
3. Allow-listed hosts only, with SSRF protection, redirect limits, size/type caps and a per-host concurrency/rate cap. Identify the client honestly in the user agent.
4. Store the minimum author metadata; do not build cross-platform profiles or infer identities.
5. Quotation and derived publication follow the source policy; where quotation is not allowed, publish only paraphrased, attributed findings with a link. Version 2 of the web and YouTube policies (product owner, 28 Sep 2026, D28) allows first-person reviews in the author's words with a credit line naming platform and date; no public link is required.
6. Any acquisition route outside these rules (for example downloading third-party media) is not implemented unless the product owner records a decision in DECISIONS.md that accepts the terms-of-service risk; the code must not hard-code such a route. Recorded 28 Sep 2026: D33 (public videos and captions through yt-dlp and youtube-transcript-api, without sign-in) and D34 (competitor portal reviews). Neither changes rules 1–3. Recorded 9 Oct 2026: D54 (Instagram public posts through Scrapfly's anti-bot unblocker and residential proxies). It is the one exception to rule 1's bot-check clause; sign-in, accounts, cookies and private content stay excluded.

## Common connector interface

Implement `capabilities`, `discover`, `fetch_item`, `fetch_thread`, `list_updates`, `check_availability`, and `health` where supported. Unsupported methods return explicit capability errors. Use versioned input/result types and persist provider request IDs, query/window, source-native ID, cursor and coverage.

Return original publication time or an explicit unknown-date flag (the web reader takes dates only from structured markup; a date written in the page text is not a stated publication date, D44), collected time, canonical URL, content/metadata, parent relationships, access level, source role signals, permitted media references and policy version. Do not rely on arbitrary raw dictionaries in downstream agents.

Commit a page's records before advancing its cursor/watermark. Replaying the page after a crash upserts the same identities. Use bounded retries, exponential backoff with jitter and Retry-After. Isolate a failing platform so other platforms can finish; mark the run partial. Token refresh, quota reservation and concurrency caps must work across workers.

## As built in Step 05

- **Web reader** (`backend/app/connectors/web.py`, D40). Before any request it checks the host's policy family and allow-list, then asks robots.txt and logs the verdict (enforced only under `obey`, D46). Every redirect hop is checked the same way. A redirected page is stored where it landed, and the fetch log keeps both addresses. Every decision goes to `ai_fetch_log`.
- **Safe client** (`backend/app/sources/http.py`). It refuses non-public addresses, re-checked on every hop. It caps size (3 MB) and content type. It paces 3 seconds per host and honours Retry-After with backoff.
- **Runs** (D43). A run uses only the connectors it planned. Coverage is per connector, and `partial` means some items may read next time.
- **Re-checks** (D44). The `check_availability` job re-checks stored pages and YouTube records. It applies the lifecycle rules: temporary failure, two consecutive "gone" results for deletion, a new revision for an edit. It also corrects stated dates with an audit event.
- **Checks on stored data.** `make verify-collection` checks the stored data against these rules.

## As built in Step 06

- **Routes** (`backend/app/media/`, D47). The media worker processes only project videos whose match is accepted:
  1. the published caption track, human-made before auto-generated;
  2. otherwise, up to 10 minutes, the audio through yt-dlp, transcribed locally with faster-whisper;
  3. otherwise the video stays metadata-only with the reason recorded.

  A refusal (bot check, unavailable video, blocked network) stops the attempt. Audio is deleted after each job.
- **Frames** (D49, `spoken_video_content` v3). For a video within the length cap, one download at 480p or lower serves both the speech (when there are no captions) and the frames:
  - ffmpeg samples up to 12 frames, at scene changes and at least every 10 seconds;
  - A03 (one Claude vision call per video) copies on-screen text verbatim and describes visible facts, without identifying people;
  - each observation becomes its own segment at its frame's time (`f:<ms>:text` or `f:<ms>:scene`) and `on_screen_text` or `frame` evidence;
  - anything not clearly real footage is flagged `possible_render` and never proves construction status;
  - frame images are never stored;
  - with captions, a refused video download costs only the frames, and the skip is audited.
- **Windows** of about 30 seconds on the original timeline are the stored segments, the matching unit and the speech evidence span. A window that names no project inherits the video's accepted match; if that match is undone, it returns to review.
- **Language.** Machine-made numbers are flagged `numbers_uncertain`. A04 translations are kept only when numbers and negations survive (`backend/app/media/translate.py`).
- **Media worker** (D48). It runs in its own container: 2 GB, `MEDIA_WORKER_CPUS` CPUs (default 2), in-memory scratch disk, and the kernel kills it first under memory pressure.
- **Checks.** `make eval-media` runs the synthetic speech set; `make eval-language` checks A04 translations; `make eval-frames` checks A03 on synthetic frames.
- **Status.** Live acquisition is blocked while youtube.com is unreachable from the demo network: an office firewall (I17). The end-to-end video run will be done later from another network.

## As built in Step 08

- **HRERA registry** (`backend/app/connectors/harera.py`, D53). The public Gurugram list of registered projects is read once per collection job; one `registration_record` per supplied RERA ID holds registry facts only (certificate and date, project ID, registered name, promoter, location, validity, whether a completion or occupation certificate is listed). The project preview page is not read: it repeats other projects' dates and holds directors' personal details. Policy `official_records` v2 (robots.txt recorded, D46).
- **Instagram public posts** (`backend/app/connectors/instagram.py`, D54, policy `instagram_public` v1). Brave Search restricted to instagram.com finds post and reel addresses; each is read once through Scrapfly's scrape API (`unblocker=true`, `proxy_pool=public_residential_pool`, no JavaScript rendering). The logged-out page embeds the post as JSON; the caption, the author's username and the post time are kept. Comments need a rendered page and more credits, so they are not read in this version. Credits are reserved before each request (`SCRAPFLY_CREDITS_PER_POST` of `SCRAPFLY_MONTHLY_CREDITS`), and a run reads at most `INSTAGRAM_POSTS_PER_PROJECT` posts per project. robots.txt is asked and recorded for every page and not enforced: instagram.com disallows unlisted crawlers. The connector stays `access_pending` until `SCRAPFLY_API_KEY` is set and a real post has been read. Brave hits on instagram.com found by the web group are left to this connector.

- **Google Alerts by RSS** (`backend/app/connectors/alerts.py`, D56, policy `google_alerts` v1). The free listening source: one alert per project in the product owner's Google account, feed addresses in `GOOGLE_ALERTS_FEEDS`. A run reads the feeds whose title names the project, stores each mention as discovery metadata under the policy of the page it points to (Google's redirect link removed; the date is when Google found it, kept as approximate), and the web reader reads allow-listed pages (up to `ALERT_PAGES_PER_RUN`). Feed addresses are never logged in full; snippets are not stored. robots.txt (google.com disallows /alerts/ for crawlers) is recorded, not enforced.

## Media rules

Discovery, transcript availability and analysis completion are separate fields. A discovered video with no authorised transcript remains in the library with its status; it provides no speech evidence. Do not label a Short solely from duration.

For permitted files: validate type/size/duration, isolate processing, normalise audio with FFmpeg, transcribe with local faster-whisper (language hint from the video metadata; record model size and per-segment quality), align segments to the original timeline, keep segment IDs, then translate with the language agent if needed. Store original speech and translation separately. Timestamp precision is exact or approximate with method recorded. Promotional renders and undated footage do not establish current construction progress.

Comments are their own textual sources with parent video references. Do not attribute a viewer comment to the creator.

## Coverage reporting

Report attempted queries, fetched items, relevant matches, analysed items, metadata-only items, missing access and last successful sync by platform. `complete_for_query` means the permitted query was exhausted, not that the internet was covered. A broad outage is not evidence of zero chatter.

If a mandatory platform remains inaccessible, continue independent development and record a release dependency. Do not replace it with synthetic data or describe it as supported.
