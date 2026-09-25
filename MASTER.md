# Agentic Project Intelligence: master build guide

**Version:** coding handoff 1.1, 25 September 2026 (supersedes 1.0 — see CHANGELOG.md). **Delivery:** one complete release for five projects. **Implementation status:** not started. The documents and reference JSON exist; the application has not been built.

## Outcome

Build a standalone system that collects authorised discussion and identifies relevant videos/shorts for five the client projects, analyses permitted content, creates evidence-linked pros and cons, presents findings in a moderator console, formats approved findings for SEO/AEO, obtains approval of the final wording, and displays that exact content on a public project page served by the same system. Include freshness, correction, withdrawal, monitoring and recovery in the same release.

The "Master Model" is a managed multi-agent workflow. It coordinates Claude API calls, deterministic connectors, evidence stores and human decisions. This POC does not require training a model or a separate microservice for every agent.

## Confirmed constraints (revised 25 September 2026)

1. The POC covers **five projects**. Required user fields are project name, alternate names, locality and city; micromarket is optional. The user supplies these in `contracts/five-project-input-template.json`.
2. **No dependency on existing the client systems.** The POC owns its MongoDB, its project catalogue (seeded from the input file), its moderator console and its public page renderer. Nothing reads from or writes to production the client infrastructure. The public page is designed as a drop-in module contract so it can be integrated into the real project detail page later, but that integration is out of scope.
3. **Fresh GitHub repository**, developed in VS Code (or Visual Studio) with Claude Code. Backend (Python) and web app (TypeScript) live in one repository. GitHub Actions is the CI system.
4. **Claude API is the model provider** (Anthropic Python SDK). No OpenAI dependency. Speech-to-text and embeddings, which the Claude API does not provide, use local open-source models by default (see architecture spec).
5. **One complete product release** includes collection, text/media analysis, evidence, agents, review, formatting, final approval, publication and operations. The steps below are engineering work packages.
6. **Cloud provisioning is excluded.** Everything runs from Docker Compose on any team machine or VM; hosting selection is deferred. Obtaining API keys from providers (Anthropic, Brave, Google/YouTube, Firecrawl, etc.) is not "cloud work" and is expected.
7. **Source access is obtained incrementally during the build.** Every connector starts as `access_pending` and moves to live only when a credential or contract exists and has been demonstrated. No connector may be described as supported before that. Scraping adapters are permitted only within the source-policy rules in the source-integrations spec.
8. Final publication requires an authenticated publisher's approval of the exact immutable content revision and current evidence eligibility. AI agents cannot approve themselves.

Provisional defaults: daily incremental plus manual refresh, 90-day initial discovery, English/Hindi/Hinglish input, English publication, seeded users holding admin/researcher/moderator/publisher/analyst roles (one person may hold several). Confirm and configure these in Step 01 rather than hard-coding them.

## Authority and changes from the original plan

The user's confirmed constraints take priority. This guide and the linked specifications resolve coding details; the [original complete plan](reference/original-master-plan.md) is preserved unchanged as background, and much of its "existing CMS / existing MongoDB / existing page" language is now historical. CHANGELOG.md lists the differences. Record further design changes in DECISIONS.md and update affected contracts/steps together.

- The original 20-project vendor trial is **not a POC requirement**. Use the five provided projects.
- Original runtime/library/model names were planning observations. Pin current supported versions after checking official documentation. Model IDs are configuration, verified against the actual Anthropic account.
- The original JSON is a **synthetic exchange example**, not a complete implementation schema. Step 02 versions the required extensions described in [database and contracts](docs/02-database-and-contracts.md).
- Freeze content payloads; keep mutable approval/delivery metadata outside them. A material edit requires a new approval.
- Separate source identity from project-segment associations, and approval/activation from verified page delivery.

## Recommended architecture and stack

