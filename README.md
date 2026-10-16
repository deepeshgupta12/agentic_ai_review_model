# Agentic Project Intelligence

A proof of concept that collects what real people have said online about a residential project, keeps each person's review in their own words, lets a moderator accept or reject every one, and publishes an approved, evidence-linked review list on a public page. It runs as a standalone stack (FastAPI, LangGraph, MongoDB, Next.js) with the Claude API as its only model provider.

Status: a working POC for five supplied projects, exercised with live runs from the console. Record of decisions in [DECISIONS.md](DECISIONS.md), session-by-session state in [PROGRESS.md](PROGRESS.md), the build plan in [MASTER.md](MASTER.md).

---

## 1. Problem statement

Buyers researching a project find its reviews scattered across property portals (MagicBricks, 99acres, Housing.com, NoBroker), Quora, Reddit, YouTube comments and Instagram, mixed with brochure language, dealers' listings and reviews of other projects with similar names. A portal page lists several people's reviews as one block; a YouTube comment thread mixes owners, agents and bystanders; the same project is "DLF Privana", "Privana South" or "Privana by DLF".

What is needed is a system that:

- finds the pages, videos and threads that are about **this** project and not another with a similar name or the same developer;
- splits them into **one record per person's review**, with the author's own words, the platform, the date and the author's role as the platform badges it (owner, resident, agent), never a name;
- tags every review with the product's **review categories** (builder reputation, construction and specifications, unit layouts and livability, amenities and common areas, maintenance and facility management, safety and security, location and connectivity, value for money, investment potential, pricing);
- puts **every** review, positive and negative, agents' and residents' alike, in front of a moderator to accept or reject, and never lets a model approve or publish anything;
- publishes only an **exact, immutable, approved revision**, traceable from every published sentence back to the source, and takes it down when the evidence behind it is withdrawn;
- does all this within **each source's terms** (robots.txt recorded for every page, no logins, no paywall or bot-protection bypass, no private groups) and within explicit **budgets** for paid providers and the model.

## 2. Solution

A managed multi-agent workflow, the "master model", coordinates deterministic connectors, Claude model calls, an evidence store and human decisions. Nothing a model writes is a fact until a person has reviewed it, and nothing is published that does not resolve to reviewed records.

The flow a project goes through:

1. **Run.** A researcher starts a run from the console. Collection jobs search the project's name, every approved alternate name and, for each, one search per review category, through Brave, Firecrawl search and YouTube; the web reader reads only pages whose title or address names the project, review pages first; Reddit, Instagram and the state RERA registry run as their own sources.
2. **Read reviews.** Portal and Quora pages are split into one record per review by the site's own markup. The identity matcher decides which project each page is about (the page's title and address are its subject). The review curator (A11) proposes every passage in which a person gives a view of the project, keeping the author's words and tagging the categories it speaks to.
3. **Decide.** A moderator accepts or rejects each review in the console, filtered by status and category. Agents' reviews and sales talk are shown and marked, not hidden.
4. **Build the page.** The moderator picks up to 20 approved reviews of 20 to 80 words; the page is built deterministically, balanced between positive, negative and mixed, labelled "Person 1", "Person 2"… with no credit line, no intro and no site name on the page.
5. **Approve and publish.** A publisher approves the exact revision by its payload hash, then publishes it; delivery to the public page is verified. An edit is a new revision needing a new approval. Withdrawn evidence disables serving until a new revision is approved.
6. **Refresh and recover.** Sources are re-checked for deletion; runs, jobs and model calls are persisted with leases, fencing and idempotency, so a crash or a stopped analysis is continued from its checkpoint, never redone or double-paid.

## 3. Technical architecture

