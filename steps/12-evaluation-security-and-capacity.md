# Step 12: Evaluation, security and capacity qualification

**Release:** 1.0, complete five-project POC. **Initial status:** not started.

Measure end-to-end correctness, security, capacity and recoverability against versioned data before release. Fix blocking issues and preserve evidence for review.

## Prerequisites

[Step 01: Requirements, source access and acceptance definition](01-requirements-and-access.md), [Step 02: UX, architecture and contracts](02-ux-architecture-and-contracts.md), [Step 03: Engineering foundation and MongoDB setup](03-foundation-and-mongodb.md), [Step 04: Project catalogue and identity resolution](04-project-identity.md), [Step 05: Text and social collection](05-text-and-social-connectors.md), [Step 06: Videos, shorts and multilingual processing](06-video-and-language-processing.md), [Step 07: Evidence storage, deduplication and retrieval](07-evidence-and-retrieval.md), [Step 08: Agent development and master workflow](08-agents-and-master-workflow.md), [Step 09: Moderator console](09-cms-moderation.md), [Step 10: SEO/AEO content and quality controls](10-seo-aeo-and-editorial-qa.md), [Step 11: Publication and public page](11-publishing-and-recovery.md)

Read [MASTER.md](../MASTER.md), the relevant entries in [DECISIONS.md](../DECISIONS.md), and these specifications:

- [Source integrations](../docs/06-source-integrations.md)
- [Validation and release](../docs/07-validation-and-release.md)
- [Editorial and console UI](../docs/08-editorial-and-ui.md)

Numbered order is the default solo-coding order. Independent fixtures/contracts may be prepared earlier, but a blocked live integration cannot be marked complete. This step is an internal work package, not a separate product release.

## Original requirements covered

12.1 Build a labelled dataset across all five projects, available source families, launch languages, opinions, facts and adversarial examples; target at least 150–300 source items when enough chatter exists.

12.2 Split by source origin and time, and hold out projects for tuning checks where feasible; adjudicate uncertain labels. Sparse coverage is a POC finding, not a reason to invent examples of real chatter.

12.3 Measure matching, extraction, citation support, contradiction recall, translation errors and moderator acceptance.

12.4 Test prompt injection, unsafe HTML, private URL fetching, permission escalation and secret exposure.

12.5 Test provider rate limits, revoked access, deleted sources and schema drift.

12.6 Test all five projects together, including a controlled burst above observed volume, and measure database/retrieval latency and review throughput.

12.7 Run checkpoint recovery, partial-run restart, publish rollback and duplicate-event drills; use `mongodump`/`mongorestore` against the Compose volume.

12.8 Resolve release-blocking defects and freeze evaluated versions.

Deliverables: evaluation report, security findings closure, load report and recovery evidence.

## Detailed implementation

### 12.1 Assemble and label the dataset

Use the five projects and authorised source items, targeting 150–300 where available. Include adversarial/sparse/conflicting cases, source-origin separation and confirmed languages. Record provenance and uncertain-label adjudication.

### 12.2 Prevent evaluation leakage

Split by origin cluster and time before tuning; hold out project examples where feasible. Freeze dataset/config/prompt/model versions and report small-sample limits.

### 12.3 Measure product quality

Compute project-match precision/recall/ambiguity, retrieval recall@10, claim support, contradiction recall, transcription/translation errors, editor acceptance and review time. Audit critical facts manually.

### 12.4 Test security boundaries

Exercise source prompt injection, HTML/script content, private-network URL redirects, oversized media, CSRF as applicable, permission escalation, cross-project reads, webhook replay and secret leakage.

### 12.5 Test realistic failures

Exercise quota exhaustion, revoked credentials, deleted sources, provider schema drift, partial pages, web-app outage during revalidation and incomplete model output. Check coverage/status and restart behavior.

### 12.6 Test capacity and recovery

Run five projects concurrently at agreed volume and a bounded burst; measure queue delay, API/database/retrieval latency, media cost and moderator load. Kill/restart workers and simulate uncertain publish success.

### 12.7 Close defects and record gates

Fix release blockers, rerun affected checks and freeze a candidate. Keep numerical targets tied to measurements; list remaining nonblocking issues and risks with owners.

## Required deliverables

- Versioned evaluation manifest, labels, runnable evaluation suite and quality report.
- Security findings and resolution evidence; load and recovery report.
- Candidate version matrix and acceptance-gate ledger.

Use the logical code boundaries from the architecture specification and map them to actual repository paths. Update implementation schemas, API types, fixtures and documentation together when a contract changes.

## Acceptance checks

- [ ] Each release threshold has a measured result or is explicitly blocked, never merely ticked.
- [ ] No known critical unsupported claim remains in the acceptance sample.
- [ ] All approval bypass and deterministic integrity checks pass.
- [ ] Reported live-source/model results are clearly separated from fixture results.
- [ ] Actual editorial throughput and operational cost are recorded.
- [ ] Relevant repository checks were actually run and their results recorded.
- [ ] [PROGRESS.md](../PROGRESS.md) records changed paths, decisions, evidence, unresolved dependencies and the next action.

## Missing access or information

If live data is sparse, disclose sample limits and add synthetic edge cases without presenting them as real chatter. Missing mandatory access remains a release blocker. Later Step 13 changes require targeted revalidation before Step 14.

## Coding prompt

```text
Implement Step 12 from steps/12-evaluation-security-and-capacity.md in the actual project repository.
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

Mark this step complete only when its deliverables and applicable acceptance checks have evidence. Use `blocked` or `in_progress` when required integration is outstanding; record fixture success separately from live acceptance. Next: [Step 13: Operations, freshness and analytics](13-operations-and-freshness.md)
