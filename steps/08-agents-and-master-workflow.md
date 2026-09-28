# Step 08: Agent development and master workflow

**Release:** 1.0, complete five-project POC. **Initial status:** not started.

Connect the specialist components into a durable, bounded workflow that produces evidence-linked draft findings and pauses for console decisions.

## Prerequisites

[Step 02: UX, architecture and contracts](02-ux-architecture-and-contracts.md), [Step 03: Engineering foundation and MongoDB setup](03-foundation-and-mongodb.md), [Step 04: Project catalogue and identity resolution](04-project-identity.md), [Step 05: Text and social collection](05-text-and-social-connectors.md), [Step 06: Videos, shorts and multilingual processing](06-video-and-language-processing.md), [Step 07: Evidence storage, deduplication and retrieval](07-evidence-and-retrieval.md)

Read [MASTER.md](../MASTER.md), the relevant entries in [DECISIONS.md](../DECISIONS.md), and these specifications:

- [Database and contracts](../docs/02-database-and-contracts.md)
- [Agent contracts](../docs/04-agent-contracts.md)
- [Workflow and publication](../docs/05-workflow-and-publication.md)
- [Validation and release](../docs/07-validation-and-release.md)

Numbered order is the default solo-coding order. Independent fixtures/contracts may be prepared earlier, but a blocked live integration cannot be marked complete. This step is an internal work package, not a separate product release.

## Original requirements covered

8.1 Implement each agent's tools, prompts, schemas, limits and escalation behavior.

8.2 Build claim taxonomy and aspect-level extraction.

8.3 Implement fact/opinion/promotion/allegation classification and contradiction handling.

8.4 Build verified-fact retrieval and dated primary-source references.

8.5 Build pros/cons synthesis and insufficient-evidence handling.

8.6 Integrate agents into the durable workflow with bounded concurrency and budgets.

8.7 Implement output validation, resumability, cancellation and operator-visible errors.

8.8 Evaluate model routing and establish baseline prompt/model versions.

Deliverables: evaluated multi-agent pipeline producing traceable draft findings.

## Detailed implementation

### 08.1 Complete the model gateway

Extend the Step 03 Anthropic gateway: configured model roles (D10), JSON-schema structured outputs with Pydantic result types, strict tool use for tool-calling agents, prompt caching for the shared evidence context, Message Batches for bulk classification, `stop_reason`/refusal/incomplete handling, one bounded repair and measured usage/cost. Validate server-generated IDs and referenced input sets after schema validation.

### 08.2 Implement specialist wrappers

Create versioned prompts, input/output schemas and tool allowlists for A01–A11. Reuse identity/media/retrieval services already built. Keep A00 state coordination deterministic and tools restricted by role.

### 08.3 Extract and verify claims

Create atomic aspect claims, preserve fact/opinion/promotion/allegation distinctions, retrieve contradicting evidence and dated primary records, and retain uncertainty. LLM memory cannot supply a project fact.

### 08.4 Synthesise defensible findings

Create pros/cons/neutral findings with exact references, independent-origin counts and caveats. Single observations remain attributed; empty evidence returns insufficient_evidence. Apply the same standard to negative findings.

### 08.5 Build the graph

Wire collection→identity/media/context→evidence→claims→verification→findings, then human review→editorial/QA→final review. Persist checkpoints and output references. Publication runs as a deterministic service after the required action.

### 08.6 Implement pause/resume and failure paths

Release leases while awaiting review; accept only authenticated version-matched resume events. Isolate partial connector failures, enforce budgets/deadlines, support cancellation and restart without duplicate side effects.

### 08.7 Evaluate and freeze a baseline

Measure per-agent semantic failures and end-to-end grounding on held-out data. Record prompt/schema/model/config versions and cost. Escalate difficult cases based on results; no automatic retraining from moderator feedback.

## Required deliverables

- Registered specialist agents, versioned prompt/schema contracts and model gateway.
- Durable LangGraph workflow with review interrupts, resume and cancellation.
- Traceable findings, error/coverage reporting and baseline agent evaluation.

Use the logical code boundaries from the architecture specification and map them to actual repository paths. Update implementation schemas, API types, fixtures and documentation together when a contract changes.

## Acceptance checks

- [ ] Prompt injection in a source cannot gain tools, alter policy or approve/publish content.
- [ ] Invalid or invented evidence references are rejected even if JSON is valid.
- [ ] An empty corpus produces no fabricated findings; conflicting sources remain visible.
- [ ] Restart at every durable node recovers without duplicate records or lost review state.
- [ ] Budget exhaustion and unavailable models appear as explicit outcomes.
- [ ] Relevant repository checks were actually run and their results recorded.
- [ ] [PROGRESS.md](../PROGRESS.md) records changed paths, decisions, evidence, unresolved dependencies and the next action.

## Missing access or information

Provider access is required for live semantic/model evaluation. Fixture graph tests can proceed without it, but do not claim measured model quality from mock outputs. Console review gates remain enforced during all testing.

## Coding prompt

```text
Implement Step 08 from steps/08-agents-and-master-workflow.md in the actual project repository.
Read MASTER.md, PROGRESS.md, this step and its linked relevant specifications.
Inspect the current repository state and preserve its conventions. Build the work described,
not just another plan. Use the implementation schemas and enforce the backend invariants.
Keep one complete release, the standalone architecture (own MongoDB, own console and
public page, Claude API only) and no cloud provisioning. Do not invent project data, platform access or passing test results.
If a dependency is missing, complete independent work and record the precise blocked gate.
Run the meaningful checks for changed behavior, resolve failures, and update PROGRESS.md
with changed paths, actual results, decisions, blockers and the next executable action.
```

## Completion and handoff

Mark this step complete only when its deliverables and applicable acceptance checks have evidence. Use `blocked` or `in_progress` when required integration is outstanding; record fixture success separately from live acceptance. Next: [Step 09: Moderator console](09-cms-moderation.md)
