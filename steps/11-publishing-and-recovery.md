# Step 11: Publication and public page

**Release:** 1.0, complete five-project POC. **Initial status:** not started.

Implement the guarded publication path from final approval to a verified rendered public page: atomic activation, durable delivery through ISR revalidation, rendered-revision verification, correction/withdrawal, rollback and unpublish.

## Prerequisites

[Step 02](02-ux-architecture-and-contracts.md), [Step 03](03-foundation-and-mongodb.md), [Step 07](07-evidence-and-retrieval.md), [Step 09](09-cms-moderation.md), [Step 10](10-seo-aeo-and-editorial-qa.md)

Read [MASTER.md](../MASTER.md), the relevant entries in [DECISIONS.md](../DECISIONS.md), and these specifications:

- [Database and contracts](../docs/02-database-and-contracts.md)
- [API and console contracts](../docs/03-api-and-cms-contracts.md)
- [Workflow and publication](../docs/05-workflow-and-publication.md)
- [Editorial and console UI](../docs/08-editorial-and-ui.md)

## Original requirements covered (revised)

11.1 Implement the publication state records and the public read endpoint.

11.2 Build the public project page in `web/app/projects/[slug]` on the shared page template.

11.3 Implement atomic approval/publication state changes, idempotency keys, conflict detection and persisted delivery jobs.

11.4 Add cache revalidation and rendered-content verification.

11.5 Implement unpublish/correction/rollback with role checks and audit trail.

11.6 Verify indexability settings, structured-data consistency and mobile presentation.

11.7 Test worker crash, timeout after success and simultaneous editor updates.

Deliverables: end-to-end approved-content publishing and recovery in the local/demo environment.

## Detailed implementation

### 11.1 Public read endpoint and page

`GET /v1/public/projects/{slug}/insights` returns only the active eligible revision (pointer + serving gate), with revision ID and hash. The page's server component renders the payload with the shared template and embeds `data-insights-revision`/`data-insights-hash`. No active revision ⇒ empty state. The page never queries drafts and never calls a model.

### 11.2 Activation invariants

Validate actor (publisher role), project/locale, revision/hash, exact approval, evidence/policy eligibility, expected version and idempotency. Apply the D08 strategy: control-document compare-and-set inside a transaction with the operation record and delivery intent.

### 11.3 Durable delivery

A delivery worker consumes the persisted intent, calls the web app's signed revalidation route with the revision key, stores the acknowledgement, then fetches the public page and compares the embedded marker to the activated revision/hash. Distinguish `activating`, `delivery_pending`, `verified`, `failed`.

### 11.4 Reconcile failures

Timeout-after-success is resolved by lookup, not blind retry. Retry transient failures under a deadline. Expose delivery states accurately in the console.

### 11.5 Correction and withdrawal

Public corrections endpoint (rate-limited, bot-protected) creates a moderation-queue item. Evidence invalidation bumps the control document's eligibility epoch and serving gate, revalidates the page and enqueues review. Track incomplete invalidation/erasure until reconciled.

### 11.6 Rollback and unpublish

Publisher role and reason required; revalidate the prior revision's current eligibility; activate through the same guarded path; verify rendering. If no prior revision is eligible, unpublish and render the empty state.

### 11.7 Page verification

Mobile/desktop rendering, escaping, link safety, `noindex` per I14, JSON-LD matching visible content, long names and empty optional sections. Playwright covers publish → verify → correction → rollback → unpublish.

## Required deliverables

- Publication service, control-document activation, delivery worker and verification.
- Public project page and public read/corrections endpoints.
- Correction/unpublish/rollback actions and race/recovery test evidence.

## Acceptance checks

- [ ] Publishing without current final approval is rejected through UI, API and worker paths.
- [ ] Concurrent evidence withdrawal and activation cannot leave newly ineligible content served.
- [ ] Timeout after a successful write yields one operation and the correct rendered revision.
- [ ] A crash after activation is recovered from persisted delivery intent.
- [ ] Rollback to withdrawn evidence is rejected; eligible rollback and unpublish are verified on the page.
- [ ] The public endpoint never exposes drafts, private notes or withdrawn content.
- [ ] Relevant repository checks were actually run and their results recorded.
- [ ] [PROGRESS.md](../PROGRESS.md) records changed paths, decisions, evidence, unresolved dependencies and the next action.

## Missing access or information

This step has no external dependency. It can be completed and verified entirely in the Compose environment.

## Coding prompt

```text
Implement Step 11 from steps/11-publishing-and-recovery.md in this repository.
Read MASTER.md, PROGRESS.md, this step and its linked specifications. Implement the guarded
publication path: public read endpoint, server-rendered public page with revision markers,
control-document compare-and-set inside a transaction, durable delivery via the signed
revalidation route, rendered-revision verification, corrections, rollback and unpublish.
Write the race and recovery tests listed in docs/05 and run them against the Compose
replica set. Do not invent passing test results. Update PROGRESS.md with changed paths,
actual results, decisions, blockers and the next executable action.
```

## Completion and handoff

Mark this step complete only when its deliverables and applicable acceptance checks have evidence. Next: [Step 12: Evaluation, security and capacity qualification](12-evaluation-security-and-capacity.md)
