# Journeys and state machines

Generated from [contracts/v1/journeys.json](../contracts/v1/journeys.json) and [contracts/v1/state_machines.json](../contracts/v1/state_machines.json) by `python3 scripts/check_contracts.py --render`. Do not edit by hand; `scripts/check_contracts.py` fails when this file is stale.

## Journeys

### J01: Register the five projects and configure them

Covers: setup.

| # | Actor | API call | What happens | State changes |
|---|---|---|---|---|
| 1 | researcher | `POST /v1/projects/import` (importProjects) | Imports the five-project input file; catalogue records and slugs are created (D19) | — |
| 2 | researcher | `GET /v1/projects/{project_id}` (getProject) | Checks the record and the seeded aliases (input names and RERA registered names) | — |
| 3 | researcher | `PATCH /v1/projects/{project_id}` (updateProjectConfig) | Sets languages, refresh and enabled sources at the expected version; a stale version returns 409 | — |
| 4 | researcher | `GET /v1/connectors/health` (getConnectorHealth) | Sees which connectors are still access_pending | — |

### J02: Collection run with partial coverage

Covers: collection, partial_coverage.

| # | Actor | API call | What happens | State changes |
|---|---|---|---|---|
| 1 | researcher | `POST /v1/projects/{project_id}/runs` (startRun) | Starts a run for one project within entitlements | workflow_stage[run]: new → collecting; execution_job[collect]: new → queued |
| 2 | system | — | A worker claims the collect job with a lease | execution_job[collect]: queued → running |
| 3 | system | — | Brave and YouTube collect; an access_pending connector is recorded as not run; one provider fails mid-way and is marked partial while the others finish | — |
| 4 | analyst | `GET /v1/runs/{run_id}/events` (streamRunEvents) | Watches stage and coverage events | — |
| 5 | system | — | Collection finishes and analysis starts | execution_job[collect]: running → completed; workflow_stage[run]: collecting → analysing |
| 6 | analyst | `GET /v1/runs/{run_id}` (getRun) | Sees partial and access_pending coverage labelled per connector | — |

### J03: Inspect evidence and videos

Covers: evidence_inspection, video_access.

| # | Actor | API call | What happens | State changes |
|---|---|---|---|---|
| 1 | analyst | `GET /v1/projects/{project_id}/sources` (listSources) | Filters sources by platform, aspect, date and language | — |
| 2 | moderator | `GET /v1/sources/{source_id}/revisions/{revision}` (getSourceRevision) | Reads the exact excerpt, its context, the anchor (with UTF-16 offsets for highlighting), the policy and eligibility | — |
| 3 | analyst | `GET /v1/projects/{project_id}/media` (listMedia) | Sees each video's access and analysis status | — |
| 4 | system | — | A video without an authorised route stays in the library as metadata_only and yields no spoken-content evidence | media_access[video1]: discovered → metadata_only |

### J04: Correct a wrong project match

Covers: match_correction.

| # | Actor | API call | What happens | State changes |
|---|---|---|---|---|
| 1 | system | — | Deterministic matching auto-accepts a post that names the project | source_link[lnk1]: new → auto_accepted |
| 2 | moderator | `POST /v1/project-source-links/{link_id}/decisions` (decideSourceLink) | Sees the post is about a same-name project in another city and rejects the match with a reason | source_link[lnk1]: auto_accepted → rejected |
| 3 | system | — | Evidence on the rejected link becomes ineligible; affected findings go back to analysis | workflow_stage[run]: findings_review → analysing |

### J05: Review alternate-name proposals (D17)

Covers: alias_review.

