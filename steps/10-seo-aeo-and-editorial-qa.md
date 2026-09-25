# Step 10: SEO/AEO content and quality controls

**Release:** 1.0, complete five-project POC. **Initial status:** not started.

Generate and review publishable content from approved findings while preserving factual meaning, caveats and exact evidence lineage.

## Prerequisites

[Step 02: UX, architecture and contracts](02-ux-architecture-and-contracts.md), [Step 07: Evidence storage, deduplication and retrieval](07-evidence-and-retrieval.md), [Step 08: Agent development and master workflow](08-agents-and-master-workflow.md), [Step 09: Moderator console](09-cms-moderation.md)

Read [MASTER.md](../MASTER.md), the relevant entries in [DECISIONS.md](../DECISIONS.md), and these specifications:

- [Database and contracts](../docs/02-database-and-contracts.md)
- [Agent contracts](../docs/04-agent-contracts.md)
- [Workflow and publication](../docs/05-workflow-and-publication.md)
- [Editorial and console UI](../docs/08-editorial-and-ui.md)

Numbered order is the default solo-coding order. Independent fixtures/contracts may be prepared earlier, but a blocked live integration cannot be marked complete. This step is an internal work package, not a separate product release.

## Original requirements covered

10.1 Agree voice, content length, section structure and supported languages.

10.2 Generate summary, advantages, considerations and buyer Q&A from approved findings.

10.3 Enforce claim references on every substantive sentence/block.

10.4 Add editorial checks for unsupported numbers, new factual claims, exaggeration and source imbalance.

10.5 Generate metadata/JSON-LD proposals aligned with the visible module content.

10.6 Build final page preview, revision diff and approval of the canonical payload hash.

10.7 Evaluate factual preservation across formatting and manual edits.

Deliverables: publishable, reviewed page module and editorial validation suite.

## Detailed implementation

### 10.1 Freeze the editorial contract

Confirm voice, output locale, length, module fields, Q&A style and permitted metadata changes. Read the project record and prevent duplicate/conflicting content across sections. Do not promise SEO/AEO outcomes.

### 10.2 Implement structured generation

Pass only selected eligible moderator-approved finding revisions and necessary page context to the editor. Produce summary, pros, cons, concise questions/answers, coverage labels and source mapping.

### 10.3 Enforce factual references

Require each substantive block to resolve exact approved claims/evidence. Do not substitute source URLs alone for claim-level traceability. Keep a real insufficient-evidence outcome instead of forcing output.

### 10.4 Build QA and manual-edit validation

Check numbers, dates, units, names, attribution, negation, caveats, unsupported assertions and overgeneralisation. Run the same invariants after moderator edits. A changed factual meaning returns to finding review.

### 10.5 Integrate preview and metadata

Render through the actual page template/adapter. Include proposed metadata/JSON-LD in the approved payload and match visible content. Recheck current official search documentation before adopting structured-data types.

### 10.6 Freeze the final revision

Canonicalise/hash the complete payload and immutable dependency manifest. Keep operational approval metadata outside the hashed body. Display revision diff and exact target for final approval.

### 10.7 Evaluate preservation

Compare generated and manually edited text against approved findings using automated reference checks plus human factual audit. Record blocking issues by block and regression examples.

## Required deliverables

- SEO/AEO generation and editorial QA agents/services.
- Immutable content revisions, reference maps, diff and actual page preview.
- Final review approval action and factual-preservation regression set.

Use the logical code boundaries from the architecture specification and map them to actual repository paths. Update implementation schemas, API types, fixtures and documentation together when a contract changes.

## Acceptance checks

- [ ] Rejected/unapproved findings cannot appear in generated content.
- [ ] Rewriting an opinion into a universal fact is detected and blocks approval.
- [ ] All substantive blocks carry valid references; unsupported numbers are rejected.
- [ ] A manual edit changes the revision/hash and cannot reuse earlier final approval.
- [ ] Page copy remains usable with unequal or empty pros/cons lists.
- [ ] Relevant repository checks were actually run and their results recorded.
- [ ] [PROGRESS.md](../PROGRESS.md) records changed paths, decisions, evidence, unresolved dependencies and the next action.

## Missing access or information

This step has no external dependency beyond the Anthropic key for live generation; fixture generation validates references and hashing meanwhile.

## Coding prompt

```text
Implement Step 10 from steps/10-seo-aeo-and-editorial-qa.md in the actual project repository.
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

Mark this step complete only when its deliverables and applicable acceptance checks have evidence. Use `blocked` or `in_progress` when required integration is outstanding; record fixture success separately from live acceptance. Next: [Step 11: Publication and public page](11-publishing-and-recovery.md)
