# Step 13: Operations, freshness and analytics

**Release:** 1.0, complete five-project POC. **Initial status:** not started.

Make the complete product operable: incremental refresh, evidence expiry, correction routing, budget visibility and practical owner runbooks.

## Prerequisites

[Step 03: Engineering foundation and MongoDB setup](03-foundation-and-mongodb.md), [Step 05: Text and social collection](05-text-and-social-connectors.md), [Step 07: Evidence storage, deduplication and retrieval](07-evidence-and-retrieval.md), [Step 08: Agent development and master workflow](08-agents-and-master-workflow.md), [Step 09: Moderator console](09-cms-moderation.md), [Step 11: Publication and public page](11-publishing-and-recovery.md), [Step 12: Evaluation, security and capacity qualification](12-evaluation-security-and-capacity.md)

Read [MASTER.md](../MASTER.md), the relevant entries in [DECISIONS.md](../DECISIONS.md), and these specifications:

- [Workflow and publication](../docs/05-workflow-and-publication.md)
- [Source integrations](../docs/06-source-integrations.md)
- [Validation and release](../docs/07-validation-and-release.md)
- [Editorial and console UI](../docs/08-editorial-and-ui.md)

Numbered order is the default solo-coding order. Independent fixtures/contracts may be prepared earlier, but a blocked live integration cannot be marked complete. This step is an internal work package, not a separate product release.

## Original requirements covered

13.1 Configure incremental schedules and any required high-priority refresh rules.

13.2 Implement material-change detection and source-expiry/deletion follow-up.

13.3 Add connector, quality, cost, freshness, publication and review-backlog alerts.

13.4 Capture a before/after POC quality and cost report; record page and publication dates for optional later comparison.

13.5 Define error ownership, escalation, source replacement and manual fallback procedures.

13.6 Train moderators, publishers and on-call operators.

Deliverables: dashboards, alerts, runbooks, operating owners and editorial training.

## Detailed implementation

### 13.1 Configure scheduling

Use persisted project/window keys and the dedicated scheduler process. Configure manual/daily refresh and approved priority rules. Store UTC and document editor timezone presentation.

### 13.2 Implement material-change handling

Compare new eligible evidence and current approved manifests. Distinguish routine new chatter, contradictory facts, expired policy and withdrawn sources. Deterministic invalidation does not depend on a model being available.

### 13.3 Implement operational views

Show connector health, source freshness, run status, quota, model/transcription usage, delivery pending/failure, deletion backlog and moderator queue. Use per-project/source breakdowns.

### 13.4 Configure actionable alerts

Set thresholds with owners for stale pipelines, failed publications, exhausted quotas, eligibility invalidation failures and excessive spend/backlog. Persist alert events and show them in the console; optionally post to a configured webhook (for example Slack). Avoid alerting on every unchanged poll.

### 13.5 Write recovery procedures

Document pause connector/project, retry failed tasks, rotate credentials, replay cursor safely, reconcile publication, withdraw evidence, unpublish, rollback and restore checkpoints using `mongodump`/`mongorestore` of the Compose volume.

### 13.6 Measure POC outcomes

Report evidence coverage, grounding, approved/rejected findings, review minutes and measured cost. Record publication dates for later comparison; do not claim causal ranking uplift from a short POC.

### 13.7 Train and revalidate

Run moderator/publisher/operator exercises with named owners. Test refresh and deletion across an active page, then rerun affected qualification checks and update the candidate evidence.

## Required deliverables

- Persisted schedules, freshness/change routing and operational dashboards.
- Owned alert definitions, moderation/operations runbooks and training record.
- Measured POC operating model and targeted revalidation results.

Use the logical code boundaries from the architecture specification and map them to actual repository paths. Update implementation schemas, API types, fixtures and documentation together when a contract changes.

## Acceptance checks

- [ ] Duplicate scheduler ticks do not duplicate project runs.
- [ ] Expiry/deletion reaches affected review and serving states with monitored delivery.
- [ ] An operator can recover a failed connector/job without re-publishing unchanged content.
- [ ] Review queue and per-project cost/coverage are visible.
- [ ] Runbooks are exercised by someone following the documented actions.
- [ ] Relevant repository checks were actually run and their results recorded.
- [ ] [PROGRESS.md](../PROGRESS.md) records changed paths, decisions, evidence, unresolved dependencies and the next action.

## Missing access or information

Alerts and dashboards live in the console and structured logs; an optional outbound webhook is configuration. Do not provision a cloud monitoring stack or claim alerts were delivered without a recorded test.

## Coding prompt

```text
Implement Step 13 from steps/13-operations-and-freshness.md in the actual project repository.
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

Mark this step complete only when its deliverables and applicable acceptance checks have evidence. Use `blocked` or `in_progress` when required integration is outstanding; record fixture success separately from live acceptance. Next: [Step 14: One complete five-project POC release](14-single-release-and-handover.md)