| # | Actor | API call | What happens | State changes |
|---|---|---|---|---|
| 1 | system | — | A01 proposes 'Privana West' citing a span that also shows its RERA ID; the collision check finds none | alias_proposal[als1]: new → proposed |
| 2 | system | — | A01 proposes 'Parq'; the collision check marks it generic | alias_proposal[als2]: new → proposed |
| 3 | researcher | `GET /v1/projects/{project_id}/alias-proposals` (listAliasProposals) | Reviews proposals with evidence and collision warnings | — |
| 4 | researcher | `POST /v1/alias-proposals/{proposal_id}/decisions` (decideAliasProposal) | Approves 'Privana West' as a standalone alias for that phase | alias_proposal[als1]: proposed → approved |
| 5 | moderator | `POST /v1/alias-proposals/{proposal_id}/decisions` (decideAliasProposal) | Approves 'Parq' as context-required only; standalone approval is refused by the contract | alias_proposal[als2]: proposed → approved |
| 6 | moderator | `POST /v1/alias-proposals/{proposal_id}/decisions` (decideAliasProposal) | Later revokes 'Privana West'; the matches it produced return to review | alias_proposal[als1]: approved → revoked |

### J06: Review findings: approve, edit, reject

Covers: finding_approval, finding_edit, finding_rejection.

| # | Actor | API call | What happens | State changes |
|---|---|---|---|---|
| 1 | system | — | Analysis produces three draft findings | workflow_stage[run]: analysing → findings_review; finding_review[f1r1]: new → pending; finding_review[f2r1]: new → pending; finding_review[f3r1]: new → pending |
| 2 | moderator | `GET /v1/projects/{project_id}/findings` (listFindings) | Opens findings with their claims, conflicting evidence and eligibility | — |
| 3 | moderator | `POST /v1/findings/{finding_id}/decisions` (decideFinding) | Approves finding 1 after reading its original evidence | finding_review[f1r1]: pending → approved |
| 4 | moderator | `POST /v1/findings/{finding_id}/revisions` (reviseFinding) | Tightens finding 2's wording; this creates revision 2 | finding_review[f2r1]: pending → superseded; finding_review[f2r2]: new → pending |
| 5 | moderator | `POST /v1/findings/{finding_id}/decisions` (decideFinding) | Approves finding 2 revision 2 | finding_review[f2r2]: pending → approved |
| 6 | moderator | `POST /v1/findings/{finding_id}/decisions` (decideFinding) | Rejects finding 3 with a reason (single promotional source) | finding_review[f3r1]: pending → rejected |

### J07: Generate page content and give final approval

Covers: formatting, final_approval.

| # | Actor | API call | What happens | State changes |
|---|---|---|---|---|
| 1 | moderator | `POST /v1/projects/{project_id}/content-revisions` (createContentRevision) | Generates content from the selected approved finding revisions only | workflow_stage[run]: findings_review → formatting; execution_job[generate]: new → queued |
| 2 | system | — | A08 drafts, the backend builds JSON-LD and hashes the payload | execution_job[generate]: queued → running; content_lifecycle[rev1]: new → draft |
| 3 | system | — | A09 QA and the deterministic reference checks pass | content_lifecycle[rev1]: draft → final_review; workflow_stage[run]: formatting → final_review; execution_job[generate]: running → completed |
| 4 | moderator | `GET /v1/content-revisions/{revision_id}` (getContentRevision) | Reviews the preview in the real page template, the diff and the hashes | — |
| 5 | moderator | `POST /v1/projects/{project_id}/content-revisions` (createContentRevision) | Edits one sentence; this saves revision 2 with a new hash | content_lifecycle[rev1]: final_review → superseded; content_lifecycle[rev2]: new → draft; workflow_stage[run]: final_review → formatting |
| 6 | system | — | The edit passes the same checks | content_lifecycle[rev2]: draft → final_review; workflow_stage[run]: formatting → final_review |
| 7 | moderator | `POST /v1/content-revisions/{revision_id}/approvals` (approveContentRevision) | Approves revision 2 by its exact payload hash, manifest hash, epoch and state version | content_lifecycle[rev2]: final_review → approved; workflow_stage[run]: final_review → approved |

### J08: Publish and verify delivery

Covers: delivery.

