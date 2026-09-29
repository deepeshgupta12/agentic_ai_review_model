# Step 04 test plan and logs

Step 04 maps what sources say to the right project and phase before anything can become a finding ([step spec](../../steps/04-project-identity.md)). It adds:

- the project catalogue and configuration APIs;
- construction status per phase (I16);
- deterministic matching, with source links and evidence spans;
- moderator corrections;
- alternate-name proposals (A01 plus backend checks);
- bounded search queries;
- an identity evaluation.

No source is collected yet (that is Step 05), so matching is exercised on a clearly fictional catalogue. The real catalogue never receives made-up text: the check script confirms it holds no fixture data and no stored sources.

Run the commands from the repository root with the stack up (`make up`). In zsh, run `setopt interactivecomments` once if you paste commands that contain `#` comments.

## Run everything

```bash
git pull
bash scripts/run_step04_checks.sh
bash scripts/run_step04_mutations.sh
```

The first script covers:

- the Steps 01–03 regression;
- the backend and web gates;
- repeatable setup and seeding, including the 8 status records;
- the catalogue and configuration APIs through the web app;
- query plans for all five projects;
- three dry-run matches on the real catalogue;
- the whole identity path on the fictional catalogue in a scratch database, including the real worker;
- the identity evaluation;
- six negative checks and hygiene.

It saves `logs/step-04/checks-<UTC time>.log` and ends with `ALL CHECKS OK`. The second script disables sixteen identity rules one at a time; each must be caught by its own test, ending with `ALL MUTANTS CAUGHT`.

## Try it yourself

```bash
make plan-queries
docker compose exec -T api python -m app.cli match-text --text "DLF Privana West, Sector 76 Gurgaon"
docker compose exec -T api python -m app.cli match-text --text "M3M Antalya Hills 3 BHK floors in Sector 79"
docker compose exec -T api python -m app.cli match-text --text "Parq has a nice park" --focus conscient-parq-sector-80-gurgaon
make smoke-identity
make eval-identity
```

- `plan-queries` lists up to 12 search queries per enabled search connector for each project. Names and RERA IDs come first; phase names and approved aliases follow. Unapproved proposals are never used.
- `match-text` is a dry run; nothing is stored. Expected results for the three examples:
  1. DLF Privana, auto-accepted, West phase (GGM/819/551/2024/46).
  2. M3M Antalya Hills with the phase unknown: "3 BHK" is not "Antalya Hills 3".
  3. Rejected, because "Parq" needs Conscient or Sector 80 alongside it.
- `smoke-identity` runs six checks on a scratch database and drops it.
- `eval-identity` prints the metrics below and stores the run.

In the console, http://localhost:3000/console still shows the dashboard. The review screens for links and names come in Step 09; until then the decisions are made through the API.

## Use cases

| ID | Use case | What it proves | Tests |
|---|---|---|---|
| UC-26 | Catalogue and configuration | Import is repeatable and needs an Idempotency-Key: the same key replays the result, and a different body returns 409. Optional micromarket, developer and RERA fields don't block import. List and detail match the contract. Configuration changes need the expected version, and status records must name the project's own registrations. Aliases change only by decision. The 8 phase-status records seed idempotently. Antalya Phase II, confirmed ready to move on 29 Sep 2026, accepts living claims dated after that; before that date, the project-level status applies. A DLF Privana West living claim is flagged | 7 |
| UC-27 | Deterministic matching | These cases go to review or are rejected, never auto-accepted: name without place, same name in another city, context-required names alone, "3 BHK", several projects in one paragraph, prompt injection. Phase names match with numeral variants. Comparison articles and videos split into per-project segments | 19 |
| UC-28 | Links, evidence and corrections | One source revision is stored once, with one link per project segment. Evidence is created for linked segments only. Moderators can accept (with phase), reject, split or remap at the expected version, within the state machine, with a reason. Leaving an accepted state makes evidence ineligible at once and enqueues invalidation | 9 |
| UC-29 | Alternate names (D17) | A proposal is refused when it: lacks a cited strong identifier, even as valid JSON; cites evidence outside the task; or names something not in the evidence. Duplicates merge and origins are counted. The collision check is deterministic. Proposals change no query or match until approved. Generic or colliding names can only be context-required. Revoking returns matches to review. Rejected names become exclusions. Roles, versions and reasons are enforced | 10 |
| UC-30 | Bounded queries | Plans fit the DiscoveryPlan contract. They use only enabled search connectors and are capped and deduplicated. Identifier queries let unknown names surface. Context-required names are paired with the developer or locality | 5 |
| UC-31 | A01 identity agent | It sees review segments only. Source text is marked untrusted, and the request uses the contract schema. It annotates but cannot accept. Unknown project IDs it returns are ignored. Its proposals go through the backend checks. A refusal is recorded and changes nothing. Without a key it is not called. The live smoke option checks a real-shaped answer | 7 |
| UC-32 | Identity evaluation | Every metric is reported with its sample size. The dataset is labelled synthetic and uses fictional projects only. The fixture smoke check passes and drops its scratch database | 3 |