```
                 ┌──────────────────────────────────────────────────────────────────┐
                 │                       web/ (Next.js 16)                          │
  moderators ───▶│  /console  moderator console          /projects/{slug} public   │◀─── readers
                 └───────────────┬──────────────────────────────┬──────────────────┘
                                 │ HTTP (session cookie, CSRF)   │ public read
                 ┌───────────────▼──────────────────────────────▼──────────────────┐
                 │                   backend/app/api (FastAPI)                      │
                 │  53 operations from contracts/v1/routes.json, roles enforced     │
                 └───────────────┬──────────────────────────────────────────────────┘
                                 │ persisted jobs (leases, fencing, idempotency)
   ┌─────────────────────────────▼───────────────────────────┐   ┌───────────────────┐
   │  worker(s): collect / analyse / resume / recheck jobs   │   │ scheduler: sweeps, │
   │  LangGraph analysis graph with the MongoDB checkpointer │   │ holds, freshness   │
   └──────┬──────────────────────┬───────────────────────────┘   └───────────────────┘
          │ connectors           │ model gateway (Anthropic SDK)
   ┌──────▼──────────────┐   ┌───▼───────────────────────┐    ┌────────────────────┐
   │ Brave, Firecrawl    │   │ Claude: A01 identity,     │    │ embedder (bge-m3,  │
   │ search+render, web  │   │ A05 claims, A06 verify,   │    │ local, int8) and    │
   │ reader, Scrapfly,   │   │ A07 findings, A11 reviews │    │ media worker        │
   │ YouTube, Reddit,    │   │ (A08/A09 in full mode)    │    │ (captions, whisper) │
   │ Instagram, RERA     │   └───────────────────────────┘    └────────────────────┘
   └──────┬──────────────┘
          ▼
   ┌─────────────────────────────────────────────────────────────────────────────────┐
   │ MongoDB 8 (single-node replica set): sources, payloads, links, evidence, claims, │
   │ findings, review excerpts, content revisions, publication state, runs, jobs,    │
   │ audit events, spend ledger. Collection validators derived from contracts/v1.    │
   └─────────────────────────────────────────────────────────────────────────────────┘
```

Principles enforced in code, not in prompts:

- **Contracts first.** Every record, API operation and agent output has a JSON Schema in `contracts/v1/`; MongoDB validators, the OpenAPI document and the console's TypeScript types are generated from them. A content revision's payload is frozen JSON and hashed (RFC 8785 canonical form).
- **Models propose, people decide.** Models cannot approve, publish, change source entitlements or grant themselves tools. Source content is untrusted data in every prompt.
- **Evidence lineage.** A published review resolves to a review excerpt, its evidence spans (code-point anchors into the stored source text, with hashes), the source revision and the policy it was collected under.
- **Honest failure.** A model task that is cut off, invalid or refused is split down to single passages; what still fails is skipped and reported; anything else stops the run so it can be continued from its checkpoint. Coverage shows what was and was not read.
- **Budgets.** A monthly ledger per paid provider (Brave, Firecrawl, Scrapfly, YouTube) reserves credits before each request and settles with what the provider reports; a model spend ledger with holds caps the total and each run.

## 4. Backend (`backend/`)

Python 3.13, FastAPI, Pydantic 2, PyMongo, LangGraph with `langgraph-checkpoint-mongodb`, the Anthropic Python SDK, Trafilatura for page extraction, `uv` for the environment. Versions are pinned in `backend/uv.lock`.