| # | Actor | API call | What happens | State changes |
|---|---|---|---|---|
| 1 | publisher | `GET /v1/projects/{project_id}/publication` (getPublicationState) | Sees the approved revision and that nothing is active yet | — |
| 2 | publisher | `POST /v1/publications` (publish) | Publishes the approved revision with its hash and the expected state version | publication_operation[op1]: new → queued; workflow_stage[run]: approved → publishing |
| 3 | system | — | One transaction: control-document compare-and-set, operation record and delivery intent | publication_operation[op1]: queued → activating; publication_operation[op1]: activating → delivery_pending; serving_state[page]: unpublished → active |
| 4 | system | — | The delivery worker calls the signed revalidation route and stores the acknowledgement | — |
| 5 | system | — | Reads the rendered page; its revision marker and hash match | publication_operation[op1]: delivery_pending → verified; workflow_stage[run]: publishing → published |
| 6 | publisher | `GET /v1/publications/{operation_id}` (getPublication) | Sees activation and verified delivery as separate times | — |

### J09: Public page reads only the active revision

Covers: public_read.

| # | Actor | API call | What happens | State changes |
|---|---|---|---|---|
| 1 | public | `GET /v1/public/projects/{slug}/insights` (getPublicInsights) | Gets the active eligible revision; a newer draft is never returned | — |
| 2 | public | `GET /v1/public/projects/{slug}/insights` (getPublicInsights) | For a project with nothing active, gets 404 and the page shows the empty state | — |

### J10: Too little evidence is reported honestly

Covers: insufficient_evidence.

| # | Actor | API call | What happens | State changes |
|---|---|---|---|---|
| 1 | researcher | `POST /v1/projects/{project_id}/runs` (startRun) | Starts a run for a new-launch project | workflow_stage[run]: new → collecting; execution_job[collect]: new → queued |
| 2 | system | — | Collection finds little permitted discussion | execution_job[collect]: queued → running; workflow_stage[run]: collecting → analysing |
| 3 | system | — | No eligible evidence supports a finding; no content revision is created and nothing is manufactured | workflow_stage[run]: analysing → insufficient_evidence; execution_job[collect]: running → completed |
| 4 | analyst | `GET /v1/runs/{run_id}` (getRun) | Sees the insufficient-evidence result with its coverage | — |

### J11: Handle a public correction

Covers: correction.

| # | Actor | API call | What happens | State changes |
|---|---|---|---|---|
| 1 | public | `POST /v1/public/projects/{slug}/corrections` (submitCorrection) | A reader reports an outdated statement from the page's correction link | correction[cor1]: new → received |
| 2 | moderator | `GET /v1/corrections` (listCorrections) | Opens the correction queue | — |
| 3 | moderator | `POST /v1/corrections/{correction_id}/decisions` (decideCorrection) | Checks the evidence, revises the finding (J06 path) and resolves the correction with a reason | correction[cor1]: received → resolved |

### J12: Withdraw a source behind published content

Covers: withdrawal.

| # | Actor | API call | What happens | State changes |
|---|---|---|---|---|
| 1 | moderator | `POST /v1/sources/{source_id}/withdrawals` (withdrawSource) | Withdraws a source revision the active page depends on | deletion_request[del1]: new → pending |
| 2 | system | — | The control document's epoch is bumped first and serving is disabled; the page is revalidated to the empty state | deletion_request[del1]: pending → invalidating; record_lifecycle[ev1]: active → withdrawn; serving_state[page]: active → temporarily_disabled; content_lifecycle[rev2]: approved → withdrawn |
| 3 | system | — | Affected findings get new revisions for re-review | finding_review[f1r1]: approved → superseded |
| 4 | system | — | Payloads are erased only after invalidation | deletion_request[del1]: invalidating → erasing; deletion_request[del1]: erasing → completed |
| 5 | publisher | `GET /v1/projects/{project_id}/publication` (getPublicationState) | Sees serving temporarily disabled and the reason | — |

### J13: Roll back to an eligible prior revision

Covers: rollback.

| # | Actor | API call | What happens | State changes |
|---|---|---|---|---|
| 1 | publisher | `POST /v1/publications/{operation_id}/rollback` (rollbackPublication) | Rolls back from the current operation to an earlier, still-eligible revision | publication_operation[op2]: new → queued |
| 2 | system | — | The prior revision is re-validated against current rights and evidence, activated and verified | publication_operation[op2]: queued → activating; publication_operation[op2]: activating → delivery_pending; publication_operation[op2]: delivery_pending → verified; publication_operation[op1]: verified → rolled_back |
| 3 | publisher | `POST /v1/publications/{operation_id}/rollback` (rollbackPublication) | Tries to roll back to a withdrawn revision | publication_operation[op3]: new → queued |
| 4 | system | — | Refused with 409 ineligible_dependency; nothing changes on the page | publication_operation[op3]: queued → failed |

