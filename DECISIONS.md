# Inputs and decision register

Initial state: no code, no credentials and no real five-project values yet. Keep secrets outside this document; record references to secret locations (`.env`, GitHub Actions secrets), never values.

## Confirmed scope and architecture decisions

| ID | Decision | Status |
|---|---|---|
| D01 | Exactly five initial projects with name, alternate names, locality, city; micromarket optional | Confirmed by user (25 Sep 2026) |
| D02 | Standalone POC: no read or write dependency on any existing the client system (MongoDB, CMS, website) | Confirmed by user |
| D03 | Fresh GitHub repository; one repo with `backend/` (Python) and `web/` (TypeScript); developed in VS Code/Visual Studio with Claude Code; GitHub Actions for CI | Confirmed by user |
| D04 | One complete release; all core capabilities included | Confirmed by user |
| D05 | Cloud provisioning/migration excluded; Docker Compose on any team machine or VM; hosting deferred. Obtaining provider API keys is in scope | Confirmed by user |
| D06 | Source API access and scraping adapters are obtained incrementally during the build; connectors move from `access_pending` to live one at a time | Confirmed by user |
| D07 | Claude API (Anthropic Python SDK) is the only LLM provider | Confirmed by user |
| D08 | Own MongoDB via Docker Compose as a single-node replica set (transactions and change streams available). Publication integrity uses a single project/locale control document with compare-and-set as the core mechanism; a transaction couples the control document with the publication operation record. See docs/05 | Proposed technical design |
| D09 | Own moderator console and public project page in one Next.js app (`web/`): `/console/*` authenticated, `/projects/[slug]` public and server-rendered. Own authentication: seeded users, hashed passwords, signed session cookie issued by the backend, roles enforced server-side | Proposed technical design |
| D10 | Model roles: routine + reasoning/editorial → `claude-sonnet-5`; difficult-case review → `claude-opus-5-5`; optional cost downgrade of routine work to `claude-haiku-4-5-20251001` after evaluation (note its retirement date is not sooner than 15 Oct 2026). `claude-fable-5-1` only if Opus evaluations fall short. IDs live in config and are re-verified at Step 03 against https://platform.claude.com/docs/en/models/overview | Proposed; verify against account |
| D11 | Structured outputs via the Claude API JSON-schema output format (`client.messages.parse()` with Pydantic) for extraction/synthesis agents; strict tool use for tool-calling agents; prompt caching for repeated evidence context; Message Batches API for bulk offline classification | Proposed technical design |
| D12 | Speech-to-text: local `faster-whisper` on authorised media only. Embeddings: keyword/filter baseline first, then local `BAAI/bge-m3` as a measured addition; Voyage AI is the hosted alternative if local quality/latency is insufficient | Proposed technical design |
| D13 | Human findings review plus final exact-wording approval; LangGraph + MongoDB checkpointer; durable MongoDB jobs | Proposed design from master plan |
| D14 | Public page is a POC renderer. Its payload contract (`ai_content_revisions` payload + JSON-LD proposal) is the future integration surface for the real project detail page; that integration is out of scope | Proposed technical design |
| D15 | Project inputs come from the the client project export. Mapping: `SublocationName` → `locality` (e.g. Sector 76), `Locationname` → `micromarket` (e.g. New Gurgaon), `Cityname` → `city`. The export's project/city/location/sublocation IDs and `ProjectStatusDesc` go in an optional `client_ref` object; `client_ref.project_id` seeds the reserved `projects.client_id`. Status is construction status, not `phase`, and is an external reference only (not evidence, not published). Spellings kept as supplied ("Gurgaon"); "Gurugram" belongs in search aliases at Step 04 | Proposed (25 Sep 2026) |
| D16 | A township or multi-phase project (DLF Privana: South/West/North; M3M Antalya Hills: Phase 1/II/3 plus Commercial-01) is one POC project. `rera_ids` holds `{id, registered_name}` per registration so phase identity is preserved; Step 04 uses registered names as search forms and phase signals, and A06 cites the matching registration. RERA IDs are stored as supplied (full `RC/REP/HARERA/GGM/...` for DLF Privana, short `GGM/...` elsewhere); a normalised form is derived at Step 04. The baseline schema's `rera_references` (string list) takes the `id` values | Proposed (25 Sep 2026) |
| D17 | Alternate-name and phase-name discovery is added to the existing A01 Project identity agent, not a new agent. A01 proposes names found in evidence; the backend checks a strong identifier and collisions; a researcher/moderator approves each alias (standalone or context-required) before search or matching uses it. New `ai_alias_proposals` collection and two endpoints. Specs updated: docs/02, 03, 04, 07, 08; steps 04 and 09 | Requested by user (25 Sep 2026) |
| D18 | Delivery workflow: private GitHub repo `deepeshgupta12/agentic_ai_review_model`; every commit is pushed straight to `main` (replaces MASTER's one-branch-per-step suggestion). Each step ends with use-case tests and bash commands for the user; the next step starts only after the user approves. Command output for each step is committed under `logs/step-NN/` | Confirmed by user (25 Sep 2026) |
| D19 | Slug and ID convention. Slug: lower-kebab ASCII of project name + locality + city (name first for readable URLs, e.g. `dlf-privana-sector-76-gurgaon`), accents folded, at most 80 characters cut at a word boundary. A duplicate slug fails validation as a probable duplicate project. The slug is generated at first import and stored; later imports never regenerate it, and renaming is an explicit admin action. Project ID: `prj_` + ULID generated at first import and persisted; re-import matches an existing record by `client_ref.project_id` when present, otherwise by normalised name + city. Search forms: NFKC, case-folded, punctuation to spaces, letters/digits/combining marks kept (Devanagari intact); originals are never changed. RERA IDs compare in short form (`RC/REP/HARERA/` removed) | Proposed (25 Sep 2026) |
| D20 | Step 01 seed data lives in `seed/` (`connectors.json`, `source_policies.json`, `operating_defaults.json`), a directory added to the docs/01 layout; Step 03 seed scripts load it. Until Step 03 pins the toolchain, checks are standard-library Python: `scripts/validate_inputs.py` with `unittest` tests in `scripts/tests/` (pytest can run them later unchanged). Step 04 moves the slug/normalisation functions into the backend with the same test cases. MANIFEST.json stays the v1.1 delivery snapshot; git history is authoritative from commit `e197ab9` | Proposed technical design |

## Inputs to resolve during implementation

| ID | Input/decision | Initial state | Owner | Work affected |
|---|---|---|---|---|
| I01 | Five real project input records (name, alternate names, locality, city; micromarket optional) | All 5 supplied 25 Sep 2026 (DLF Privana, Conscient Parq, Sobha Crescent, M3M Forestia West, M3M Antalya Hills; all Gurgaon). Developers and RERA registrations supplied the same day (D16). Alternate names still open | Product owner | Step 01 registration, discovery, evaluation |
| I02 | Anthropic API key and rate limits for the account; confirm model IDs in D10 are available | Pending; registry row `anthropic` (acquisition order 1) | Product owner | Step 03 gateway check, Step 08 evaluation |
| I03 | Source credentials, obtained incrementally: suggested order Brave Search → Firecrawl → YouTube Data API → others (Reddit/X/Meta/listening provider) | None yet; order, `.env` names and go-live demonstrations in the connector registry below | Product owner | Steps 05/06 live gates |
| I04 | Mandatory vs optional source list for the POC demo | Proposed 25 Sep 2026: mandatory = Anthropic, Brave, YouTube, and one of Firecrawl/Playwright; all others optional (`seed/connectors.json`). Awaiting approval | Product owner | Release scope |
| I05 | Transcript/media acquisition policy for third-party videos (creator-supplied, licensed, or none) | Open. The `spoken_video_content` policy blocks collection until decided | Product owner | Step 06 live gate |
| I06 | Initial source policy set per platform (collection, AI processing, quotation, derived publication, retention) | Proposed 25 Sep 2026 for 10 families in `seed/source_policies.json`; families needing an agreement are blocked. Awaiting terms review and approval | Product owner + implementer | Eligibility everywhere |
| I07 | Input languages and output locale | Proposed en/hi/hi-Latn → en-IN (`seed/operating_defaults.json`). Awaiting approval | Product owner | Models/evaluations |
| I08 | Refresh cadence and history window | Proposed daily incremental + manual, 90 days, shown in IST. Awaiting approval | Product owner | Jobs/quotas |
| I09 | Seeded users and role assignment | Five roles proposed; seeded users open | Product owner | Step 03 auth |
| I10 | Retention, withdrawal SLA and cache-removal behavior | Retention per source policy and 60-minute withdrawal SLA proposed; correction owner open | Product owner | Lifecycle and serving |
| I11 | Quality targets, dataset labels and moderator capacity | Proposed in the acceptance definitions below; moderator capacity open | Product owner | Release acceptance |
| I12 | Where Docker Compose runs for the demo (developer machine vs shared VM) | Open | Product owner | Steps 13/14 |
| I13 | Versioned production schemas and canonical payload algorithm | Required Step 02 work | Implementer | Cross-layer correctness |
| I14 | Page content voice, lengths, JSON-LD types and correction route | `noindex` public page proposed; voice and lengths at Step 10 | Product owner | Final payload |
| I15 | Console/page visual design direction (produced in-repo; no external design system) | Step 02 work | Product owner + implementer | Step 09/11 UI |

None of these unknowns authorises the coding assistant to invent production values. Interfaces and synthetic fixtures can be built while live dependencies remain open.

## Connector registry

Summary of [seed/connectors.json](seed/connectors.json), which holds the full fields (content kinds, expected capabilities, quota, cursor and deletion method, last verification). Per-family rights are in [seed/source_policies.json](seed/source_policies.json). Credentials live in `.env` locally and in GitHub Actions secrets for CI; only variable names are recorded. `scripts/validate_inputs.py` fails if a row is missing or shows a different status from the JSON.

| Connector | Provider | Policy family | Demo requirement (I04, proposed) | Credential (`.env`) | Demonstration to go live | Status |
|---|---|---|---|---|---|---|
| `anthropic` | Anthropic Claude API (model provider) | n/a | Mandatory | `ANTHROPIC_API_KEY` | One real structured-output call via `scripts/smoke_model.py` (Step 03) | access_pending |
| `brave_search` | Brave Search API | web_public_pages | Mandatory | `BRAVE_SEARCH_API_KEY` | Real query for a supplied project returns results | access_pending |
| `firecrawl` | Firecrawl | web_public_pages | One of `web_extraction` | `FIRECRAWL_API_KEY` | Fetch one allow-listed page found by Brave, robots decision recorded | access_pending |
| `playwright_fetch` | Playwright (local) | web_public_pages | One of `web_extraction` | none (host allow-list) | Render one allow-listed page found by Brave, robots decision recorded | access_pending |
| `youtube_data_api` | YouTube Data API v3 | youtube | Mandatory | `YOUTUBE_API_KEY` | Real search returns a video; one comments page or comments-disabled status | access_pending |
| `harera_registry` | Haryana RERA public registry | official_records | Optional | none (public site) | Fetch the record for one supplied RERA ID | access_pending |
| `spoken_video_transcripts` | Undecided (I05) | spoken_video_content | Optional | depends on route | Permitted transcript processed with original timing (Step 06) | access_pending |
| `reddit_api` | Reddit Data API | reddit | Optional | `REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET` | Approved access confirmed; real search returns posts | access_pending |
| `x_api` | X API | x | Optional | `X_BEARER_TOKEN` | Entitled tier confirmed; real search | access_pending |
| `meta_graph_api` | Meta approved endpoints | meta | Optional | `META_ACCESS_TOKEN` | Each promised capability shown with an approved app | access_pending |
| `listening_provider` | Social listening provider (not selected) | listening_provider | Optional | `LISTENING_PROVIDER_API_KEY` | Contract names platforms; real query returns items | access_pending |

## Release acceptance definitions (proposed, Step 01)

Proposed for product-owner approval. Targets come from [validation and release](docs/07-validation-and-release.md); nothing here has been measured. All capabilities ship together in one tagged release (D04); there are no staged product launches.

| Gate | Proposed target | Measured how | Sign-off |
|---|---|---|---|
| Scope | 14 steps complete; the five registered projects; one release | PROGRESS ledger with evidence for each step | Product owner |
| Source access | Mandatory set (I04) live; optional sources shown as unavailable | Recorded real query per connector (registry above) | Product owner |
| Dataset | 150–300 authorised items across the five projects if chatter allows; a shortfall is reported, never padded | Versioned evaluation manifest (Step 12) | Product owner + implementer |
| Identity | ≥98% precision on auto-accepted matches; recall, ambiguity and alias-proposal precision reported | Labelled held-out project/segment pairs, per project and language | Implementer; reviewed by product owner |
| Retrieval | ≥90% recall@10 per launch language | Labelled evidence queries | Implementer |
| Grounding | Every published substantive statement traces to eligible evidence; ≥95% draft support | Automated reference check plus human audit sample | Product owner (editorial) |
| Critical errors | Zero known critical unsupported claims | Audit of the acceptance sample | Product owner (editorial) |
| Approvals | Every publish attempt without approval of the exact current revision/hash is rejected | docs/05 race tests | Implementer |
| Recovery | No duplicate publication or lost decision after crash/timeout drills | Step 11/12 drills | Implementer |
| Refresh | ≥95% of scheduled jobs run within the agreed window | Job records over the measurement period | Implementer |
| Page delivery | Verified rendered revision within 5 minutes in the Compose environment | Publication operation timestamps | Implementer |
| UI | p95 common reads under 2 s at documented concurrency | k6 run on a realistic corpus | Implementer |
| Editorial capacity | Review workload fits named moderator capacity (capacity open, I11) | Measured review minutes | Product owner |
| Security | All blocking findings closed | Step 12 security report | Product owner + implementer |

## Decision entry template

```text
Decision ID / date:
Question:
Evidence inspected (docs, tests, measurements):
Selected option and reason:
Owner / authority:
Affected contracts, steps and files:
Compatibility or migration implications:
Validation performed / remaining:
Status: proposed | accepted | superseded | blocked
```

Maintain a version matrix here or in a linked repository file for runtimes, packages, model IDs, prompt/schema revisions and MongoDB version. Planning version names are not installation instructions until checked and pinned.
