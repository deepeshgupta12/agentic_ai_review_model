# Database, JSON contracts and invariants

The POC's own MongoDB holds the project catalogue (`projects`, seeded from the five-project input file by `python -m app.cli seed-projects`, run as `make seed-projects`; D30) and the separate AI records. The console operates only through authenticated backend contracts. Catalogue records are written by the import/seed service; agents read them and never mutate them.

## Baseline assets and required contract work

[Exchange schema](../contracts/client-data-contract.schema.json), [synthetic example](../contracts/client-data-example.json) and [five-project input](../contracts/five-project-input-template.json) are preserved from the original plan. They describe a per-project exchange bundle, not a database migration or complete production model. `sample_is_synthetic` labels the example. Never import it as real project evidence. In the baseline, `project.client_id`, `page_url` and `rera_references` become optional external references in the POC's own catalogue; the POC generates its own project IDs.

Step 02 must create and version the implementation schemas, API models and smaller agent outputs before dependent integration. Translate constraints to MongoDB's supported validator/BSON subset. Do not install Draft 2020-12 directly as a collection validator or send the full bundle schema to a model.

Required extensions to the baseline:

1. Separate global source revisions from project/segment associations so the same comparison video can relate to several projects without violating a source uniqueness index. Project exports can still project one association into the old `project_id` field.
2. Add explicit revisions/content hashes for claims and exact finding references in content revisions. IDs alone must not point to mutable factual meaning.
3. Add a publication operation ID, revalidation acknowledgement, delivery status, attempts and rendered-revision verification. The baseline publication object is a summary, not a complete operation record.
4. Add persisted jobs, lease/fencing fields, connector cursors, media segments, policy versions, lineage indexes, workflow state and evaluation models.
5. Allow genuinely unknown publication dates with an explicit date status. Never substitute collection time for an unknown publication date.
6. Bind final approval to project, locale, revision, payload hash, dependency manifest, policy/evidence generation and reviewer action. Keep mutable decisions outside the immutable payload.
7. Represent empty evidence without inventing a summary requiring claim IDs. Return an `insufficient_evidence` run result with `content_revision = null`; implement an informational empty-state module only if the editorial contract requests one.
8. Express cancellation, partial coverage, withdrawal and delivery failures in the record types to which they belong. The baseline has limited enums; extend schemas intentionally, not with arbitrary extra fields.
9. Define text coordinate units and original/normalised/translated anchors. A browser uses UTF-16 offsets while Python commonly indexes Unicode code points; convert explicitly and test Hindi and emoji.
10. Define nullable calibrated confidence, transcription quality and timestamp precision separately. None is a probability of factual truth by default.

Version these changes as a new contract revision, update fixtures and adapters, and record compatibility in DECISIONS.md. Keep the baseline files as historical reference. New client generation and validators must use the implementation version.

**Implementation version: [contracts/v1](../contracts/v1/README.md)** (Step 02, D22). Its README maps each of the ten gaps above to the record that resolves it. In the baseline, `micromarket` is a required string; in v1 it is optional, as D01 requires.

## Collections and ownership