### J14: Unpublish the module

Covers: unpublish.

| # | Actor | API call | What happens | State changes |
|---|---|---|---|---|
| 1 | publisher | `POST /v1/projects/{project_id}/unpublish` (unpublishProject) | Unpublishes with a reason and the expected state version | publication_operation[op4]: new → queued |
| 2 | system | — | Activated and verified: the page shows the empty state and stays usable | publication_operation[op4]: queued → activating; publication_operation[op4]: activating → delivery_pending; serving_state[page]: active → unpublished; publication_operation[op4]: delivery_pending → verified |

### J15: An approval never carries over to an edited revision

Covers: stale_approval_rejected.

| # | Actor | API call | What happens | State changes |
|---|---|---|---|---|
| 1 | moderator | `POST /v1/content-revisions/{revision_id}/approvals` (approveContentRevision) | Approves revision A | content_lifecycle[revA]: final_review → approved |
| 2 | moderator | `POST /v1/projects/{project_id}/content-revisions` (createContentRevision) | Edits the text, which saves revision B with a different payload hash | content_lifecycle[revB]: new → draft |
| 3 | system | — | Revision B passes QA and awaits its own approval | content_lifecycle[revB]: draft → final_review |
| 4 | publisher | `POST /v1/publications` (publish) | Tries to publish revision B using revision A's approval | publication_operation[op5]: new → queued |
| 5 | system | — | Refused with 409 approval_required: A's approval binds A's hash only | publication_operation[op5]: queued → failed |

### J16: Cancel a run

Covers: cancellation.

| # | Actor | API call | What happens | State changes |
|---|---|---|---|---|
| 1 | researcher | `POST /v1/projects/{project_id}/runs` (startRun) | Starts a run | workflow_stage[run]: new → collecting; execution_job[collect]: new → queued |
| 2 | system | — | A worker picks it up | execution_job[collect]: queued → running |
| 3 | researcher | `POST /v1/runs/{run_id}/cancel` (cancelRun) | Cancels with a reason; valid results so far are kept | execution_job[collect]: running → cancelled; workflow_stage[run]: collecting → cancelled |

### J17: Recover from a worker crash

Covers: recovery.

| # | Actor | API call | What happens | State changes |
|---|---|---|---|---|
| 1 | system | — | The worker dies mid-task; its lease expires and recovery increments the fencing token | execution_job[collect]: running → retry_wait |
| 2 | system | — | Another worker resumes from the last checkpoint; the old worker's late writes are rejected by the fencing token | execution_job[collect]: retry_wait → running; execution_job[collect]: running → completed |
| 3 | analyst | `GET /v1/runs/{run_id}` (getRun) | Sees one completed run with no duplicate records | — |

### J18: A 'lived here' post about a project nobody can live in yet goes to review

Covers: status_consistency.

| # | Actor | API call | What happens | State changes |
|---|---|---|---|---|
| 1 | system | — | A post says the author has lived in the project for a year, but the project is under construction; the claim is flagged occupancy_before_possession and the match goes to review instead of being accepted | source_link[lnk7]: new → needs_review |
| 2 | moderator | `GET /v1/sources/{source_id}/revisions/{revision}` (getSourceRevision) | Reads the post: it names Phase 1, which the RERA registry shows as ready to move | — |
| 3 | moderator | `POST /v1/project-source-links/{link_id}/decisions` (decideSourceLink) | Accepts the match with the phase set to Phase 1; the flag clears because that phase is ready | source_link[lnk7]: needs_review → accepted |
| 4 | system | — | Another post claims years of living in a new-launch project with no ready phase; it is flagged the same way | source_link[lnk8]: new → needs_review |
| 5 | moderator | `POST /v1/project-source-links/{link_id}/decisions` (decideSourceLink) | Rejects it as not credible for this project, with a reason; it never reaches findings, reviews or the page | source_link[lnk8]: needs_review → rejected |
| 6 | researcher | `PATCH /v1/projects/{project_id}` (updateProjectConfig) | Records Phase 1's ready-to-move status from the registry, with its date, so later posts about Phase 1 are judged correctly | — |