| Package | What it holds |
|---|---|
| `app/api` | FastAPI routers, one per area (`routes_runs.py`, `routes_findings.py` (reviews too), `routes_content.py`, `routes_publication.py`, `routes_identity.py`, `routes_sources.py`, `routes_policies.py`, `routes_admin.py`, `routes_ops.py`, `routes_corrections.py`, `routes_webhooks.py`, `routes_auth.py`), auth dependencies, idempotency keys |
| `app/auth` | Session cookies, CSRF, Argon2 passwords, roles (admin, researcher, moderator, publisher, analyst) |
| `app/sources` | Collection runner (`collection.py`), source storage and revisions (`store.py`), per-source policies (`policies.py`), HTTP client with per-host pacing and retries (`http.py`), robots.txt cache, provider quotas, deletion re-checks and source lifecycle |
| `app/connectors` | Brave search, Firecrawl search and page rendering, the web reader with the portal review splitters (`portal_reviews.py`), Scrapfly, YouTube Data API, Reddit through PullPush, Instagram public posts, the Haryana RERA registry and other state registries; `registry.py` builds each from its credential |
| `app/identity` | Deterministic project matching (`matching.py`: names, aliases, RERA IDs, place and developer context, the page's subject), the search query plan (`queries.py`), the A01 identity agent for ambiguous cases, evidence spans for links |
| `app/evidence` | Anchors, eligibility (computed, never stored), origin clusters (the same post on several sites), retrieval (keyword and bge-m3 embeddings), lineage checks |
| `app/agents` | The model gateway (`gateway.py`: structured outputs, caching, holds, timeouts, cost), A05 claims, A06 verification, A07 findings, A11 review curator, the D27 construction-status consistency rules, the spend ledger |
| `app/workflows` | The LangGraph analysis graph (`analysis.py`), decisions, revisions, verification |
| `app/content` | Page building from approved reviews (`build.py`), A08 editor and A09 QA for the full mode, hashing, the content service (generate, edit, approve) |
| `app/publication` | Activation, delivery verification, rollback, withdrawal handling |
| `app/media` | Captions, audio fetch, local transcription (faster-whisper), frames, language detection and translation windows, run in the isolated media worker |
| `app/embeddings` | The bge-m3 int8 embedding server and its client |
| `app/jobs`, `app/workers`, `app/scheduler` | The persisted job queue (leases, fencing, cancellation, recovery), the worker loop with heartbeats, and the scheduler (sweeps, stale holds, freshness) |
| `app/seed`, `app/setup` | Project catalogue import and registry sync, users, idempotent database setup (collections, validators, indexes) |
| `app/cli.py` | Operational commands: `setup-db`, `sync-catalogue`, `seed-*`, `smoke-model`, `plan-queries`, `collect`, `analyse`, evaluations |

**Analysis graph** (`workflows/analysis.py`), one thread per run, checkpointed in MongoDB:

```
START ─▶ reviews ─▶ conclude ─▶ review (interrupt: waits for the moderator)
                                   │
         selected ◀────────────────┘  (the moderator's selection arrives as a resume job)
            │
          format ─▶ END          (reviews-only mode, the default, D68)

START ─▶ claims ─▶ findings ─▶ reviews ─▶ conclude ─▶ …   (full mode, with A05/A06/A07)
```

The interrupt releases the worker: a paused run holds no process. A `resume_after_review` job continues the thread with the moderator's exact selection, checked again when it runs.

**Tests.** 470+ pytest tests on a real MongoDB replica set with a fake internet (`tests/fakenet.py`) and a scripted model: no test reaches the network or a paid provider. `ruff` and `mypy` in strict mode. Contract checks (`scripts/check_contracts.py`, 13 sections) and input validation run in CI.

## 5. Frontend (`web/`)

Next.js 16 App Router, React 19, TypeScript, Tailwind v4, server components reading the API with the session cookie; Playwright journeys; Vitest unit tests. The API's types are generated from `contracts/v1/openapi.json` into `lib/api-schema.d.ts`.

**Moderator console** (`/console`, sign-in required):

| Screen | What it does |
|---|---|
| Portfolio | Every project with its next step (run, approve reviews, build the page, approve and publish), the latest run's sources with live progress, pending decisions, page state, spend |
| Project → Runs | Start a run (sources as people think of them, look-back window; a run asks before spending), the project's runs with per-source coverage |
| Run page | A stepper, headline numbers, a card per source with its live note, progress bar and counts; stop and continue banners (budget, model access, failure) |
| Project → Reviews | One card per review: the author's words, platform, date, role badge, categories, the original beside a translation, the evidence spans; approve, reject, request changes, edit as a new revision; filter by status and category |
| Project → Page | Build the page from approved reviews (balanced selection, word limits), the revision list, the editor (a material edit is a new revision), the preview, final approval by payload hash, publish |
| Project → Publishing, Sources, Videos, Findings, Setup | Publication operations and rollback; linked sources with their match rationale; videos and transcripts; findings (full mode); aliases, enabled sources, negative keywords |
| Corrections, Operations, Administration | Reader corrections; connector health and quotas, jobs; users and roles, source policy versions, the audit record |

**Public page** (`/projects/{slug}`): the approved review list as "Person N" entries in the authors' words with their categories, structured data, and a correction form. It serves only an active approved revision and says plainly when nothing is published.

## 6. Repository layout

```
.
├── backend/                  Python service (see section 4)
│   ├── app/                  api, auth, sources, connectors, identity, evidence, agents,
│   │                         workflows, content, publication, media, embeddings, jobs,
│   │                         workers, scheduler, seed, setup, cli.py, config.py
│   ├── tests/                pytest suite, fake internet, scripted model, journey seed
│   ├── Dockerfile, Dockerfile.media, Dockerfile.embed
│   └── pyproject.toml, uv.lock
├── web/                      Next.js console and public page (see section 5)
│   ├── app/                  console/(app)/…, console/login, projects/[slug], api/revalidate
│   ├── components/           shared UI (cards, status chips, source cards, stepper, dialogs)
│   ├── lib/                  API client, flow rules, formatting, generated API types
│   └── e2e/                  Playwright journeys
├── contracts/v1/             JSON Schemas (common, api, agents, evidence, content, sources,
│                             operations, publication, catalogue), routes.json, openapi.json,
│                             state_machines.json, content_rules.json, journeys.json, fixtures/
├── prompts/                  versioned prompt templates per agent (a01…a11, immutable once published)
├── seed/                     connectors.json (registry), source_policies.json, operating_defaults.json
├── evals/                    labelled evaluation sets (identity, agents, retrieval, media)
├── scripts/                  contract tools, fixture and OpenAPI generation, step check scripts
├── docs/                     01 architecture … 11 moderator guide
├── steps/                    the 14 work packages of the build plan
├── logs/                     check and journey logs per step (no secrets, no source text)
├── docker-compose.yml        MongoDB, api, worker, media-worker, embedder, scheduler, web
├── Makefile                  every command (make help)
├── MASTER.md, PROGRESS.md, DECISIONS.md, CHANGELOG.md
└── .env.example              configuration contract; .env is never committed
```

## 7. Agent orchestration and the agents

The coordinator (A00) is not a model: it is the job queue, the LangGraph graph and the scheduler. It decides the next state from persisted facts, never from a model's say-so. Each model agent has a prompt version, a schema for its output (Claude structured outputs), a cache key, a cost record and backend checks on everything it returns.

| Agent | Role | How it runs |
|---|---|---|
| A00 Master coordinator | Dispatches jobs, checkpoints, coverage, budgets, state transitions | Deterministic: `jobs/queue.py`, `workflows/analysis.py`, `scheduler/main.py` |
| A01 Project identity | Decides whether an ambiguous page is about this project, proposes alternate names for approval | Claude, only when the deterministic matcher sends a page to review; capped per run |
| A02 Discovery planner | The bounded search plan: review-site queries, name queries, category queries per name | Deterministic: `identity/queries.py` (no model) |
| A03 Video understanding | Timestamped observations from captions, audio and frames | Local models in the media worker; Claude for frame descriptions (full mode) |
| A04 Language and context | Language detection, Hindi and Hinglish translation windows, original kept beside the translation | `media/language.py`, `media/translate.py` |
| A05 Claim extractor | Atomic claims with evidence IDs, polarity, perspective, category | Claude, full mode only |
| A06 Evidence verifier | Claims checked against RERA records and nearby evidence | Claude plus deterministic rules, full mode only |
| A07 Findings synthesiser | Pros and cons with exact claim references and caveats | Claude, full mode only |
| A08 SEO/AEO editor | Page copy from approved findings | Claude, full mode only; the reviews-only page is built deterministically |
| A09 Editorial QA | Blocking and non-blocking issues on a draft | Claude plus deterministic rules |
| A10 Freshness reviewer | What changed since the approved manifest; invalidation | Deterministic: `sources/recheck.py`, `sources/lifecycle.py`, `evidence/eligibility.py` |
| A11 Review curator | Every passage in which a person gives a view of the project, in the author's words, with category, polarity and perspective; agents' views and sales talk marked, not hidden | Claude (Haiku by default), one task per bucket of sources, split on cut-off answers |

Rules the backend applies to every A11 proposal: the spans must exist and belong to the cited source; a verbatim rendering must equal the spans, a normalised one keep every word, a shortened one drop whole sentences only, a translation come from a non-English original and add no number; no phone numbers or e-mail addresses; a reviewer's name is never stored or shown; the credit comes from the author's perspective and the platform's badge; the D27 consistency flags block approval of impossible claims (first-hand living in a project before possession).

## 8. Sources and policies

Each connector is `access_pending` until its credential is configured in `.env` and a real call is recorded (`seed/connectors.json`). In runs today: Brave search, Firecrawl search and page rendering, the web reader (portals, Quora, forums, the open web by allow-list), Scrapfly for pages that refuse the reader (competitor portals), YouTube Data API (videos and comments), Reddit through the PullPush archive (no account), Instagram public posts through Scrapfly, the Haryana RERA registry. Pending: spoken video transcripts (blocked by the office network), X, Meta, LinkedIn, a social listening provider.

Every source family has a versioned policy (`seed/source_policies.json`, immutable versions, console-managed): whether collection, model use, quotation and derived publication are allowed, which hosts, retention. The web reader asks and records robots.txt for every page; it never logs in, never bypasses a paywall or bot protection, never reads private groups. Reviewer names are never kept.

## 9. Running it locally

Needs Docker with Compose v2, [uv](https://docs.astral.sh/uv/), pnpm (`corepack enable`), Node.js 24+ and Python 3.10+ for the scripts. Give the Docker VM at least 6 GB.

```sh
make install          # backend (uv), web (pnpm), contract tools
make up               # creates or completes .env, builds and starts the stack, waits until healthy
make seed             # the five projects, policies and the seeded users
open http://localhost:3000/console
```

Keys go in `.env` (never committed): `ANTHROPIC_API_KEY`, `BRAVE_SEARCH_API_KEY`, `FIRECRAWL_API_KEY`, `SCRAPFLY_API_KEY`, `YOUTUBE_API_KEY`; budgets `MODEL_BUDGET_USD` (total) and `RUN_BUDGET_USD` (per run); model IDs `MODEL_ROUTINE`, `MODEL_REASONING`, `MODEL_DIFFICULT`. A run spends credits and asks before starting. `make help` lists every command; `make test`, `make lint`, `make typecheck`, `make journeys` and `make check-step09-10` run the checks that CI runs.

Operational notes: a database restore must be followed by `docker compose exec api python -m app.cli sync-catalogue` (it re-seeds policies and each project's sources); MongoDB runs with `minSnapshotHistoryWindowInSeconds=5` so the test suite's dropped tables do not slow it down; backups are `mongodump` archives under `backups/` (git-ignored).

## 10. Documentation map

| Need | Read |
|---|---|
| Scope, rules, release gates | [MASTER.md](MASTER.md), [AGENTS.md](AGENTS.md) |
| Why things are the way they are | [DECISIONS.md](DECISIONS.md) (D01–D77), [CHANGELOG.md](CHANGELOG.md) |
| Where the work stands | [PROGRESS.md](PROGRESS.md), `logs/` |
| Architecture and stack | [docs/01](docs/01-architecture-and-stack.md) |
| Database and contracts | [docs/02](docs/02-database-and-contracts.md), `contracts/v1/README.md` |
| API and console actions | [docs/03](docs/03-api-and-cms-contracts.md) |
| Agents and the model gateway | [docs/04](docs/04-agent-contracts.md), `prompts/README.md` |
| Approval, publication, recovery | [docs/05](docs/05-workflow-and-publication.md) |
| Connectors and scraping rules | [docs/06](docs/06-source-integrations.md) |
| Validation and release | [docs/07](docs/07-validation-and-release.md) |
| Editorial rules, screens, journeys | [docs/08](docs/08-editorial-and-ui.md), [docs/09](docs/09-screen-specifications.md), [docs/10](docs/10-journeys-and-states.md) |
| Using the console | [docs/11](docs/11-moderator-guide.md) |

Original planning material is preserved unchanged under `reference/`.

## License

Proprietary. Copyright (c) 2026 deepeshgupta12, all rights reserved; see [LICENSE](LICENSE).
