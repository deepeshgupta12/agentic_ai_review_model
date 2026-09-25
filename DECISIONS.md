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

## Inputs to resolve during implementation

| ID | Input/decision | Initial state | Owner | Work affected |
|---|---|---|---|---|
| I01 | Five real project input records (name, alternate names, locality, city; micromarket optional) | All 5 supplied 25 Sep 2026 (DLF Privana, Conscient Parq, Sobha Crescent, M3M Forestia West, M3M Antalya Hills; all Gurgaon). Developers and RERA registrations supplied the same day (D16). Alternate names still open | Product owner | Step 01 registration, discovery, evaluation |
| I02 | Anthropic API key and rate limits for the account; confirm model IDs in D10 are available | Pending | Product owner | Step 03 gateway check, Step 08 evaluation |
| I03 | Source credentials, obtained incrementally: suggested order Brave Search → Firecrawl → YouTube Data API → others (Reddit/X/Meta/listening provider) | None yet | Product owner | Steps 05/06 live gates |
| I04 | Mandatory vs optional source list for the POC demo | Unconfirmed | Product owner | Release scope |
| I05 | Transcript/media acquisition policy for third-party videos (creator-supplied, licensed, or none) | Unconfirmed | Product owner | Step 06 live gate |
| I06 | Initial source policy set per platform (collection, AI processing, quotation, derived publication, retention) | Required Step 01 work | Product owner + implementer | Eligibility everywhere |
| I07 | Input languages and output locale | Proposed en/hi/hi-Latn → en-IN | Product owner | Models/evaluations |
| I08 | Refresh cadence and history window | Proposed daily/manual and 90 days | Product owner | Jobs/quotas |
| I09 | Seeded users and role assignment | Unknown | Product owner | Step 03 auth |
| I10 | Retention, withdrawal SLA and cache-removal behavior | Unconfirmed | Product owner | Lifecycle and serving |
| I11 | Quality targets, dataset labels and moderator capacity | Proposed in validation spec | Product owner | Release acceptance |
| I12 | Where Docker Compose runs for the demo (developer machine vs shared VM) | Unknown | Product owner | Steps 13/14 |
| I13 | Versioned production schemas and canonical payload algorithm | Required Step 02 work | Implementer | Cross-layer correctness |
| I14 | Page content voice, lengths, JSON-LD types and correction route | Unconfirmed | Product owner | Final payload |
| I15 | Console/page visual design direction (produced in-repo; no external design system) | Step 02 work | Product owner + implementer | Step 09/11 UI |

None of these unknowns authorises the coding assistant to invent production values. Interfaces and synthetic fixtures can be built while live dependencies remain open.

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