### J19: First-person reviews from real posts and videos, positive and negative

Covers: source_reviews.

| # | Actor | API call | What happens | State changes |
|---|---|---|---|---|
| 1 | system | — | A11 proposes a buyer's forum post (dashes turned into commas), a YouTube comment in Hinglish (translated) and a post claiming residence in the under-construction project; the last one is flagged | review_excerpt[rex1]: new → pending; review_excerpt[rex2r1]: new → pending; review_excerpt[rex3]: new → pending |
| 2 | moderator | `GET /v1/projects/{project_id}/review-excerpts` (listReviewExcerpts) | Sees each review beside the original words, the credit line, the rendering check and any flag | — |
| 3 | moderator | `POST /v1/review-excerpts/{excerpt_id}/decisions` (decideReviewExcerpt) | Approves the forum post review; the backend confirmed the words match the original | review_excerpt[rex1]: pending → approved |
| 4 | moderator | `POST /v1/review-excerpts/{excerpt_id}/revisions` (reviseReviewExcerpt) | Corrects one word in the translation of the YouTube comment; this creates revision 2 | review_excerpt[rex2r1]: pending → superseded; review_excerpt[rex2r2]: new → pending |
| 5 | moderator | `POST /v1/review-excerpts/{excerpt_id}/decisions` (decideReviewExcerpt) | Approves the corrected translation (negative review about construction speed) | review_excerpt[rex2r2]: pending → approved |
| 6 | moderator | `POST /v1/review-excerpts/{excerpt_id}/decisions` (decideReviewExcerpt) | Rejects the flagged review with a reason; approval is refused while the flag stands | review_excerpt[rex3]: pending → rejected |
| 7 | moderator | `POST /v1/projects/{project_id}/content-revisions` (createContentRevision) | Generates page content with the approved findings and the two approved reviews, one positive and one negative, each with its credit line | — |

## State machines

### execution_job

States (`JobStatus`), field `status` of `Job`. Starts in `queued`; ends in `completed`, `failed`, `cancelled`.

| From | To | Who | Trigger |
|---|---|---|---|
| `queued` | `running` | system | A worker claims the job atomically with a lease and a new fencing token |
| `retry_wait` | `running` | system | Next attempt is due and a worker claims it |
| `running` | `completed` | system | Work and its durable side effects are committed |
| `running` | `retry_wait` | system | Transient failure, or the lease expired; recovery increments the fencing token |
| `running` | `waiting_review` | system | The graph reached a human-review pause; the checkpoint is saved and the lease released |
| `running` | `failed` | system | Non-retryable error or attempts exhausted |
| `retry_wait` | `failed` | system | Deadline passed before a successful attempt |
| `queued` | `cancelled` | researcher, system | Run cancelled before work started |
| `running` | `cancelled` | researcher, system | Cooperative cancellation; valid results are kept |
| `retry_wait` | `cancelled` | researcher, system | Run cancelled while waiting to retry |
| `waiting_review` | `completed` | system | An authenticated, version-checked decision arrived and a separate resume job was enqueued |
| `waiting_review` | `cancelled` | researcher, system | Run cancelled while waiting for review |

### workflow_stage

States (`WorkflowStage`), field `stage` of `WorkflowRun`. Starts in `collecting`; ends in `published`, `insufficient_evidence`, `cancelled`.