One repository: `backend/` (Python 3.12+, FastAPI, Pydantic 2, PyMongo, LangGraph with the MongoDB checkpointer, Anthropic SDK model gateway) and `web/` (Next.js App Router, TypeScript, Tailwind, shadcn/ui, TanStack Query/Table, Zod, TipTap) serving both the moderator console (`/console/*`, authenticated) and the public project page (`/projects/[slug]`, server-rendered, reads only the active eligible revision). MongoDB runs as a single-node replica set in Docker Compose so transactions are available. Durable MongoDB jobs and deterministic publication services. Discovery through entitled direct/provider/search adapters; permitted media uses FFmpeg plus local Whisper transcription. Retrieval uses project/time/eligibility filters, a keyword baseline and bounded local-embedding ranking.

Do not add cloud infrastructure, a second database, or a second orchestration framework. See [architecture and stack](docs/01-architecture-and-stack.md).

## How to execute

1. Create the GitHub repository with this pack at its root. Open it in VS Code with Claude Code (the `CLAUDE.md` at the root imports `AGENTS.md`).
2. Read this guide, [PROGRESS.md](PROGRESS.md), [DECISIONS.md](DECISIONS.md) and the current step. Load only relevant shared specifications for that task.
3. Follow the numbered sequence by default. Establish contracts and test fixtures before dependent code.
4. Implement the active step and run its checks. Maintain the progress ledger with actual changed paths and results. Never call a mocked connector or model output a live integration.
5. If a credential is missing, record precisely what is blocked and continue independent work. Missing access does not authorise invention or silent scope removal.
6. Complete all steps and release gates, then release the complete product together. Per-project content publication still follows the console review workflow.

## Step files and dependencies

| Step | Implementation guide | Prerequisites |
|---|---|---|
| 01 | [Requirements, source access and acceptance definition](steps/01-requirements-and-access.md) | None |
| 02 | [UX, architecture and contracts](steps/02-ux-architecture-and-contracts.md) | 01 |
| 03 | [Engineering foundation and MongoDB setup](steps/03-foundation-and-mongodb.md) | 01, 02 |
| 04 | [Project catalogue and identity resolution](steps/04-project-identity.md) | 02, 03 |
| 05 | [Text and social collection](steps/05-text-and-social-connectors.md) | 02, 03, 04 |
| 06 | [Videos, shorts and multilingual processing](steps/06-video-and-language-processing.md) | 02, 03, 04, 05 |
| 07 | [Evidence storage, deduplication and retrieval](steps/07-evidence-and-retrieval.md) | 02, 03, 04, 05, 06 |
| 08 | [Agent development and master workflow](steps/08-agents-and-master-workflow.md) | 02, 03, 04, 05, 06, 07 |
| 09 | [Moderator console](steps/09-cms-moderation.md) | 02, 03, 04, 07, 08 |
| 10 | [SEO/AEO content and quality controls](steps/10-seo-aeo-and-editorial-qa.md) | 02, 07, 08, 09 |
| 11 | [Publication and public page](steps/11-publishing-and-recovery.md) | 02, 03, 07, 09, 10 |
| 12 | [Evaluation, security and capacity qualification](steps/12-evaluation-security-and-capacity.md) | 01–11 |
| 13 | [Operations, freshness and analytics](steps/13-operations-and-freshness.md) | 03, 05, 07, 08, 09, 11, 12 |
| 14 | [One complete five-project POC release](steps/14-single-release-and-handover.md) | 01–13 |

Recommended de-risking checkpoint: after Step 08, run one project through one live source (Brave or YouTube) to a console preview before starting Steps 09–11 in full. Record it in PROGRESS.md as a checkpoint, not a release.

## Shared specifications

