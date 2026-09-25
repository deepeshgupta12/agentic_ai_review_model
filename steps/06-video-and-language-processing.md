# Step 06: Videos, shorts and multilingual processing

**Release:** 1.0, complete five-project POC. **Initial status:** not started.

Discover project videos/shorts and create timestamped evidence only from authorised media. Preserve original language, speaker and modality through analysis.

## Prerequisites

[Step 02: UX, architecture and contracts](02-ux-architecture-and-contracts.md), [Step 03: Engineering foundation and MongoDB setup](03-foundation-and-mongodb.md), [Step 04: Project catalogue and identity resolution](04-project-identity.md), [Step 05: Text and social collection](05-text-and-social-connectors.md)

Read [MASTER.md](../MASTER.md), the relevant entries in [DECISIONS.md](../DECISIONS.md), and these specifications:

- [Database and contracts](../docs/02-database-and-contracts.md)
- [Agent contracts](../docs/04-agent-contracts.md)
- [Source integrations](../docs/06-source-integrations.md)
- [Validation and release](../docs/07-validation-and-release.md)

Numbered order is the default solo-coding order. Independent fixtures/contracts may be prepared earlier, but a blocked live integration cannot be marked complete. This step is an internal work package, not a separate product release.

## Original requirements covered

6.1 Discover videos using project names, aliases, creators, hashtags and known channels.

6.2 Match project references and preserve format certainty; accept unknown format.

6.3 Resolve which captions, transcripts or media files are authorised for analysis.

6.4 Implement audio preparation, transcription, segment timing and quality checks.

6.5 Extract sampled frames/on-screen text only where necessary and permitted.

6.6 Preserve original language, translations, speaker context and separate comments.

6.7 Evaluate numbers, possession dates, unit sizes and Hindi/English code-switching.

6.8 Display unavailable transcripts distinctly and route necessary cases to manual review.

Deliverables: video library, authorised media analysis pipeline and timestamped evidence.

## Detailed implementation

### 06.1 Build video discovery

Use name/alias/location queries plus known permitted channels and creators. Save metadata and project-match signals. Preserve known video/short format evidence or mark it unknown.

### 06.2 Resolve analysis access

Select permitted captions, creator files or licensed media. Store entitlement and transcript status separately from discovery. Do not assume public viewing grants transcript API/download access.

### 06.3 Implement safe media processing

Validate file type, byte/duration limits and allowed origin; process in an isolated worker. Use FFmpeg preparation and configured transcription; store method, original timeline, segments and uncertainty.

### 06.4 Align and translate

Keep original speech, language tags, translated/normalised text and segment mapping. Define code-point/time anchors. Evaluate code-switching, negation, names, possession dates, currency, areas and unit sizes.

### 06.5 Add selective visual observations

Extract bounded frames/OCR only when useful and permitted. Mark observation modality and video date certainty. Renders or undated imagery cannot prove present construction status.

### 06.6 Separate comments and speakers

Keep audience comments as textual sources linked to the video. Never transfer their claims to the creator. Track speaker/context uncertainty instead of inferring identity.

### 06.7 Expose media states

Serve video library and segment APIs with discovered/access_pending/metadata_only/transcribed/analysed/error distinctions. Link to source timestamps where supported; expose approximate timing explicitly.

## Required deliverables

- Video/short discovery integration and media library records/API.
- Authorised transcription, alignment, language processing and bounded visual extraction.
- Media/language fixtures and measured quality findings.

Use the logical code boundaries from the architecture specification and map them to actual repository paths. Update implementation schemas, API types, fixtures and documentation together when a contract changes.

## Acceptance checks

- [ ] A video without an authorised transcript remains visible but yields no spoken-content finding.
- [ ] Duration alone does not determine Shorts format.
- [ ] Timestamp jumps resolve the correct original segment within documented precision.
- [ ] Hindi/English/Hinglish numerical and negation errors are measured and flagged.
- [ ] Comments, descriptions, spoken content and frame observations remain distinguishable.
- [ ] Relevant repository checks were actually run and their results recorded.
- [ ] [PROGRESS.md](../PROGRESS.md) records changed paths, decisions, evidence, unresolved dependencies and the next action.

## Missing access or information

If no transcript/media entitlement exists yet, complete discovery and access-status behavior plus authorised fixture processing. Do not label live media analysis complete until a permitted real sample has been processed.

## Coding prompt

```text
Implement Step 06 from steps/06-video-and-language-processing.md in the actual project repository.
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

Mark this step complete only when its deliverables and applicable acceptance checks have evidence. Use `blocked` or `in_progress` when required integration is outstanding; record fixture success separately from live acceptance. Next: [Step 07: Evidence storage, deduplication and retrieval](07-evidence-and-retrieval.md)
