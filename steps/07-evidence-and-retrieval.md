# Step 07: Evidence storage, deduplication and retrieval

**Release:** 1.0, complete five-project POC. **Initial status:** not started.

Create the evidence layer that lets every finding be traced, independently counted, retrieved and invalidated correctly.

## Prerequisites

[Step 02: UX, architecture and contracts](02-ux-architecture-and-contracts.md), [Step 03: Engineering foundation and MongoDB setup](03-foundation-and-mongodb.md), [Step 04: Project catalogue and identity resolution](04-project-identity.md), [Step 05: Text and social collection](05-text-and-social-connectors.md), [Step 06: Videos, shorts and multilingual processing](06-video-and-language-processing.md)

Read [MASTER.md](../MASTER.md), the relevant entries in [DECISIONS.md](../DECISIONS.md), and these specifications:

- [Database and contracts](../docs/02-database-and-contracts.md)
- [Agent contracts](../docs/04-agent-contracts.md)
- [Workflow and publication](../docs/05-workflow-and-publication.md)
- [Validation and release](../docs/07-validation-and-release.md)

Numbered order is the default solo-coding order. Independent fixtures/contracts may be prepared earlier, but a blocked live integration cannot be marked complete. This step is an internal work package, not a separate product release.

## Original requirements covered

7.1 Implement revisioned source records and policy-controlled snapshot storage.

7.2 Create evidence spans with stable text/time anchors.

7.3 Implement exact hashing, near-duplicate detection and origin clustering.

7.4 Build project/aspect/date retrieval filters and bounded embedding similarity ranking; use native MongoDB Search/Vector Search only if already supported by the deployment.

7.5 Create lineage between sources, claims, findings and content revisions.

7.6 Implement stale, deleted, inaccessible and superseded evidence states.

7.7 Test that withdrawn evidence disappears from retrieval and dependent approval eligibility.

Deliverables: searchable evidence repository with provenance and lifecycle controls.

## Detailed implementation

### 07.1 Implement revisioned records

Persist source revisions, project associations and permitted payload/file references. Make evidence anchors identify an exact source/representation/revision; validate bounds and excerpt reproduction.

### 07.2 Create canonical evidence spans

Store original excerpt, contextual window, text/time anchor, language, modality, project association and eligibility. Translation spans link back to original evidence; avoid indexing arbitrary text as verified truth.

### 07.3 Deduplicate and cluster origins

Use exact normalised hashes, then conservative near-duplicate checks for copied/syndicated material. Preserve source records and cluster membership so repeated copies count as one origin. Do not infer personal identities across platforms.

### 07.4 Implement filtered retrieval

Filter by project/phase, eligibility, time and aspect before embedding ranking. Freeze embedding model/dimension and cap candidate counts. Build the keyword/filter baseline first (MongoDB text index + project/time/eligibility filters); add local `bge-m3` embedding ranking as a measured addition. Native MongoDB vector search only if the pinned server build supports it.

### 07.5 Build dependency lineage

Index source→evidence→claim→finding→content references. Support affected-content lookups and exact immutable revisions. Reuse this graph for reviewer citations and publication checks.

### 07.6 Implement lifecycle controls

Mark stale, corrected, unavailable, deleted and withdrawn states distinctly. Invalidate approval/serving through the shared control service before erasing required payloads. Exclude ineligible records from retrieval immediately under that contract.

### 07.7 Measure search correctness

Build labelled evidence-query cases across projects/languages; calculate recall@10, wrong-project contamination and latency. Validate both source selection and exact anchor display.

## Required deliverables

- Evidence repository, origin clustering and filtered retrieval API/service.
- Dependency lookup and retention/withdrawal processing.
- Retrieval benchmark and anchor/lineage integration checks.

Use the logical code boundaries from the architecture specification and map them to actual repository paths. Update implementation schemas, API types, fixtures and documentation together when a contract changes.

## Acceptance checks

- [ ] Three copies of one post do not count as three independent opinions.
- [ ] Retrieval never returns another project's or withdrawn evidence as eligible support.
- [ ] Hindi/emoji offsets and approximate media timestamps display correctly.
- [ ] A source correction identifies every affected draft and active revision.
- [ ] Recall@10 and latency are measured on versioned labelled cases.
- [ ] Relevant repository checks were actually run and their results recorded.
- [ ] [PROGRESS.md](../PROGRESS.md) records changed paths, decisions, evidence, unresolved dependencies and the next action.

## Missing access or information

Use bounded application-side similarity; do not make a database or cloud migration a hidden prerequisite. Label sparse retrieval evaluation honestly.

## Coding prompt

```text
Implement Step 07 from steps/07-evidence-and-retrieval.md in the actual project repository.
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

Mark this step complete only when its deliverables and applicable acceptance checks have evidence. Use `blocked` or `in_progress` when required integration is outstanding; record fixture success separately from live acceptance. Next: [Step 08: Agent development and master workflow](08-agents-and-master-workflow.md)