| Document | Use |
|---|---|
| [Architecture and stack](docs/01-architecture-and-stack.md) | Repository layout, compatible stack, model provider, configuration. |
| [Database and contracts](docs/02-database-and-contracts.md) | Collections, baseline JSON gaps, immutable references, indexes and lifecycle. |
| [API and console contracts](docs/03-api-and-cms-contracts.md) | REST routes, authentication, roles, concurrency and page-renderer adapter. |
| [Agent contracts](docs/04-agent-contracts.md) | Master coordinator and 10 specialists with tools, outputs, limits and evaluation. |
| [Workflow and publication](docs/05-workflow-and-publication.md) | Jobs, leases, approval hashes, atomic publication, withdrawal and recovery. |
| [Source integrations](docs/06-source-integrations.md) | Incremental access plan, connector contract, scraping policy, media permissions. |
| [Validation and release](docs/07-validation-and-release.md) | Datasets, meaningful tests, numerical gates and full user acceptance. |
| [Editorial and console UI](docs/08-editorial-and-ui.md) | Console screens, content rules, SEO/AEO formatting and final preview. |

Additional files: [AGENTS.md](AGENTS.md), [CLAUDE.md](CLAUDE.md), [PROGRESS.md](PROGRESS.md), [DECISIONS.md](DECISIONS.md), [CHANGELOG.md](CHANGELOG.md), [project input template](contracts/five-project-input-template.json), [baseline exchange schema](contracts/client-data-contract.schema.json), [synthetic example](contracts/client-data-example.json).

## Non-negotiable implementation invariants

- Facts and opinions remain distinguishable; support and contradictions are preserved. No invented transcript, community consensus or forced balance.
- A source title/snippet is discovery metadata, not evidence for unanalysed spoken content.
- Every substantive published block resolves exact approved finding/claim/source revisions with current permissions.
- Unknown source date, uncertain project match or uncalibrated confidence stays unknown.
- Exact approved payload hash, expected state version and eligibility generation are validated by the backend at publication.
- Source deletion/policy withdrawal invalidates dependencies and affects serving eligibility; rollback cannot revive ineligible content.
- Worker leases/checkpoints do not guarantee exactly-once external behavior. Fencing, idempotency, persistent delivery intent and reconciliation are required.
- The public page reads an eligible active revision, never the latest draft, and never depends on a live model call.
- Secrets and raw personal/source content do not leak into public payloads, test repositories or operational traces.

## Release definition of done

All 14 packages complete; every mandatory source capability works through an entitled integration (or is honestly recorded as unavailable); five project records are loaded; console review/edit/reject and exact final approval work; page delivery is verified; correction, expiry, withdrawal, restart and rollback are demonstrated; quality and capacity targets are measured; runbooks exist. Insufficient chatter for a project is reported honestly and does not justify manufactured content.

The original 6–8 week estimate assumed a five-person team; it is not a promise for one or two people using a coding assistant.

## Ready-to-use bootstrap prompt

```text
Build the Agentic Project Intelligence POC described in MASTER.md.
This is a fresh standalone repository: our own MongoDB, our own project catalogue seeded
from contracts/five-project-input-template.json, our own moderator console and public
project page in web/, a Python FastAPI + LangGraph backend in backend/, and the Claude API
(Anthropic SDK) as the only LLM provider. No existing the client system is a dependency
and no cloud provisioning is in scope. Read AGENTS.md, PROGRESS.md, DECISIONS.md and
CHANGELOG.md first. Start with Step 01 (register the project inputs and the source-access
plan), then implement steps in dependency order using the step specifications to build and
verify the product, not just summarise the plan. Source credentials arrive incrementally:
keep every connector access_pending until a real credential is configured and demonstrated.
Do not invent project data, API access, integrations or passed checks. Persist decisions,
changed paths, validation results and the next action in PROGRESS.md so another session
can resume. Do not mark live acceptance complete from synthetic fixtures.
```

For a later session:

```text
Continue this project from PROGRESS.md. Read MASTER.md and the active step's relevant
specifications. Verify the recorded repository state, implement the next incomplete
work, run the meaningful checks, and update the handoff. Preserve the one-release scope
and all evidence, approval and publication invariants.
```

## Working with Claude Code

Use one Claude Code session per work package on its own branch; commit and update PROGRESS.md before switching sessions. `CLAUDE.md` at the repository root imports `AGENTS.md` (Claude Code memory guide: https://code.claude.com/docs/en/memory). The coding tool does not determine the runtime models the application uses; those are configuration validated in Step 03.
