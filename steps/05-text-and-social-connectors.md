# Step 05: Text and social collection

**Release:** 1.0, complete five-project POC. **Initial status:** not started.

Collect permitted textual discussion and context from every mandatory source, with resumable pagination and honest coverage reporting.

## Prerequisites

[Step 02: UX, architecture and contracts](02-ux-architecture-and-contracts.md), [Step 03: Engineering foundation and MongoDB setup](03-foundation-and-mongodb.md), [Step 04: Project catalogue and identity resolution](04-project-identity.md)

Read [MASTER.md](../MASTER.md), the relevant entries in [DECISIONS.md](../DECISIONS.md), and these specifications:

- [Database and contracts](../docs/02-database-and-contracts.md)
- [API and console contracts](../docs/03-api-and-cms-contracts.md)
- [Source integrations](../docs/06-source-integrations.md)
- [Validation and release](../docs/07-validation-and-release.md)

Numbered order is the default solo-coding order. Independent fixtures/contracts may be prepared earlier, but a blocked live integration cannot be marked complete. This step is an internal work package, not a separate product release.

## Original requirements covered

5.1 Implement a common connector interface for discovery, fetch, incremental updates and deletion checks.

5.2 Integrate the contracted social provider and approved direct APIs.

5.3 Integrate web search and permitted forum/page adapters.

5.4 Preserve comment/thread context, pagination, publication dates and source roles.

5.5 Add quota handling, cursor checkpoints, retries, token refresh and outage isolation.

5.6 Record actual coverage and reconcile duplicate records from multiple providers.

5.7 Test retention/deletion behavior and missing-field responses.

Deliverables: working collectors for every source with a configured credential, `access_pending` registration for the rest, and documented coverage.

## Detailed implementation

### 05.1 Implement the connector base

Define typed capabilities, discover/fetch/thread/update/deletion/health methods. Unsupported capabilities return explicit status. Reuse the job, quota and error infrastructure.

### 05.2 Add entitled providers

Implement the selected listening provider/direct APIs and approved web search/extraction route. Keep provider-specific parsing behind adapters. Enable a platform only after validating its credential/entitlement and fields.

### 05.3 Preserve source provenance

Store native IDs, canonical URL, source revision/hash, original dates or unknown status, parent thread/comment IDs, collected time and policy version. Preserve necessary context and source-role uncertainty.

### 05.4 Make ingestion resumable

Persist a page's source records before committing its cursor. Replay safely with unique keys. Handle partial pages, token refresh, Retry-After, exponential backoff and a run deadline.

### 05.5 Enforce boundaries

Check policy before fetch/storage/AI use, enforce host/redirect/size limits and minimise author metadata. Exact provider/platform overlap is reconciled before model work.

### 05.6 Implement availability updates

Handle edited/deleted sources, revoked access and policy expiry. Distinguish temporary inability to fetch from confirmed deletion. Enqueue dependency invalidation where appropriate.

### 05.7 Expose coverage

Persist attempted queries, fetched/matched/full-content counts, cursors, source health and last success. Complete-for-query never means complete social-platform coverage.

## Required deliverables

- Connector registry and live adapters for mandatory text sources.
- Durable ingestion, provider quotas, incremental cursors and source lifecycle hooks.
- Contract fixtures, live entitlement verification records and coverage endpoints.

Use the logical code boundaries from the architecture specification and map them to actual repository paths. Update implementation schemas, API types, fixtures and documentation together when a contract changes.

## Acceptance checks

- [ ] Crash/retry of the same page creates no duplicate source revision.
- [ ] One provider outage permits other sources to finish and visibly marks partial coverage.
- [ ] Thread context, missing publication date and deleted/edited items behave as specified.
- [ ] A metadata-only search hit cannot become an eligible content claim.
- [ ] Each mandatory live connector has an actual authorised query result, separate from mocks.
- [ ] Relevant repository checks were actually run and their results recorded.
- [ ] [PROGRESS.md](../PROGRESS.md) records changed paths, decisions, evidence, unresolved dependencies and the next action.

## Missing access or information

Blocked source credentials do not prevent building the common interface and deterministic fixtures. Keep that provider access_pending and the mandatory live-source release gate open. Do not scrape around access restrictions.

## Coding prompt

```text
Implement Step 05 from steps/05-text-and-social-connectors.md in the actual project repository.
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

Mark this step complete only when its deliverables and applicable acceptance checks have evidence. Use `blocked` or `in_progress` when required integration is outstanding; record fixture success separately from live acceptance. Next: [Step 06: Videos, shorts and multilingual processing](06-video-and-language-processing.md)