| From | To | Who | Trigger |
|---|---|---|---|
| `collecting` | `analysing` | system | Collection finished for every enabled connector (some may be partial) |
| `analysing` | `findings_review` | system | Draft findings with exact references are ready |
| `analysing` | `insufficient_evidence` | system | No eligible evidence supports any finding; no content revision is created |
| `findings_review` | `formatting` | moderator | Moderator generates content from selected approved finding revisions |
| `findings_review` | `analysing` | moderator, system | Match correction or evidence invalidation needs re-analysis |
| `formatting` | `final_review` | system | Draft generated and QA found no blocking issue |
| `final_review` | `formatting` | moderator | Changes requested, or an edit created a new revision that needs QA |
| `final_review` | `findings_review` | system | A dependency was invalidated; affected findings return to review |
| `final_review` | `approved` | moderator | Exact revision and hashes approved |
| `approved` | `publishing` | publisher | Publisher requested publication |
| `approved` | `findings_review` | system | Evidence invalidated before publication |
| `publishing` | `published` | system | Rendered page verified to show the activated revision |
| `publishing` | `approved` | system | Activation conflict; approval still holds and publication can be retried |
| `collecting` | `cancelled` | researcher, system | Run cancelled |
| `analysing` | `cancelled` | researcher, system | Run cancelled |
| `findings_review` | `cancelled` | researcher, system | Run cancelled |
| `formatting` | `cancelled` | researcher, system | Run cancelled |
| `final_review` | `cancelled` | researcher, system | Run cancelled |

### finding_review

States (`FindingReviewStatus`), field `review_status` of `Finding`. Starts in `pending`; ends in `superseded`.

| From | To | Who | Trigger |
|---|---|---|---|
| `pending` | `approved` | moderator | Moderator approves this exact revision after inspecting evidence |
| `pending` | `rejected` | moderator | Moderator rejects with a reason |
| `pending` | `changes_requested` | moderator | Moderator requests changes with a reason |
| `pending` | `superseded` | moderator, system | A newer revision was created before review |
| `changes_requested` | `superseded` | moderator, system | The requested change was made as a new revision |
| `approved` | `superseded` | moderator, system | An edit or an evidence invalidation created a new revision needing review |
| `rejected` | `superseded` | moderator | Moderator reworked a rejected finding as a new revision |

### review_excerpt

States (`FindingReviewStatus`), field `review_status` of `ReviewExcerpt`. Starts in `pending`; ends in `superseded`.

| From | To | Who | Trigger |
|---|---|---|---|
| `pending` | `approved` | moderator | Moderator approves this exact revision after reading the original; only when it has no consistency flag |
| `pending` | `rejected` | moderator | Moderator rejects with a reason (e.g. claims residence before possession) |
| `pending` | `changes_requested` | moderator | Moderator asks for other spans or a better translation |
| `pending` | `superseded` | moderator, system | A newer revision was created before review |
| `changes_requested` | `superseded` | moderator, system | The change was made as a new revision |
| `approved` | `superseded` | moderator, system | A new revision, or the source was edited or withdrawn |
| `rejected` | `superseded` | moderator | Moderator reworked a rejected review as a new revision |

### content_lifecycle

States (`ContentLifecycle`), field `lifecycle` of `ContentRevision`. Starts in `draft`; ends in `rejected`, `superseded`, `withdrawn`.

| From | To | Who | Trigger |
|---|---|---|---|
| `draft` | `final_review` | system | QA passed with no blocking issue |
| `draft` | `superseded` | moderator, system | A newer draft revision was saved |
| `final_review` | `approved` | moderator | Exact payload hash, manifest hash, epoch and state version approved |
| `final_review` | `rejected` | moderator | Moderator rejects with a reason |
| `final_review` | `changes_requested` | moderator | Moderator requests changes with a reason |
| `final_review` | `superseded` | moderator | An edit saved a newer revision |
| `final_review` | `withdrawn` | system | A dependency was invalidated |
| `changes_requested` | `superseded` | moderator, system | The change was made as a newer revision |
| `approved` | `superseded` | system | A newer revision was approved |
| `approved` | `withdrawn` | system | A dependency was invalidated; rollback can never revive it |

### publication_operation

States (`PublicationOperationStatus`), field `status` of `PublicationOperation`. Starts in `queued`; ends in `failed`, `rolled_back`.

