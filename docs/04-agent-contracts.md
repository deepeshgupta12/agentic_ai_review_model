# Master workflow and specialist agent contracts

Use LangGraph for explicit orchestration. Keep matching thresholds, permission checks, approval states, hashing, quotas and publishing in deterministic backend code. Logical agents may share a runtime model but have separate prompts, output schemas, tool permissions and evaluation cases.

## Shared execution envelope

Every task receives a server-created `task_id`, `run_id`, `project_id`, input references with exact revisions, source-policy context, locale, prompt/schema versions and remaining budget. Return a validated result with `outcome`, structured data, input/evidence references, uncertainty reasons and safe error information. Supported outcomes include completed, insufficient evidence, needs review and failed; map them explicitly into implementation schemas.

Persist requested/returned model IDs, prompt/config/schema versions, tool steps, elapsed time, provider request ID where available, retries, token/audio usage and estimated cost basis. Use null for unknown measurements. Store reference manifests instead of copying all private/source text into traces.

All model calls go through the Claude API gateway (docs/01): role-selected model IDs from config, JSON-schema structured outputs (Pydantic via `client.messages.parse()`) for extraction/synthesis, strict tool use where an agent calls tools, prompt caching for the shared evidence context, and the Message Batches API for bulk offline classification. Record `stop_reason`, returned model ID and usage on every call.

Provider refusals, incomplete responses and malformed output are explicit paths. Permit one bounded schema repair when appropriate; further failure becomes a visible task outcome. Retry transient provider transport/rate-limit failures under a shared budget and deadline. Never retry publication through an LLM.

## Specialist definitions

Output schemas for A01–A10 are in [contracts/v1/agents.schema.json](../contracts/v1/agents.schema.json), within the Claude structured-output subset. A00 is deterministic and has no model output. JSON-LD is built by the backend from the visible content, never by A08.

| ID / component | Inputs | Allowed tools | Required output and boundary |
|---|---|---|---|
| A00 Master coordinator | Config, eligible sources, job, state and budget | Dispatch registered nodes, read checkpoints, record state | Deterministic next state, run coverage and errors; cannot invent tasks/tools or approve content |
| A01 Project identity | Catalogue identity (seeded `projects` record, RERA registrations), approved aliases, candidate text/metadata, segment context | Read catalogue/aliases and matching evidence | Match/ambiguous/reject, project/phase and segment signals; alternate-name and phase-name proposals with evidence (see below); no catalogue or alias-list mutation |
| A02 Discovery planner | Identity, approved aliases, RERA IDs, languages and entitlement matrix | Approved query templates and source catalogue | Bounded queries with platform, window, locale, exclusions and priority, including identifier queries (RERA ID, developer + sector) so unknown names can surface; never uses unapproved alias proposals; collectors execute pagination |
| A03 Video understanding | Authorised aligned transcript/frames plus metadata | Read permitted segments/frames | Timestamped observations, modality, speaker and uncertainty; metadata-only is never spoken evidence |
| A04 Language/context | Original text or transcript, parent context | Approved language/translation service | Normalised text, language, translation alignment, negation/uncertainty flags; preserve names, units and original |
| A05 Claim extractor | Matched eligible evidence spans | Read supplied evidence only | Atomic aspect claims, evidence IDs, polarity, observation time and proposed type; no unsupported external facts |
| A06 Evidence verifier | Claims, supporting/contradicting retrieval and trusted records | Project-filtered evidence and allowlisted primary records | Verification status, dated authority, conflicts and reason; classify reported opinion separately from verified fact |
| A07 Findings synthesiser | Eligible verified/attributed claims and origin clusters | Read claims and source mixture | Pros/cons/neutral with exact refs, caveats and insufficiency; do not force equal counts or consensus |
| A08 SEO/AEO editor | Moderator-approved finding revisions, page context, style contract | Read approved facts and permitted page context | Structured summary/pros/cons/Q&A and metadata proposals with claim mapping; no new factual content |
| A09 Editorial QA | Final draft, approved findings and evidence manifest | Read and compare provided records | Blocking/nonblocking issues by content block and supporting refs; cannot grant final approval |
| A10 Freshness/change reviewer | New/deleted/expired evidence, old approved manifest | Read diffs and change policy | Material-change classification and review reasons; deterministic invalidation operates even if model unavailable |

