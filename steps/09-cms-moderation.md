# Step 09: Moderator console

**Release:** 1.0, complete five-project POC. **Initial status:** not started.

Build the moderator console in `web/app/console/*` on top of the backend contracts: portfolio, project setup, evidence and media review, findings decisions, editorial queue, operations and administration.

## Prerequisites

[Step 02](02-ux-architecture-and-contracts.md), [Step 03](03-foundation-and-mongodb.md), [Step 04](04-project-identity.md), [Step 07](07-evidence-and-retrieval.md), [Step 08](08-agents-and-master-workflow.md)

Read [MASTER.md](../MASTER.md), the relevant entries in [DECISIONS.md](../DECISIONS.md), and these specifications:

- [API and console contracts](../docs/03-api-and-cms-contracts.md)
- [Workflow and publication](../docs/05-workflow-and-publication.md)
- [Editorial and console UI](../docs/08-editorial-and-ui.md)

## Original requirements covered

9.1 Implement portfolio and project configuration screens.

9.2 Implement evidence search, transcript viewing and source jump links.

9.3 Implement claim/finding approval, edit, reject and escalation actions.

9.4 Add source conflicts, insufficiency, origin counts and freshness indicators.

9.5 Build assignment, review queue, comments and optimistic editing locks.

9.6 Implement role enforcement and audit history.

9.7 Conduct moderator usability sessions with realistic data.

Deliverables: complete console and review operating guide.

## Detailed implementation

### 09.1 Console foundation

Use the Step 03 shell: protected route group, session handling, generated typed API client, TanStack Query for data, Zod for forms. Follow the Step 02 designs; keep components in `web/components/`. Visibly label fixture mode.

### 09.2 Portfolio and project setup

Show the five projects, generated slug, approved aliases and pending alias/phase-name proposals (with evidence, collision warnings and approve/reject/revoke), run status, coverage and access-pending sources, cost, active revision and pending work. Provide validated configuration editing (expected version) and manual refresh actions.

### 09.3 Evidence and media review

Paginated filters, original/translated text, exact excerpts/context, origin clusters, conflicts, source links and transcript jumps. Show metadata-only/access-pending media separately from analysed media.

### 09.4 Findings decisions

Display positive/negative/neutral candidates alongside evidence. Support approve, reject with reason, edit-as-new-revision, match correction and escalation. Record exact target revision; reviewer identity comes from the session.

### 09.5 Editorial workflow

Review assignment, comments, queue filters and the content-editor shell (TipTap, controlled). Optimistic versions with explicit conflict resolution; label old decisions as superseded when content changes.

### 09.6 Operations and administration

Connector access/coverage, run timelines, failed jobs, quotas, model/transcription usage, evaluation results; user/role management, thresholds, source policies, retention, prompt versions and audit search. Never expose keys or unrestricted source payloads.

### 09.7 Usability and access

Run realistic moderator sessions (the product owner can act as moderator), keyboard/accessibility checks and Playwright journeys. Clear loading, empty, stale, partial, error and forbidden states.

## Required deliverables

- Console screens for portfolio, setup, evidence, media, findings, queues, operations and administration.
- Backend review/assignment/audit endpoints and optimistic-edit handling.
- Moderator operating guide and browser/usability evidence.

## Acceptance checks

- [ ] A moderator can inspect the original evidence before approving or rejecting a finding.
- [ ] Negative findings are available under the same rules as positive ones.
- [ ] Two editors cannot silently overwrite one another; edits create new revisions.
- [ ] Analyst users cannot invoke write endpoints directly (API test, not only hidden buttons).
- [ ] Unknown video access, access-pending sources and sparse evidence are understandable in the UI.
- [ ] Relevant repository checks (web lint/type/test, Playwright journeys) were actually run and recorded.
- [ ] [PROGRESS.md](../PROGRESS.md) records changed paths, decisions, evidence, unresolved dependencies and the next action.

## Missing access or information

The console has no external dependency; it can be completed on fixtures. Screens that display live-source data show `access_pending` honestly until credentials exist.

## Coding prompt

```text
Implement Step 09 from steps/09-cms-moderation.md in this repository.
Read MASTER.md, PROGRESS.md, this step and its linked specifications. Build the moderator
console in web/app/console on the backend contracts and the Step 02 designs: portfolio,
setup, evidence/media review, findings decisions, editorial queue, operations and
administration. Enforce roles in the backend, not only in the UI. Do not invent passing
test results. Run the web checks and Playwright journeys, resolve failures, and update
PROGRESS.md with changed paths, actual results, decisions, blockers and the next action.
```

## Completion and handoff

Mark this step complete only when its deliverables and applicable acceptance checks have evidence. Next: [Step 10: SEO/AEO content and quality controls](10-seo-aeo-and-editorial-qa.md)