| From | To | Who | Trigger |
|---|---|---|---|
| `queued` | `activating` | system | Preconditions re-checked: role, approval, recomputed hash, eligibility, expected version |
| `queued` | `failed` | system | A precondition failed before activation |
| `activating` | `delivery_pending` | system | Control-document compare-and-set and operation record committed in one transaction |
| `activating` | `failed` | system | Compare-and-set rejected (stale version, epoch or approval) |
| `delivery_pending` | `verified` | system | The rendered page's revision marker and hash match the activated revision |
| `delivery_pending` | `retry_wait` | system | Revalidation failed or timed out; state is reconciled before retrying |
| `retry_wait` | `delivery_pending` | system | Retry due after reconciliation |
| `retry_wait` | `failed` | system | Delivery deadline exceeded; activation stands and the console shows the delivery failure |
| `verified` | `rolled_back` | system | A later rollback operation activated a prior revision |

### serving_state

States (`ServingState`), field `serving_state` of `PublicationState`. Starts in `unpublished`; ends in no terminal state.

| From | To | Who | Trigger |
|---|---|---|---|
| `unpublished` | `active` | system | A publish operation activated a revision |
| `active` | `temporarily_disabled` | system | Evidence invalidation affects the active revision; the epoch is bumped |
| `temporarily_disabled` | `active` | system | An eligible, approved revision was activated (new revision or rollback) |
| `active` | `unpublished` | publisher, system | An unpublish operation requested by a publisher was activated |
| `temporarily_disabled` | `unpublished` | publisher, system | Unpublished, or no eligible prior revision remains |

### source_link

States (`SourceLinkStatus`), field `status` of `ProjectSourceLink`. Starts in `auto_accepted`, `needs_review`, `rejected`; ends in `superseded`.

| From | To | Who | Trigger |
|---|---|---|---|
| `needs_review` | `accepted` | moderator | Moderator confirms the match |
| `needs_review` | `rejected` | moderator | Moderator rejects the match with a reason |
| `auto_accepted` | `accepted` | moderator | Moderator confirms an automatic match |
| `auto_accepted` | `rejected` | moderator | Moderator corrects a wrong automatic match; dependants are invalidated |
| `accepted` | `rejected` | moderator | Moderator corrects an earlier decision; dependants are invalidated |
| `rejected` | `accepted` | moderator | Moderator reverses a rejection |
| `needs_review` | `superseded` | moderator | Split into segments or remapped to another project |
| `auto_accepted` | `superseded` | moderator | Split into segments or remapped to another project |
| `accepted` | `superseded` | moderator | Split into segments or remapped to another project |

### alias_proposal

States (`AliasProposalStatus`), field `status` of `AliasProposal`. Starts in `proposed`; ends in `rejected`, `revoked`.

| From | To | Who | Trigger |
|---|---|---|---|
| `proposed` | `approved` | researcher, moderator | Approved as standalone or context-required after the collision check |
| `proposed` | `rejected` | researcher, moderator | Rejected with a reason; kept so it is not proposed again |
| `approved` | `revoked` | researcher, moderator | Revoked; associations it produced return to review |

### record_lifecycle

States (`RecordLifecycle`), field `lifecycle` of `Evidence`. Starts in `active`; ends in `superseded`, `deleted`, `withdrawn`, `expired`.

| From | To | Who | Trigger |
|---|---|---|---|
| `active` | `stale` | system | Freshness threshold passed; still eligible, flagged for review |
| `active` | `superseded` | system | The source was edited; a new revision exists |
| `stale` | `superseded` | system | The source was edited; a new revision exists |
| `active` | `unavailable` | system | Temporary fetch failure; not confirmed deletion |
| `stale` | `unavailable` | system | Temporary fetch failure; not confirmed deletion |
| `unavailable` | `active` | system | Fetch restored with unchanged content |
| `active` | `deleted` | system | Deletion confirmed on repeat checks |
| `stale` | `deleted` | system | Deletion confirmed on repeat checks |
| `unavailable` | `deleted` | system | Deletion confirmed on repeat checks |
| `active` | `withdrawn` | moderator, admin, system | Source or policy withdrawal |
| `stale` | `withdrawn` | moderator, admin, system | Source or policy withdrawal |
| `unavailable` | `withdrawn` | moderator, admin, system | Source or policy withdrawal |
| `active` | `expired` | system | Retention period or policy expiry reached |
| `stale` | `expired` | system | Retention period or policy expiry reached |

### media_access