Backend total: 143 tests (83 from Step 03 plus 60 new), run against the Compose MongoDB replica set.

## Identity evaluation (synthetic)

| Metric | Value | Sample |
|---|---|---|
| Auto-accept precision (target 98%) | 100% | 22 auto-accepted pairs |
| Relevant pairs linked (auto or review) | 96.7% | 30 relevant pairs |
| Relevant pairs auto-accepted | 73.3% | 30 |
| Linked pairs sent to review | 29.0% | 31 |
| Wrong phase | 0% | 6 pairs with a labelled phase |
| Same name in another city rejected | 100% | 2 |
| Unrelated or undecidable pairs kept out of auto-accept | 100% | 11 |
| Comparison split per project | 100% | 2 |

The one miss is case c26: the project name written in Hindi script, with no approved Hindi-script alias. That's expected; A01 script-variant proposals are the route for it.

These figures come from 36 synthetic, fictional cases written alongside the rules. They show the rules behave as designed. They do not measure real-world precision. Real labelled data from collected sources replaces them at Step 12 (D39). Alias-proposal precision needs live A01 output and stays unmeasured until the Anthropic key exists (I02).

## Negative checks (in the script)

| Check | What is tried | Expected result |
|---|---|---|
| N1 | Reuse an Idempotency-Key with a different import body | 409 `idempotency_conflict` |
| N2 | Change a configuration at an old version | 409 `version_conflict` |
| N3 | Give DLF Privana a status record for an M3M Antalya Hills registration | 422 |
| N4 | Replace aliases through the configuration API | 422 (aliases change only by decision) |
| N5 | Reject a link without a reason | 422 |
| N6 | Store a link with a status outside the contract | MongoDB `Document failed validation` |

## Mutation check (second script)

These rules are each disabled, one at a time, and must be caught:

- same name in another city;
- context-required names;
- the "3 BHK" guard;
- several projects in one passage;
- the auto-accept threshold;
- link version checks, the state machine and invalidation on leaving an accepted state;
- the strong-identifier requirement;
- evidence from the task input only;
- context-required-only approval for generic or colliding names;
- revoke returning matches to review;
- the model unable to change a link status;
- rejected names becoming exclusions;
- the Idempotency-Key body check;
- status records naming only the project's own registrations.

The first run found two weak tests, both strengthened before the recorded run:

- The "3 BHK" test's text didn't put the number right after the name, so it never exercised the guard. The same fix went into evaluation case c14.
- The outside-evidence test cited only outside evidence, so it couldn't tell "any foreign citation" from "all". A mixed citation is now tested.

## Recorded results

