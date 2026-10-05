# Changelog

## 1.1 amendments — 25 September 2026

- Five project inputs registered from the the client export, with developers and RERA registrations (D15, D16).
- New requirement 4.7: the A01 Project identity agent proposes alternate project and phase names from evidence; each needs console approval before it is used (D17).

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
  - MongoDB's cache is lowered to 0.25 GB, and the media worker restarts after the kernel kills it (D48).

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