States (`MediaAccessStatus`), field `access_status` of `MediaInfo`. Starts in `discovered`; ends in `analysed`.

| From | To | Who | Trigger |
|---|---|---|---|
| `discovered` | `metadata_only` | system | No authorised transcript or media route |
| `discovered` | `access_pending` | system | A route exists but access is not yet granted |
| `access_pending` | `metadata_only` | system | Access refused |
| `access_pending` | `transcribed` | system | Authorised media transcribed with original timing |
| `metadata_only` | `access_pending` | system | An authorised route was obtained later |
| `transcribed` | `analysed` | system | Segments analysed into evidence |
| `discovered` | `error` | system | Processing error |
| `access_pending` | `error` | system | Processing error |
| `transcribed` | `error` | system | Processing error |
| `error` | `discovered` | system | Retried from the start |

### connector

States (`ConnectorStatus`), field `status` of `connectors.json`. Starts in `access_pending`; ends in no terminal state.

| From | To | Who | Trigger |
|---|---|---|---|
| `access_pending` | `live` | admin, researcher | Credential configured and the go-live demonstration recorded |
| `access_pending` | `unavailable` | admin, researcher | Access refused or not pursued |
| `live` | `unavailable` | admin, system | Credential revoked, contract ended or quota withdrawn |
| `unavailable` | `access_pending` | admin, researcher | A new credential was obtained but not yet demonstrated |

### deletion_request

States (`DeletionRequestStatus`), field `status` of `DeletionRequest`. Starts in `pending`; ends in `completed`.

| From | To | Who | Trigger |
|---|---|---|---|
| `pending` | `invalidating` | system | Invalidation job started: epochs bumped, serving gates checked |
| `invalidating` | `erasing` | system | Every affected control document is invalidated |
| `erasing` | `completed` | system | Payloads, embeddings, media and caches erased |
| `pending` | `failed` | system | Could not start |
| `invalidating` | `failed` | system | Invalidation failed; serving stays fail-closed |
| `erasing` | `failed` | system | Erasure failed; tracked until reconciled |
| `failed` | `pending` | system, admin | Retried |

### correction

States (`CorrectionStatus`), field `status` of `PublicCorrection`. Starts in `received`; ends in `resolved`, `dismissed`.

| From | To | Who | Trigger |
|---|---|---|---|
| `received` | `in_review` | moderator | Moderator picked it up |
| `received` | `resolved` | moderator | Resolved with a reason |
| `received` | `dismissed` | moderator | Dismissed with a reason |
| `in_review` | `resolved` | moderator | Resolved with a reason |
| `in_review` | `dismissed` | moderator | Dismissed with a reason |

## Classifications

### coverage

| Value | Meaning |
|---|---|
| `complete_for_query` | The permitted query was exhausted. Never means the platform or the internet was covered. |
| `partial` | Some pages or items could not be fetched; results so far are kept and labelled. |
| `unavailable` | The provider failed or refused for this run. A broad outage is not evidence of zero discussion. |
| `access_pending` | No demonstrated credential; the connector did not run. |

### verification

| Value | Meaning |
|---|---|
| `unverified` | A factual claim or allegation not yet checked against a dated primary record. |
| `verified` | Matches a cited, dated primary record. Counts of independent posts never make a claim verified. |
| `contradicted` | A cited, dated primary record says otherwise. |
| `disputed` | Sources conflict and no primary record settles it; both sides stay visible. |
| `not_applicable` | Opinions and promotions are attributed, never verified. |

### construction_status

| Value | Meaning |
|---|---|
| `new_launch` | Launched for sale; nobody lives there. First-hand living experience is not possible. |
| `under_construction` | Being built; owners are awaiting possession. First-hand living experience is not possible. |
| `partially_ready` | Some phases handed over. Living experience is possible only for a ready phase, so the phase must be identified. |
| `ready_to_move` | Handed over. Residents' experience is possible. |

### date

| Value | Meaning |
|---|---|
| `known` | The date comes from platform metadata, page markup, a registry record or a moderator. |
| `approximate` | Only a coarse date is known (month or year); precision says which. |
| `unknown` | No date could be established. Collection time is never substituted. |