## Alternate-name and phase-name discovery (A01)

While matching, A01 also proposes names that sources use for a project or one of its phases and that are not yet approved aliases: short names ("Privana"), phase names ("Privana West"), spelling variants, transliterations and Hindi-script forms, and marketing names.

- Each proposal gives the alias as written, a normalised form, its target (the project, or a specific phase identified by its RERA registration; an unknown phase stays project-level), the alias type and the evidence spans where it appears. Propose only names found in the supplied evidence; model memory is not a source.
- The backend accepts a proposal only when at least one cited eligible span shows the alias together with a strong identifier: RERA ID, developer plus locality/sector, the known project name, or an official developer/RERA page. Proposals are deduplicated per project and normalised form, and independent origins are counted.
- A deterministic collision check (backend code, not the model) compares the alias with every other catalogue project's names and aliases and with generic terms (developer name alone, locality alone, words such as "West" or "Parq"). A colliding or generic alias can be approved only as context-required, usable in a query or match only together with the developer or locality, never as a standalone term.
- Proposals have no effect until a researcher or moderator approves them in the console. Approval writes the alias, target and mode to `ai_project_configs` through the configuration API with an expected version, and the next query plan uses it. The `projects` record and the input file are never changed. Rejected proposals are kept so they are not proposed again and may become negative keywords.
- Match rationales record which alias produced a match. Revoking an approved alias sends the associations it produced back to review through the normal dependency invalidation path.
- Aliases are identity data, not facts about the project, and are never published as such.

## Initial aspect taxonomy

Connectivity, location/locality context, layout, construction quality, construction progress, possession, amenities, maintenance, density, parking, water, power, service/management and value perception. Permit `other` with a proposed label for review; version the taxonomy. Do not infer return on investment or convert sentiment into a financial recommendation.

## Prompt requirements

For each specialist include: task, input meanings, allowed references/tools, output schema, evidence standards, handling of conflicting/empty data, and examples of valid abstention. Mark source material as untrusted quoted data. Tool outputs cannot change the system task, reveal secrets or approve content. Keep instructions short enough to evaluate, and keep editorial style separate from factual extraction.

Provide adversarial fixtures for a post saying to ignore instructions, a copied marketing campaign, wrong city/same name, phase confusion, a short name shared by an unrelated project, mixed-project video, negation, sarcasm, disputed possession date, missing transcript and source withdrawal. Make tool permissions enforceable outside prompts.

## Graph design

1. Load project settings and eligibility snapshot; generate bounded query plan.
2. Collect text/video metadata and permitted content; persist cursors and coverage.
3. Match segments and record alias proposals; normalise language/media; deduplicate and create evidence.
4. Extract claims, retrieve support/conflicts, verify and synthesise findings.
5. Pause at findings review. Resume only from authenticated, version-checked review events.
6. Generate editorial draft from the selected approved finding revisions and run QA.
7. Pause at final review. Edits create a new revision; invalidated evidence returns to review.
8. A publisher action enqueues deterministic publication. After delivery, observe freshness and operational results.

Handle insufficient evidence as a valid terminal analysis outcome. Store per-connector partial status separately from overall stage. Do not hold a worker lease while waiting days for a person: checkpoint the graph, finish the current job and enqueue a unique resume job when a valid decision arrives.

## Resource controls and evaluations

Define configurable task deadline, model token limit, max tool steps, connector concurrency, media minute cap and per-run spend budget. Choose numerical production limits from entitled quotas and measurements. Model routing starts by role, then changes only on measured failures/cost and versioned evaluation. No autonomous recursive agent spawning is required.

Test each output contract independently before graph integration. Test semantic correctness with held-out evidence and human adjudication, not only schema validity or an LLM judge. Grounding, contradiction handling, project identity and editorial factual preservation have separate scores.