| Date (UTC) | Commit | Run by | Command | Result | Log |
|---|---|---|---|---|---|
| 2026-09-28 12:13 | `da76682` | Implementer | `bash scripts/run_step04_checks.sh` | ALL CHECKS OK, 32/32; 141 backend tests; N1–N6 as expected | [checks-20260928T121315Z.log](checks-20260928T121315Z.log) |
| 2026-09-28 12:16 | `da76682` | Implementer | `bash scripts/run_step04_mutations.sh` | ALL MUTANTS CAUGHT, 16/16 | [mutation-check-20260928T121611Z.log](mutation-check-20260928T121611Z.log) |
| 2026-09-28 | `da76682` | GitHub Actions | CI, including the identity smoke check and evaluation in the Compose containers | All four jobs passed | [run 36420418930](https://github.com/deepeshgupta12/agentic_ai_review_model/actions/runs/36420418930) |
| 2026-09-29 04:12 | `ed57fdf` | Implementer | `bash scripts/run_step04_checks.sh` after adding the comparison-video test | ALL CHECKS OK, 32/32; 142 backend tests | [checks-20260929T041158Z.log](checks-20260929T041158Z.log) |
| 2026-09-29 04:20 | `4606c3a` | Product owner, own terminal | `bash scripts/run_step04_checks.sh` | ALL CHECKS OK, 32/32; independent confirmation before approval | [checks-20260929T042049Z.log](checks-20260929T042049Z.log) |
| 2026-09-29 04:24 | `4606c3a` | Product owner, own terminal | `bash scripts/run_step04_mutations.sh` | ALL MUTANTS CAUGHT, 16/16 | [mutation-check-20260929T042446Z.log](mutation-check-20260929T042446Z.log) |

No live integration was run. There's no Anthropic key yet, so A01 is tested only with a recorded fake client, and no source connector exists until Step 05.

## Step 04 acceptance checks

- [x] The same name in a different city is rejected, or goes to review when the project's own city is also named (UC-27; evaluation 2/2).
- [x] A comparison video links to two projects through distinct time segments, and a comparison article through paragraph segments, without duplicating the source (UC-27, UC-28, fixture smoke check). Real video segments arrive with authorised transcripts at Step 06.
- [x] Absent micromarket, developer or RERA fields don't block onboarding (UC-26).
- [ ] An identity correction invalidates dependent findings and final approval. **Partly done.** A correction makes the evidence on that link ineligible at once, and the worker runs the invalidation job (UC-28, smoke check). Findings and approvals don't exist until Steps 07–11; they join the same job then.
- [x] Auto-accept precision is measured against the agreed target, with sparse and synthetic labels disclosed (UC-32; D39).
- [x] An alias proposal without a cited span showing a strong identifier is rejected by the backend, even when the model output is valid JSON (UC-29, UC-31).
- [x] A proposed alias affects no query or match until approved; one that collides or is generic can only be approved as context-required (UC-29).
- [x] Revoking an approved alias sends the associations it produced back to review (UC-29; D35).
- [x] Relevant repository checks were actually run and their results recorded (above).
- [x] PROGRESS.md records changed paths, decisions, evidence, unresolved dependencies and the next action.
- [x] Product owner approved items P–T on 29 Sep 2026 after running both scripts.

## Approvals (P–T), all approved by the product owner on 29 Sep 2026

| Item | Decision | Where |
|---|---|---|
| P | Small contract amendment. A match can go back to review, done only by the system, when an alias it relied on is revoked or a status check flags it | D35 |
| Q | Matching rules: <ul><li>auto-accept needs a RERA ID, or the name with its sector or developer (score 550 of 1000);</li><li>a name without its place goes to review;</li><li>the same name with another city is rejected;</li><li>comparisons are split per project;</li><li>A01 only advises on review items and never accepts or rejects</li></ul> | D36 |
| R | Alternate-name rules: <ul><li>a proposal needs a cited span showing the name with a RERA ID, the project name, or the developer with the sector;</li><li>names shared with another project, or made of generic words such as "Parq", "West" or a sector, can only be used alongside the developer or locality;</li><li>revoking a name returns its matches to review</li></ul> | D37 |
| S | Storage and interim sources: <ul><li>source text kept in an erasable payload store;</li><li>source policies read from the seed file until Step 05;</li><li>your phase statuses in `seed/construction_status.json`, with DLF Privana treated as under construction at project level;</li><li>up to 12 search queries per connector</li></ul> | D38 |
| T | The identity evaluation is synthetic until Step 12; real precision is measured on collected, labelled data then | D39 |

Settled on 29 Sep 2026: M3M Antalya Hills Phase II is ready to move (product owner). Still open: the Anthropic key (I02) goes into `.env` with `make set-secret NAME=ANTHROPIC_API_KEY`. After that, `make smoke-model` and `docker compose exec -T api python -m app.cli fixture-smoke-identity --live-a01` verify the model and A01 live.