| Collection | Key records / indexes | Writer |
|---|---|---|
| `projects` | Generated project ID and unique slug; name, alternate names, locality, city, optional micromarket/developer/phase/RERA/reference URL; `client_id` reserved and nullable for later integration | Import/seed service |
| `users` | Unique email/username; password hash, roles, active flag | Seed script / admin API |
| `ai_project_configs` | Unique project ID; approved search aliases (text, target project/phase, standalone or context-required, origin: input file, RERA registered name or approved proposal), construction status per project and phase with source and date (D27), languages, refresh and source settings | Configuration API |
| `ai_review_excerpts` | Unique `(project_id, id, revision)`; one source revision, its evidence spans, original words, rendering, displayed text, perspective, polarity, consistency flags and review status (D28) | Review curation service / review API |
| `ai_alias_proposals` | Unique `(project_id, normalised_alias)`; alias as written, target project/phase, alias type, evidence refs, independent-origin count, collision result, status (proposed/approved/rejected/revoked) and decision reference | Identity service (proposals) / configuration API (decisions) |
| `ai_sources` | Unique `(platform, native_id, revision)`; source identity, dates, hash, policy version and permitted payload reference | Ingestion service |
| `ai_payloads` | Erasable source text keyed by source revision (`payload_ref.key`); erasure deletes it and leaves the metadata (D38) | Ingestion service |
| `ai_project_source_links` | Unique `(project_id, source_id, source_revision, segment_key)`; match status and rationale | Identity service / moderator |
| `ai_media_segments` | Unique `(source_id, revision, segment_key)`; time range, language, modality and permitted file reference | Media worker |
| `ai_evidence` | Source revision and anchor; indexes for source/dependency invalidation | Evidence service |
| `ai_claims` | Unique `(project_id, claim_id, revision)`; aspect, type, immutable evidence refs | Analysis service |
| `ai_findings` | Unique `(project_id, finding_id, revision)`; exact claim refs and wording | Synthesis / revision service |
| `ai_content_revisions` | Unique `(project_id, locale, revision)`; immutable payload/hash/dependency manifest | Editorial service |
| `ai_review_decisions` | Target type/ID/revision/hash and server-derived actor; append-only decisions | Review API |
| `ai_publication_state` | Unique `(project_id, locale)`; approved target, active pointer, version, evidence epoch, serving gate | Publication/invalidation service |
| `ai_publication_operations` | Unique operation ID and scoped idempotency key; receipts, delivery/retry states | Publisher |
| `ai_jobs` | Unique logical job key; status/next-attempt/lease indexes | Scheduler and worker |
| `ai_agent_runs` | Run/project/task IDs, versions, usage, outcome and errors | Worker |
| `ai_connector_state` | Provider/project/query partition; cursor, watermark and last success | Connector worker |
| `ai_source_policies` | Immutable policy versions, scope and expiry; current eligibility pointer | Authorised administrator |
| `ai_origin_clusters` | Cluster membership/version and provenance | Deduplication service |
| `ai_audit_events` | Actor/action/target/time; no raw source payload | Backend services |
| `ai_idempotency_keys` | Operation, user, key hash, request digest and stored response for seven days (docs/03 Idempotency-Key, D38) | API |
| `ai_deletion_requests` | Source/policy scope, dependent IDs and erasure progress | Lifecycle service |
| `ai_evaluations` | Dataset/version/model/prompt/config and measured results | Evaluation runner |
| Checkpointer collections | Framework-specific run/thread/checkpoint keys | LangGraph persistence |

Keep arrays bounded; page sources, findings, histories and operations. Store actual BSON dates internally and ISO-8601 UTC timestamps externally. Use string ULIDs or ObjectIds consistently and expose them as opaque strings. Create compound indexes from actual query shapes and explain plans. Build indexes idempotently.

## Essential invariants

- An evidence span resolves to an eligible source revision and matching project association. `end > start`; text offsets reproduce the claimed excerpt in the identified representation.
- Claims cite existing eligible evidence; factual verification cites appropriate dated primary records. Supporting and contradicting evidence remain independently visible.
- Content resolves exact finding/claim revisions. Every substantive block is supported; a disclaimer alone cannot repair an unsupported statement.
- Model-produced IDs may reference only records included in the allowed input set. The server generates persisted IDs and verifies references.
- Stored payload bytes are canonicalised and hashed by the backend. The console never supplies the authoritative hash calculation.
- All writes requiring a current version use an expected version. Cross-project references fail validation even when a user can access both projects.
- Eligibility is checked at retrieval, approval and publication; deletion/expiry also invalidates active content according to the publication contract.

## Retention and migration

Separate erasable source payload from minimal audit metadata. Revoking evidence triggers a durable dependency invalidation job before physical erasure; deletion must not erase the references needed to identify affected content prematurely. TTL expiry alone is not sufficient because it does not implement the application's dependency workflow. Apply retention to snapshots, embeddings, media, caches, backups and redacted traces under their actual policy.

Use versioned setup/migration scripts with dry-run summaries, precondition checks and additive changes where possible. Step 03 tests the selected MongoDB topology. Step 11 tests the atomic publication strategy on that topology; a local transaction-capable test database does not prove a standalone production deployment supports transactions.
