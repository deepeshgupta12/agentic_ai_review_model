# Step 14: One complete five-project POC release

**Release:** 1.0, complete five-project POC. **Initial status:** not started.

Release the complete workflow once, across all five selected projects, with real console moderation, verified approved public-page content where evidence supports it, and an honest evaluation/operations handover.

## Prerequisites

[Step 01: Requirements, source access and acceptance definition](01-requirements-and-access.md), [Step 02: UX, architecture and contracts](02-ux-architecture-and-contracts.md), [Step 03: Engineering foundation and MongoDB setup](03-foundation-and-mongodb.md), [Step 04: Project catalogue and identity resolution](04-project-identity.md), [Step 05: Text and social collection](05-text-and-social-connectors.md), [Step 06: Videos, shorts and multilingual processing](06-video-and-language-processing.md), [Step 07: Evidence storage, deduplication and retrieval](07-evidence-and-retrieval.md), [Step 08: Agent development and master workflow](08-agents-and-master-workflow.md), [Step 09: Moderator console](09-cms-moderation.md), [Step 10: SEO/AEO content and quality controls](10-seo-aeo-and-editorial-qa.md), [Step 11: Publication and public page](11-publishing-and-recovery.md), [Step 12: Evaluation, security and capacity qualification](12-evaluation-security-and-capacity.md), [Step 13: Operations, freshness and analytics](13-operations-and-freshness.md)

Read [MASTER.md](../MASTER.md), the relevant entries in [DECISIONS.md](../DECISIONS.md), and these specifications:

- [Architecture and stack](../docs/01-architecture-and-stack.md)
- [Workflow and publication](../docs/05-workflow-and-publication.md)
- [Source integrations](../docs/06-source-integrations.md)
- [Validation and release](../docs/07-validation-and-release.md)
- [Editorial and console UI](../docs/08-editorial-and-ui.md)

Numbered order is the default solo-coding order. Independent fixtures/contracts may be prepared earlier, but a blocked live integration cannot be marked complete. This step is an internal work package, not a separate product release.

## Original requirements covered

14.1 Complete end-to-end user acceptance on representative and edge-case projects in the demo Compose environment.

14.2 Confirm each agreed POC source entitlement and quota, and show unavailable coverage explicitly.

14.3 Recheck dependency patches, credentials, model availability and provider contracts.

14.4 Approve the release candidate against every acceptance gate.

14.5 Release the tagged repository version and Compose stack together in the agreed demo environment (I12).

14.6 Execute collection for the five projects, review the findings in the console and publish only moderator-approved content to the public page.

14.7 Verify the rendered page module, rejection/edit paths, refresh and recovery controls; deliver the POC evaluation report.

Deliverables: a complete end-to-end POC for all five projects, the console approval/disapproval workflow, approved page content where evidence supports it, and the evaluation report. Collection, media analysis, moderation, SEO/AEO and approved page display all belong to this single release.

## Detailed implementation

### 14.1 Review the candidate

Verify all work packages, locked versions, migrations, source capabilities, console/page behavior, user roles, runbooks and accepted defect list. Recheck current model availability, patches and provider entitlements.

### 14.2 Run full acceptance in the demo environment

Execute the complete scenario in the validation specification on representative five-project cases, including sparse evidence, rejection, edit, final approval, publication, refresh, correction and rollback.

### 14.3 Verify release gates

Compare measured results to agreed criteria and obtain the relevant product/editorial/technical release decisions. Record unresolved mandatory dependencies; they cannot be converted into optional scope by the coding assistant.

### 14.4 Prepare the concrete release

Tag the repository, build the Compose images, and write the additive DB setup plan. Specify startup order, compatibility, rollback target (previous tag) and the handling of active jobs/checkpoints.

### 14.5 Apply the authorised release

Deliver API, workers, MongoDB setup, console and public page together as one Compose stack. This is one release with internal development checkpoints, not staged product capability launches.

### 14.6 Operate the five-project POC

Load the five project records and configured sources, run collection/analysis, review findings in the console, generate editorial previews and publish only specifically approved revisions. Insufficient evidence is a valid reported outcome.

### 14.7 Verify and hand over

Check actual rendered revisions, rejection/edit behavior, freshness, deletion, recovery, queue ownership and measured spend. Deliver the POC report, known limitations, manuals and reproducible repository instructions.

## Required deliverables

- One complete versioned release with all core capabilities and recorded owner acceptance.
- Five-project POC run/review/publication evidence and measured evaluation report.
- Operational handover, limitations, rollback/recovery instructions and completed progress ledger.

Use the logical code boundaries from the architecture specification and map them to actual repository paths. Update implementation schemas, API types, fixtures and documentation together when a contract changes.

## Acceptance checks

- [ ] Every mandatory capability is demonstrated with real entitled integrations.
- [ ] Each published page module matches the exact approved revision and eligible evidence.
- [ ] Projects with sparse data do not receive manufactured claims.
- [ ] Rollback/recovery and correction procedures are demonstrated in the actual integration environment.
- [ ] No cloud work or second product release was silently introduced.
- [ ] Relevant repository checks were actually run and their results recorded.
- [ ] [PROGRESS.md](../PROGRESS.md) records changed paths, decisions, evidence, unresolved dependencies and the next action.

## Missing access or information

If mandatory source access or a critical integrity check remains unresolved, keep the release blocked and continue independent fixes. A fixture demo is not completion. Public publication still requires the product's recorded moderator approval for each exact revision.

## Coding prompt

```text
Implement Step 14 from steps/14-single-release-and-handover.md in the actual project repository.
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

Mark this step complete only when its deliverables and applicable acceptance checks have evidence. Use `blocked` or `in_progress` when required integration is outstanding; record fixture success separately from live acceptance. Next: Complete the POC report and operating handover; retain this repository as the maintained product record.
