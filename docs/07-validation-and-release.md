# Validation and one-release acceptance

Tests and evaluations are implementation deliverables. This handoff does not assert that any product check has passed. Use deterministic fixtures for automated checks and separately authorised real data for source and model qualification.

## Dataset design

Create a versioned manifest across the five projects and confirmed launch languages, targeting 150–300 authorised source items if enough chatter exists. Include similarly named projects, phase confusion, mixed-project videos, sparse discussion, positive/negative/neutral opinions, promotions, copied sources, temporal changes and contradictions. Add clearly synthetic adversarial fixtures separately.

Label relevance, correct project/segment and phase, alias mentions, aspects, polarity, fact/opinion/type, evidence span, source-origin cluster, contradictions, translation errors and editorial support. Use an adjudication record for ambiguous labels. Split by source-origin cluster and time before tuning to avoid duplicate leakage; hold out projects for robustness where feasible. Report sample sizes, exclusions and uncertainty. Lack of chatter is a result, not permission to fabricate real examples.

## Release gates

| Area | Target / required evidence |
|---|---|
| Scope | All 14 work packages complete and all core capabilities in one release candidate |
| Source access | Every agreed mandatory capability tested with entitled real accounts; optional limits visible |
| Identity | At least 98% precision on auto-accepted matches; report recall, ambiguity and per-project/language results, plus alias-proposal precision and moderator approval rate |
| Retrieval | At least 90% recall@10 on labelled evidence queries, separately by launch language |
| Grounding | All published substantive statements trace to eligible evidence; at least 95% draft support in human audit |
| Critical errors | Zero known critical unsupported claims in the acceptance sample |
| Approvals | All attempts without approval of the exact current revision/hash are rejected |
| Recovery | Worker crash/lease expiry, duplicate events and timeout-after-write recover without duplicate publication or lost decisions |
| Refresh | At least 95% of scheduled jobs meet the agreed window, with reported outage exclusions |
| Page delivery | Approved publication reaches verified rendered content within five minutes under normal operation of the Compose environment |
| UI | p95 common reads under two seconds at documented concurrency and realistic corpus |
| Editorial capacity | Measured review workload fits named moderator capacity and queue targets |
| Security | Blocking findings closed; source/role/approval boundaries verified |

These are proposed targets inherited from the plan. Record agreed thresholds and measurement definitions before tuning. A small passing sample is not proof of perfect future behavior. Do not weaken gates silently to make a release pass.

## Test layers

1. Unit/property checks: canonicalisation/hash, schemas, transitions, anchor bounds, eligibility, matching rules, cursor keys and retry budgets.
2. MongoDB integration: unique indexes, optimistic concurrency, lease fencing, checkpoint persistence, chosen atomicity strategy, lifecycle invalidation and erase/retrieval behavior.
3. Connector contracts: pagination, duplicates, null fields, revocation, quota, schema drift, deleted content, unavailable comments/media and date semantics.
4. Model evaluations: wrong-project inclusion, unsupported facts, contradictory evidence, numerical transcription errors, language preservation and abstention. Use human audits as well as automated graders.
5. Console and public-page browser journeys: configuration, search, video state, finding edit/reject, final preview approval, conflict handling, publishing, correction and rollback. Verify keyboard access and mobile/desktop rendering where relevant.
6. Security checks: source prompt injection, XSS, CSRF where applicable, SSRF/private host redirects, role bypass, forged webhooks, secret exposure, oversized files and unauthorised project reads.
7. Recovery/load: five projects together, realistic retained corpus, controlled burst above observed load, worker/process restart, web-app outage during revalidation and ambiguous publication timeout.

## Evidence records and commands

Step 03 establishes real repository commands for formatting, types, unit/integration tests, frontend build, browser tests and fixture smoke checks. Later steps add evaluation and release commands. Record command, commit, fixture/data version, environment, timestamp and result for each gate. Redact credentials/source text from artifacts. A checklist tick without an actual result is not evidence.

## Full user acceptance scenario

Import five user projects into the seeded catalogue; collect entitled text and video sources; display partial access honestly; produce anchored findings; reject at least one, edit another, and accept supported findings; generate SEO/AEO copy; approve the exact preview; publish to the public project page; verify rendered revision; trigger new chatter and a withdrawn source; demonstrate re-review, correction/unpublish and eligible rollback. Demonstrate sparse evidence without manufactured pros/cons.

The release report names incomplete coverage, outstanding nonblocking defects, measured spend, source/model/dependency versions, moderation time and operating owners. Release only after the product owner accepts the candidate and actual publication actions are approved in the console. All code is delivered together as one tagged repository version and Compose stack; no cloud project is required.
