# Step 02: UX, architecture and contracts

**Release:** 1.0, complete five-project POC. **Initial status:** not started.

Freeze the interfaces and state rules shared by backend, agents, console and public page. Turn the illustrative JSON bundle into explicit versioned implementation contracts.

## Prerequisites

[Step 01: Requirements, source access and acceptance definition](01-requirements-and-access.md)

Read [MASTER.md](../MASTER.md), the relevant entries in [DECISIONS.md](../DECISIONS.md), and these specifications:

- [Architecture and stack](../docs/01-architecture-and-stack.md)
- [Database and contracts](../docs/02-database-and-contracts.md)
- [API and console contracts](../docs/03-api-and-cms-contracts.md)
- [Agent contracts](../docs/04-agent-contracts.md)
- [Workflow and publication](../docs/05-workflow-and-publication.md)
- [Editorial and console UI](../docs/08-editorial-and-ui.md)

Numbered order is the default solo-coding order. Independent fixtures/contracts may be prepared earlier, but a blocked live integration cannot be marked complete. This step is an internal work package, not a separate product release.

## Original requirements covered

2.1 Map user journeys from project setup through correction/rollback.

2.2 Design dashboard, evidence explorer, media library, review and preview screens.

2.3 Document deployment boundaries and workflow state transitions.

2.4 Specify database relations, JSON schemas, agent contracts and API definitions.

2.5 Define content approval hashing and publication idempotency behavior.

2.6 Review architecture and designs with the product owner.

Deliverables: approved UX, architecture decisions, OpenAPI draft, schema definitions and page module specification.

## Detailed implementation

### 02.1 Map complete journeys

Document setup, collection, evidence inspection, video access states, finding approval/edit/rejection, formatting, final preview approval, delivery, correction and rollback. Include empty and partial-coverage paths.

### 02.2 Design the console and public page

Designs are produced in-repo: choose a visual direction (typography, palette, density) and record it in DECISIONS.md, then write route/component specifications for every console screen and the public page module. Include data needed, roles, loading/error/access-pending states and optimistic conflict handling. Use shadcn/ui primitives on Tailwind; avoid generic template defaults.

### 02.3 Define record boundaries

Resolve every baseline-schema gap in the database specification: source/project associations, immutable references, unknown dates, media records, durable jobs, policy versions and publication operations. Create new versioned schemas and fixtures.

### 02.4 Specify API and adapter contracts

Define request/response models, error codes, pagination, version preconditions and idempotency scope. Write the page-renderer adapter contract (revalidation route, revision markers) and the generated OpenAPI approach. Align FE types with these models.

### 02.5 Specify invariants and concurrency

Apply the decided atomicity strategy (D08: single-node replica set, control-document compare-and-set inside a transaction with the operation record). Document canonical payload hashing, dependency manifest, eligibility invalidation, serving gate and timeout reconciliation.

### 02.6 Specify agent contracts

Define each specialist's input/output schema, allowed references/tools, failure modes and budgets. Keep output schemas small and model-compatible; include valid abstention fixtures.

### 02.7 Record review decisions

Capture architecture choices and unresolved alternatives in DECISIONS.md. Contracts are complete when testable and agreed with relevant owners, not when a diagram alone exists.

## Required deliverables

- Versioned implementation schemas, request/response definitions and representative valid/invalid fixtures.
- Console and public-page screen specifications, state-transition table and page payload contract.
- Architecture decisions for repository boundaries, MongoDB atomicity and canonical hashing.

Use the logical code boundaries from the architecture specification and map them to actual repository paths. Update implementation schemas, API types, fixtures and documentation together when a contract changes.

## Acceptance checks

- [ ] Every mandatory journey has a state path and API/actor mapping.
- [ ] Schema fixtures cover multi-project video, unknown date, insufficient evidence and withdrawal.
- [ ] An edited payload cannot retain approval by contract; independent-source counts are not treated as truth.
- [ ] FE, backend and agent schemas use the same status vocabulary and ID/revision conventions.
- [ ] Relevant repository checks were actually run and their results recorded.
- [ ] [PROGRESS.md](../PROGRESS.md) records changed paths, decisions, evidence, unresolved dependencies and the next action.

## Missing access or information

This step has no external dependency. If the five-project input is still a template, use clearly synthetic placeholder projects in fixtures. Do not claim the original sample schema is production-complete.

## Coding prompt

```text
Implement Step 02 from steps/02-ux-architecture-and-contracts.md in the actual project repository.
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

Mark this step complete only when its deliverables and applicable acceptance checks have evidence. Use `blocked` or `in_progress` when required integration is outstanding; record fixture success separately from live acceptance. Next: [Step 03: Engineering foundation and MongoDB setup](03-foundation-and-mongodb.md)
