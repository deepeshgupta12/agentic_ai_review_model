# Changelog

## 1.1 amendments — 25 September 2026

- Five project inputs registered from the the client export, with developers and RERA registrations (D15, D16).
- New requirement 4.7: the A01 Project identity agent proposes alternate project and phase names from evidence; each needs console approval before it is used (D17).

## Public repository, no client name — 16 October 2026

- The client's name is removed from every file, file name and commit (history rewritten), the console title, the page metadata, the crawler's user agent and all identifiers; a proprietary LICENSE; the repository is public (D78).

## The product's review categories, category-driven searches, and higher caps — 16 October 2026

- **Reviews are tagged with the product's categories** (builder reputation, construction and specifications, unit layouts and livability, amenities and common areas, maintenance and facility management, safety and security, location and connectivity, value for money, investment potential, pricing); the console filters by category and the public page prints a review's categories (D77).
- **Category-driven searches:** one search per category for the project's name and each alternate name, on Brave, Firecrawl and YouTube (D77).
- **Caps raised across every source** (pages, searches, results, posts, threads, identity checks, job time, a run's model budget) (D77).

## Shorter reviews on the page, and the page build fixed — 16 October 2026

- **A published review has 20 to 80 words** (was 30): reviews of 20 to 29 words that make sense now fit the page (D76).
- **Page building no longer fails on reviews with a known date:** the database validator wanted a date where the frozen page payload holds the contract's string; fixed and applied to the live database (D76).

## The page budget goes to review pages — 16 October 2026 (after the fourth DLF Privana run)

- **Portal sub-pages with no reviews** (amenities, floor plans, location, photos, brochure, listings) are no longer read; **review pages are read first**; the cap is 120 pages a run (D75). Last run 34 of 80 reads went to such pages and 14 pages naming the project were left unread.
- **Firecrawl search retries its rate limit** (four of ten searches were lost to a 429).

## Agents' reviews for the moderator, refused pages read, Instagram searched twice — 15 October 2026 (after the DLF Privana run)

- **Reviews that were dropped now reach the moderator** (D73): agents' and dealers' reviews, sales talk and locality reviews are kept and marked ("agent, dealer or sales talk"; the aspect location), positive and negative alike; the moderator accepts or rejects each. Before, 15 MagicBricks reviews and 2 99acres locality reviews of DLF Privana were left out, and the model left out sales talk and views of the locality.
- **Portal and Quora review pages are read on every run,** so new reviews are collected and nothing left out by an older rule is lost; no review is stored twice (D73).
- **Refused pages are read through Firecrawl** when Scrapfly cannot or may not read them, up to 20 pages a run (D74). Housing.com and most 99acres pages refused the reader.
- **Instagram posts are searched through Brave and Firecrawl search** (D74).
- **Default look-back of 120 days** (D74).

## More reviews found, the right pages kept, and a new console look — 15 October 2026 (after the Conscient Parq run)

- **Why the Conscient Parq run found nothing:** 52 of the 61 pages read were about something else (Parq Casino, parking apps, the developer's other projects); the project's MagicBricks page went to review because its "similar projects" box named another project; a page about another project was accepted from its sidebar; the model read a page's menu. All fixed: every page read must name the project in its title or address, a page is about the project its title names, and the model reads the part of a page that names the project (D71).
- **More sources (D72):** Firecrawl search runs beside Brave with the same searches, and searches the portals' project pages, where the reviews are, instead of single-flat listings.
- **The run's look-back now reaches the searches;** before, every run searched only the last 90 days whatever was chosen.
- **Said in words:** a portal page with a rating but no review text, and an Instagram search that finds no post.
- **Console redesign:** dark top bar, project header with the four-step flow, pill tabs, headline numbers, a stepper and a card per source with its own live progress bar, and source cards to choose when starting a run.

## Failures handled honestly, live progress, and fixes from four audits — 14 October 2026 (after the first live run)

- **The first live run's failure:** a review task with 36 sources was cut off at its output limit and the run ended as "insufficient evidence". Now a task the model cannot answer whole is split down to single passages; what still fails is skipped and reported; anything else stops the run so it can be continued (D70). Review tasks hold at most 12 sources.
- **Continue analysis** in the console for a run that stopped (budget, model access, a failure), including a stopped page building.
- **Live progress:** every source shows queued, running (with its counts as it goes), not finished or its final status; pages refresh only while the system works.
- **Spending protected:** paid page readers are never resent after a timeout; per-run caps hold across retries; finished searches are reused; budget holds are given back when a call fails or a worker stops; only pages that name the project are read on the portals and Quora.
- **Robustness:** a bad page never ends a collect job; a database stall never stops a job's heartbeat; jobs have a time limit; a second run of a project waits for the first; a server error never signs anyone out of the console.
- Contracts: api 1.5.0, routes 1.3.0.

## Real people's reviews, Reddit and Quora, and a simpler console — 14 October 2026 (Steps 09 and 10, continued)

- **Reviews, not facts** (D68). Portal and forum pages are split into one record per person's review from the review data each site publishes: MagicBricks project reviews (agents' and sponsored reviews left out; the full review list read once when the project page shows only some), 99acres reviews (without the locality reviews the page labels as the project's), NoBroker forum answers, Quora answers, and any other page's schema.org reviews of the project. Reviewer names are never kept; the platform's badge (owner, resident) is. A review shown on two pages is stored once. The first web searches look for the project's review pages on the portals and Quora.
- **Reviews-only analysis** (D68, the default): only the review curator (A11, prompt 1.1, which now sees the platform and the reviewer's badge) runs; no claims, verification or findings, and the state registries are not read. The full analysis stays available with `ANALYSIS_MODE=full`.
- **Reddit** (D67) through the free PullPush archive: posts and comments naming the project and each thread's comments; deleted, removed, moderator and bot entries left out; no username stored. **Quora**: only the answers a signed-out visitor is served.
- **The published list** (D69): at most 20 reviews of 30 to 80 words, positive, negative and mixed spread through the list, shown as Person 1, Person 2… in the authors' own words, with no credit, intro or disclosure line and no site name. A page edit can add any approved review; counts written by the system follow the edit.
- **Console flow:** a next-step banner on every project and in the portfolio (run, approve reviews, build the page, approve and publish); tabs in that order; runs started from plain source groups with each connector's status; live coverage on the run page; the draft opens by itself when generated; the page editor shows Person N with word counts and adds, removes and reorders approved reviews. The console reads the limits and the analysis mode from the backend.
- **Fixes:** a run started with every source unticked ran all of them; RERA names with a comma were split in two; the source filter lacked portal reviews; re-checking a portal review compared the whole page with it (now the review is found again by its key on its page); Reddit is searched only with names that identify the project on their own.
- **Stack start keeps the catalogue current:** the db-setup service also runs `sync-catalogue`, loading the source policies and adding any newly registered source (such as Reddit) to existing projects; new projects get every mandatory source when they are added.
- Contracts: common 1.3.0, evidence 1.1.0, content 1.2.0. Query rules 1.1.

## Moderator console, page content and publication — 13 October 2026 (Steps 09 and 10)

- **The whole console** in `web/app/console`: portfolio with **Add project** (any state or city, D58) and the input-file import; per project Setup (configuration at the expected version, construction status, approved names, name proposals), Runs (start the full run, with a warning that it spends paid credits) and a live run page, Evidence (filters, source text with the evidence spans highlighted, match decisions, withdrawal), Videos, Findings and Reviews (each decided beside its evidence, edit as a new revision), Content (choose approved findings and reviews, generate, block editor with QA issues on their blocks, preview with the real template, final approval of the exact hashes, approve-and-publish), Publishing (approved, active and verified revisions, publish, rollback, unpublish); Corrections, Operations and Administration (users and roles, policy versions, audit). Roles hide actions; the backend enforces them again (a test keeps the console's role map equal to the contract).
- **The console runs the real system** (D64): it calls the API, whose services load the real `.env`; the stack runs in live mode.
- **Public project page** `/projects/[slug]`: overview, advantages and considerations, "What buyers are saying" (first-person reviews with credit lines, never presented as written on the client), questions, sources, coverage note, correction form; JSON-LD exactly as approved; delivery markers for verification; signed revalidation route.
- **Page content** (Step 10, D66): generated from a moderator's selection in the analysis graph (`format` step). Pages can be built from approved reviews alone, with no model call (D64). With findings, A08 writes and A09 checks the text; deterministic QA blocks unsupported references and numbers, opinions written as facts, lost caveats, "residents" before possession and changed reviews. Edits are new revisions checked the same way; final approval binds revision, payload and manifest hashes, evidence epoch and state version.
- **Publication** (built now for the end-to-end console; Step 11 completes it): activation by compare-and-set with the operation and delivery job in one transaction; delivery verified by reading the rendered page; rollback, unpublish; withdrawn evidence stops serving at once.
- **Prompt caching** (D65): one cache breakpoint on each agent's instructions, the shared prefix, never on the task's evidence; 5-minute cache for live calls, 1-hour for batches; cache writes and reads are priced in the budget.
- **API**: finding and review revisions, content revisions, approvals and decisions, publication, public insights and corrections, users, audit events, evaluations, `createProject`. Contracts: api 1.4.0, content 1.1.0, catalogue 1.1.0, routes 1.1.0, content rules 1.2.0.
- **Browser journeys** (Playwright) on a separate journey database with the real environment: add a project, decide findings and reviews, generate, approve, publish, verify the public page, edit, correct, role limits.

## Agents and the analysis workflow — 12 October 2026 (Step 08)

- **Spend cap** (D53). Every live Claude call reserves its worst case against a $2 budget before it is made and settles the actual cost; a call that does not fit returns `budget_exhausted`. Roles: Claude Haiku 5.5 for claim extraction and review curation, Sonnet 5 for verification and synthesis. Message Batches are available for bulk work.
- **Primary records.** The HRERA registry reader stores one dated record per supplied RERA ID with registry facts only, so facts can be verified (D53).
- **Agents** with backend checks that hold whatever the model writes: A05 claims (per post or video thread), A06 verification against registry records, A07 findings (attribution, kind and caveats set by the backend; conflicts stay visible), A11 first-person reviews (the author's words checked word by word, one source each, no personal data). Models see short handles, never IDs; invented references are dropped.
- **Workflow** (D55). A LangGraph analysis per run, checkpointed in MongoDB: claims → findings → reviews → findings review (pause) or insufficient evidence. The analysis starts when collection finishes; at the pause the worker is released. A moderator's selection of approved revisions, checked twice, continues it to formatting (content generation is Step 10). Budget and model-access stops are explicit; a crash at any node recovers without duplicates or paying twice; cancellation stops at the next task.
- **Decisions and API.** `listFindings`, `decideFinding`, `listReviewExcerpts` and `decideReviewExcerpt`: decisions name the exact revision, come from a moderator's session, and an approval re-checks flags, attribution, eligibility, rendering and quotation policy. The source list now shows each source's aspects.
- **Instagram public posts** (D54, D55): Brave discovery and Scrapfly reading, caption, author and time only, credits reserved before each request; `access_pending` until a Scrapfly key is set and a real post is read.
- **Evaluation and checks:** `evals/agents/v1` (15 labelled fictional posts, adversarial cases from docs/04) with `make eval-agents`; `make plan-analysis` (dry-run cost), `make analysis-report`, `make verify-analysis`, and a sample sheet of real outputs for the product owner (`exports/`, never committed).
- **Identity:** Devanagari locality words, digits and city names now match (I19, identity-rules 1.1).
- **Registries across India** (D57): each project is looked up only in its own state's RERA registry; a state without a reader yet is reported, not skipped. Haryana is the first reader.
- **Google Alerts** was built as a free listening source (D56) and then removed (D59): it overlaps Brave Search.
- **Construction-status checks** (D63): besides "living there before possession", the backend now flags "still awaiting possession" and construction complaints dated after a project was ready. Displayed reviews carry no dashes. Contracts: common 1.2.0, content rules 1.1.0.
- **Registries across India** (D57) now read 16 more states' RERA portals by registration number (Haryana keeps its list reader); orders and cause lists that mention a number are refused.
- **Every data** (D61): budget $3; robots.txt recorded, never enforced; the web reader reads any public host Brave finds (not only the allow-list), and refused pages go to Scrapfly. **Firecrawl** (D62) renders pages built by JavaScript. Contracts: sources 1.5.0, api 1.3.0 (`host_scope`).
- **Competitor portals** (D60): a portal page that refuses the web reader (99acres, Housing.com) is read through Scrapfly, a few pages per run, within one credit ledger shared with Instagram.
- **Real run** (13 Oct 2026, within the $2 cap): four projects reached findings review (278 claims, 84 findings, 10 reviews); the fifth stopped explicitly when the budget ran out and can continue from its cache. Prompts were tightened during the run to cut cost (A07 1.2, A06 1.2).

## Evidence storage, deduplication and retrieval — 5 October 2026 (Step 07)

- **One eligibility rule** for support, identity work, the API and retrieval (D50). A temporarily unavailable source is not used; a stale one is used with a flag.
- **Context windows.** New text evidence keeps up to 400 code points of context on each side, cut at a sentence end or a space; speech evidence keeps the neighbouring transcript windows. Older evidence gets its context once (`make evidence-context`).
- **Anchor checks.** `make verify-evidence` re-derives every anchor and context from the stored source, and checks links, erasure, the search index, origin clusters and lineage references.
- **Origin clusters.** Copies of one origin count once: identical texts, near-copies and copied passages are joined; short identical comments are not. A scheduled job keeps clusters current; cluster IDs are stable and changes are audited.
- **Filtered retrieval.** Eligibility and the caller's filters come first. A MongoDB text index ranks by keywords; English queries reach Hindi speech through A04's kept translation. Erasure removes the search copy at once. Commands: `make search` and `make eval-retrieval`.
- **Embedding search** (D51, requested by the product owner). Local bge-m3 (int8 ONNX, pinned and hash-checked) runs in a new `embedder` service, capped at 1.5 GB. A scheduled job gives every evidence span its vector. Hybrid ranking fuses keywords and vectors by reciprocal rank and is the default; if the embedder is down, search falls back to keywords and says so. On the labelled set (45 posts, 28 queries), recall@10 went from 0.839 (keyword) to 1.0 (hybrid), closing the word-form, cross-language and paraphrase misses.
- **Lineage.** Claims, findings, source reviews and content revisions are indexed by every exact reference. A correction or withdrawal finds every affected draft and active revision; the invalidation job withdraws approvals that rested on the evidence and reports the rest.
- **Benchmark:** `evals/retrieval/v1`, 45 synthetic posts and 28 labelled queries, scoring keyword, vector and hybrid ranking. Results are in `logs/step-07`.
- **Contracts:** api 1.2.0 (`source_unavailable`), operations 1.4.0 (jobs `cluster_origins` and `embed_evidence`). New collections: `ai_claims`, `ai_findings`, `ai_review_excerpts`, `ai_content_revisions` and `ai_evidence_search`.
- **Found:** Hindi posts that write the locality in Devanagari ("सेक्टर 102") go to review rather than being matched automatically (I19).

## Videos and languages — 1 October 2026 (Step 06)

- **Transcripts** for project videos whose match is accepted (D47). The route order is:
  1. published captions;
  2. otherwise, up to 10 minutes, public audio transcribed locally with faster-whisper `large-v3-turbo`;
  3. otherwise metadata-only, with the reason recorded.

  A refusal stops the attempt and is never worked around, and audio is deleted after each job.
- **Windows** of about 30 seconds on the original timeline become media segments and speech evidence. Windows that name a project are matched on their own words; the others inherit the video's match and return to review if it is undone. Erasing a video erases its transcript.
- **Language.** Language tags and quality flags are added. Every number in machine-made text is flagged for a person. A04 translations are kept only when numbers and negations survive, and Hindi negation markers respect Devanagari word edges.
- **Media worker** in its own image and container (D48): ffmpeg and the media libraries, 2 GB, the first to be killed under memory pressure, with MongoDB protected.
- **APIs and commands:**
  - `listMedia`;
  - `make transcribe`, `make eval-media`, `make eval-language` and `make eval-frames`;
  - transcript rules in `verify-collection`.
- **Measurement:** a synthetic speech set (`evals/media/v1`, eight text-to-speech clips with known text).
- **Frames and on-screen text** (D49, the product owner's Z3 decision). The video is downloaded once at 480p or lower, and that one download serves both the speech and the frames:
  - up to 12 frames are sampled at scene changes and at least every 10 seconds;
  - A03 (one Claude vision call per video) copies on-screen text verbatim and describes visible facts;
  - each observation becomes an `on_screen_text` or `frame` segment and evidence at its frame's time;
  - renders, and anything not clearly real footage, are flagged `possible_render`;
  - images are never stored;
  - a refused video download keeps the captions, and the skip is audited.

  Synthetic frame check: 6 of 6 phrases read, and 3 of 3 graphics recognised as graphics (`make eval-frames`).
- **Contracts:** sources 1.4.0, common 1.1.0, agents 1.1.0 and operations 1.2.0. **Policies:** spoken_video_content v3 and youtube v3.
- **First real videos** (2 Oct 2026). Five project videos went through captions, audio and frames. The run led to these fixes:
  - A03's output cap is raised to 8,192 tokens;
  - phone numbers read off frames are replaced, because contact details are not evidence;
  - on-screen text is tagged by its own script;
  - the media worker restarts after the kernel kills it (D48). A 0.25 GB MongoDB cache was tried and reverted, because tests ran three times slower and memory did not fall.

  On 1 Oct an office firewall had blocked youtube.com (I17).

## Text and social collection — 30 September 2026 (Step 05)

- Source policies in the database (`ai_source_policies`, immutable versions). The host decides the policy family. The generic web family is an allow-list of 62 hosts; client-site.example is not on it (D41). Portals have their own family (D34).
- Safe fetching:
  - public addresses only, re-checked on every redirect hop;
  - size and type caps;
  - an honest user agent;
  - per-host pacing and Retry-After;
  - robots.txt (RFC 9309);
  - atomic provider quotas;
  - cursors that commit with their page;
  - a fetch log.
- Connectors, all live on 30 Sep 2026:
  - Brave Search (discovery metadata only);
  - the web reader, local HTTP plus Trafilatura without Crawl4AI (D40);
  - YouTube Data API: videos as metadata only, and comments that keep their thread (D42).
- Collection runs:
  - one job per group;
  - honest per-connector coverage;
  - only the connectors the run planned (D43);
  - an SSE event stream;
  - run and source APIs with UTF-16 evidence offsets;
  - withdrawal;
  - real connector health.
- Source lifecycle:
  - temporary failures versus confirmed deletion;
  - erasure only after invalidation;
  - retention expiry;
  - the new `check_availability` job for edits, deletions and stated dates. Contract: operations 1.1.0 (D44).
- Publication dates come only from structured markup (D44).
- robots.txt is asked and recorded for every page; it blocks a fetch only where the policy version says `obey`. The web reader's families record without enforcing (product owner, 1 Oct 2026, D46). Refused pages are still not worked around, and a source a person withdrew is never collected again. Contracts: sources 1.2.0, api 1.1.0.
- `verify-collection` checks the collection rules on the stored data.
- Tests no longer see real credentials from `.env` or the shell.
- New commands: `make collect`, `make recheck`, `make verify-collection`, `make discover-hosts`, `make seed-policies`.

## Project identity — 28 September 2026 (Step 04)

- Identity service in `backend/app/identity/`:
  - deterministic matching of sources to projects and phases (D36);
  - project-source links and evidence spans;
  - moderator corrections (accept, reject, split, remap) with dependency invalidation;
  - alias proposals with backend checks for strong identifiers, collisions and generic names (D37);
  - the A01 identity agent for review segments, which annotates only;
  - bounded query plans;
  - a synthetic identity evaluation (D39).
- APIs: import (with Idempotency-Key), project list and detail, configuration updates, link decisions, alias proposals and their decisions.
- Construction status per phase from I16 in `seed/construction_status.json`.
- The link state machine and journey J05 were amended so revoked aliases return matches to review (D35).
- New commands: `make plan-queries`, `make eval-identity`, `make smoke-identity`, `make check-step04`.

## Engineering foundation — 28 September 2026 (Step 03)

- Backend (`backend/`): FastAPI API, worker and scheduler on Python 3.13; settings with explicit fixture/live modes; JSON logs with request IDs and redaction; MongoDB setup that creates collections, contract-derived validators and indexes and is safe to repeat; seeding of the five projects and the coordinator; own sign-in with argon2id, signed session cookie, CSRF and role checks from `routes.json`; durable jobs with leases, fencing, recovery, retries and cancellation; LangGraph checkpoints in MongoDB; the Claude gateway with structured outputs, one bounded repair, retries and a model-ID check.
- Web (`web/`): Next.js 16 console shell (sign-in, dashboard, operations) and the public project page's empty state, with API types generated from OpenAPI.
- Docker Compose stack with a single-node replica set, `.env.example` and `scripts/init_env.py`, a Makefile, GitHub Actions CI (contracts, backend, web, Compose), `prompts/`.
- Setup commands are backend CLI subcommands instead of separate scripts (D30); session design (D31); version matrix (D29) and deferred libraries (D32) in DECISIONS.md.

## Contracts v1 — 28 September 2026 (Step 02)

- Implementation contracts in `contracts/v1/` replace the baseline exchange schema for all new code (D22); baseline files kept as history.
- State lists extended on purpose: workflow `cancelled`; content `changes_requested` and `rejected`; finding review `superseded` (docs/05).
- API grows from the docs/03 table to 47 operations, adding what the console screens need (docs/09).
- Canonical hashing and text anchors fixed (D23, D24); design direction proposed (D25).
- Construction-status consistency for evidence, reviews and page wording (D27).
- First-person reviews from real posts, comments and videos, credited to platform and date, as a core output; new agent A11; web and YouTube policies at version 2 (D28). API now 50 operations.

## 1.1 — 25 September 2026

Revised after the product owner confirmed a standalone build. Differences from handoff 1.0:

| Area | 1.0 | 1.1 |
|---|---|---|
| Repository | Integrate into existing repos | Fresh GitHub repo; `backend/` + `web/`; VS Code + Claude Code; GitHub Actions CI |
| MongoDB | Existing the client deployment, topology unknown | Own MongoDB (Docker Compose, single-node replica set); transactions available; atomicity strategy decided (docs/05) |
| Project catalogue | Existing MongoDB catalogue, canonical ID mapping | Own `projects` collection seeded from the five-project input file; IDs generated by the POC |
| Moderator UI | Extension inside the existing CMS, CMS SSO | Own Next.js console with own authentication and seeded roles |
| Publication target | Existing project detail page via CMS publication adapter | Own server-rendered public project page in `web/`; module payload contract designed for later PDP integration |
| LLM provider | OpenAI SDK, GPT tiers | Claude API (Anthropic Python SDK); structured outputs; model roles in config |
| Transcription | GPT-Transcribe | Local Whisper (faster-whisper) on authorised media only |
| Embeddings | text-embedding-3-large | Keyword baseline first; local multilingual embeddings (bge-m3) as measured addition; Voyage AI as hosted alternative |
| Source access | Procurement before launch; 20-project vendor trial suggested | Obtained incrementally during the build; every connector starts `access_pending`; scraping adapters allowed within policy |
| Inputs | Five fields incl. micromarket | Name, alternate names, locality, city required; micromarket optional |
| Step 01 | Inspect existing catalogue/CMS/website | Register inputs, source-access plan, editorial defaults, initial source policies, acceptance definitions |
| Steps 09/11 | CMS module; CMS/website integration | Moderator console; publication to own public page with ISR revalidation and rendered-revision verification |

Unchanged: the evidence model, agent roster, approval/hash/idempotency invariants, state machines, evaluation gates, and the one-release scope. The reference plan under `reference/` is preserved as written.
