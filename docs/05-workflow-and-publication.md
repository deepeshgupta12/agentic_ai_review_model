# Durable jobs, approvals and publication

This is the critical integrity contract. Implement it before any live publication is enabled. Human approval is a product requirement, not a prompt suggestion. The console's final-review action may be configured to approve-and-publish in one click for a user holding both moderator and publisher roles; the backend still records approval and publication as separate audited operations.

## Separate state machines

| Record | States / meaning |
|---|---|
| Execution job | queued, running, retry_wait, waiting_review, completed, failed, cancelled |
| Workflow stage | collecting, analysing, findings_review, formatting, final_review, approved, publishing, published, insufficient_evidence |
| Coverage | complete_for_query, partial, unavailable, access_pending per source/capability |
| Finding review | pending, approved, rejected, changes_requested per immutable revision |
| Content lifecycle | draft, final_review, approved, superseded, withdrawn; activation recorded separately |
| Publication operation | queued, activating, delivery_pending, verified, retry_wait, failed, rolled_back |
| Serving state | active, temporarily_disabled, unpublished |

Step 02 froze these in [contracts/v1/state_machines.json](../contracts/v1/state_machines.json), with every allowed transition and actor ([readable view](10-journeys-and-states.md)). It extends the lists above on purpose: workflow stage `cancelled`; content `changes_requested` and `rejected`; finding review `superseded`. Do not place every enum into one overloaded `status`. A workflow may have completed analysis with partial coverage; a page may still serve an older approved revision while a newer draft awaits review.

## Jobs and checkpoints

Persist logical job key, run ID, project ID, input/config revisions, status, next attempt time, lease owner, expiry, monotonic lease/fencing token, attempts, deadline and checkpoint ID. Claim work with one atomic conditional operation. Heartbeat within the lease interval. Recovery increments fencing; every state-changing write from a worker must verify its current ownership/token. An expired worker must not overwrite a successor.

Use unique keys for scheduled project/window jobs and explicit request idempotency for manual refresh. Checkpoint after durable node outputs. External calls can repeat after crashes; ingestion IDs, graph resume events, reviews and publication actions therefore require idempotency. Test crashes before and after each durable side effect.

An exhausted budget or a cancelled job stops new work; preserve valid results and report the remaining coverage. Retry only failed eligible tasks, without replaying successful publication. A suspended human-review graph releases its lease and waits for a separate persisted resume event.

## Immutable content and hashing

1. Construct the full publish payload: visible prose, caveats, source links, evidence-window labels, permitted metadata/JSON-LD and any displayed editorial attribution/date.
2. Canonicalise JSON with one documented cross-language method, such as RFC 8785 through a vetted implementation. Validate string/date/number rules and compare fixtures across Python and TypeScript. Hash canonical UTF-8 bytes using SHA-256; do not hash repr(), pretty-printing or an arbitrary map order.
3. Freeze the exact payload and its dependency manifest. Keep operational approval timestamps, receipts and delivery status outside it. If a visible reviewed date is included, set it in the preview before approval; changing it later changes the payload and requires another approval.
4. Bind the approval to project, locale, revision ID, payload hash, dependency-manifest hash, evidence epoch, expected state version and authenticated moderator.
5. Any factual/wording/metadata change creates a new immutable content revision. Approval for an old hash cannot authorise the new revision. Unselected rejected findings never enter generation.

## Activation algorithm

1. Authenticate publisher and validate target project/locale, expected state version and scoped idempotency key. Record or reconcile the publication operation.
2. Load the immutable revision and recompute its hash. Resolve its exact approved finding/claim/evidence/policy versions; reject missing, ineligible, superseded-by-correction or revoked dependencies.
3. Check current approval and the dependency generation against the authoritative project/locale publication state. No model judgement can override this check.
4. Atomically activate the pointer and persist the pending delivery intent using the selected topology strategy below. A failed precondition returns a conflict or approval-required error.
5. A durable delivery worker requests page refresh through the page-renderer adapter (signed revalidation route on the web app) using a revision-specific key. Handle acknowledgement, failure and timeout separately.
6. Verify the revision marker/hash by reading the actual rendered public page. Only then mark delivery verified and show publication success in the console. Store verified time separately from activation time.
7. Reconcile timeouts by querying existing operation/revision state before retrying. Show delivery_pending when activation succeeded but refresh/verification has not.

## Atomicity strategy (decided: single-node replica set, D08)

MongoDB runs as a single-node replica set, so multi-document transactions are available. Use them as follows:

- **Control document first.** Keep the authoritative approval summary, active pointer, eligibility epoch, serving gate, monotonically increasing version and one bounded pending publication intent in a single `ai_publication_state` document per project/locale. Activation is one compare-and-set on that document including all expected values (approval hash, expected version, eligibility epoch). This alone guarantees the core invariant.
- **Transaction for coupled records.** Wrap the control-document CAS together with the insert/update of the `ai_publication_operations` record (and the delivery-intent outbox entry) in one transaction so an operation record can never exist without its pointer change or vice versa. Re-read eligibility and retry on transient write conflicts.
- **Invalidation path.** Project-scoped evidence invalidation first bumps the same control document's eligibility epoch (disabling serving if active content depends on the invalid evidence) and records pending invalidation, then edits source payloads. A source shared across projects invalidates each affected control document before physical erasure. Do not claim global cross-project atomicity.

Approval audit/history and operation history are separate paginated records; the control document is not an unbounded event log. Source-policy/eligibility changes flow through these services, not ad hoc writes. Fail closed for a project with pending eligibility invalidation. Test the transaction and the CAS paths against the Compose replica set, including commit/abort and concurrent-writer cases.

## Withdrawal, stale content and rollback

Source deletion, policy expiry or corrected project identity triggers dependency invalidation, revokes affected approval eligibility and enqueues correction review. If active content depends on the invalid evidence, disable its serving gate and persist urgent cache invalidation. The public content service consults serving eligibility as well as the active pointer. Monitor actual cache refresh latency; do not promise instantaneous removal from external search caches.

A routine freshness threshold may produce a warning/review draft while older evidence remains eligible; distinguish it from evidence withdrawal that blocks serving. Expired policy dates are checked at read/approval/publish time as well as by scheduled jobs.

Rollback is a new audited operation. Revalidate the previous revision against current rights/evidence and applicable approval; then activate it atomically and verify delivery. Refuse rollback to withdrawn content. If no prior revision remains eligible, unpublish the module and keep the project page usable.

## Required race and recovery checks

Approve revision A, edit to B and try to publish B with A's approval; concurrently revoke evidence during activation; submit two editors' changes; reuse an idempotency key with a different payload; crash after pointer update; time out after refresh succeeds; expire a worker lease mid-task; roll back to withdrawn evidence; reject a forged reviewer ID; and verify the page never queries the newest draft by date.

## As built in Step 08

- **Analysis graph** (`backend/app/workflows/analysis.py`, D55). One LangGraph thread per run (`analysis:<run ID>`), checkpointed in `lg_checkpoints` and `lg_writes` after every node; the state holds references and counts, never source words. Nodes: claims (A05, A06, claims stored) → findings (A07) → reviews (A11) → conclude → review (interrupt) → selected.
- **Start.** When collection finishes, the run moves to `analysing` and its `analyse` job is queued (unique key). The job waits, deferring without using an attempt, while the project's videos are still being transcribed or its evidence is not yet grouped by origin, for at most `ANALYSIS_INPUT_WAIT_MINUTES` (240); then it goes ahead and the report says what was missing.
- **Pause.** `conclude` moves the run to `findings_review` when there is a finding or review to decide, or to `insufficient_evidence` (no content revision). At the review interrupt the job ends `waiting_review` and releases its lease.
- **Resume.** A moderator's generate request (ContentRevisionRequest, mode `generate`: exact finding and review revisions) is checked (each the latest revision, approved and still approvable), then stored with a unique `resume_after_review` job in one transaction, so no worker sees the job without its event. The job checks the selection again before continuing the thread; a selection that changed meanwhile fails the job (`ineligible_dependency`) and the thread stays paused. `selected` moves the run to `formatting`; content generation is Step 10, whose route will call `request_resume`.
- **Stops.** Model budget or run budget reached, or no usable model: the job fails without retry, the run's note says why and `budget.exhausted` is set; outputs so far stay cached and `python -m app.cli analyse --run <id>` continues the thread. A provider outage retries with backoff. Other task failures (refusal, malformed output) are counted in the report and the analysis goes on.
- **Restart.** Tested at eight points (before the first node, during a model call, before and after each node that writes, after the stage change, after the pause before the job recorded it) and on resume: the same records, the same stage events and every answered model call paid once.
- **Cancellation.** Cancelling the run cancels its jobs: a running node stops at the next task boundary, a paused job is cancelled at once, and a cancelled run cannot be resumed.
