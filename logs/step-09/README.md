# Steps 09 and 10 test plan and logs

Step 09 builds the moderator console ([step spec](../../steps/09-cms-moderation.md)) and Step 10 the page content with its checks and final approval ([step spec](../../steps/10-seo-aeo-and-editorial-qa.md)). The product owner asked for the whole frontend end to end in these steps, driving the real system (D64), so the publication core was built with them. Both steps share one check script and this log folder; [logs/step-10](../step-10/README.md) points here.

No run was started and no model was called for these steps (product owner, 13 Oct 2026: "Do not reinitiate the run, you consumed all my credits"). Generation with findings (A08, A09) is tested with the scripted model of the workflow tests; a page from reviews alone calls no model at all.

## What is checked

| Area | How | Where |
|---|---|---|
| Finding and review edits keep the evidence rules; stale bases conflict | API tests | `backend/tests/test_console_api.py` |
| Users and roles admin-only; no self lock-out; deactivation ends sessions; audit and evaluations listed | API tests | `test_console_api.py` |
| Public corrections: honeypot, per-address limit, moderated | API tests | `test_console_api.py` |
| Add one project from the console (D58), never updating an existing one; real portfolio rows | API tests | `test_console_api.py` |
| Reviews-only page needs no model; findings page cites only approved revisions and keeps caveats | Workflow with the scripted model | `backend/tests/test_content.py` |
| QA blocks opinion written as fact, new numbers, lost caveats, occupancy words before possession, changed reviews, foreign references | Unit checks on real generated payloads | `test_content.py` |
| Final approval binds hashes, epoch and state version; roles; an edit is a new revision an old approval cannot publish | API tests | `test_content.py` |
| Publication activates once (idempotent), is verified from the rendered page, never serves a draft; wrong markers fail; withdrawal stops serving and blocks rollback; unpublish | API and worker tests with a fake web app | `test_content.py` |
| Prompt caching: only the instructions are marked, above the model's minimum; 1-hour cache in batches; cache prices | Gateway tests | `backend/tests/test_gateway.py` |
| Console role map equals the contract | Web unit test | `web/lib/roles.test.ts` |
| Browser journeys: add a project (run dialog warns about paid calls), decide findings and reviews beside evidence, generate from reviews, approve and publish, verify the public page markers, edit as a new revision, reader correction, analyst without controls | Playwright on the journey database `sy_poc_e2e` with the real `.env` (live mode); the journey worker takes no collection, analysis or media job | `web/e2e/journeys.spec.ts`, `scripts/run_step09_e2e.sh` |
| Each safety rule above is load-bearing | Mutation check (12 rules) | `scripts/run_step09_10_mutations.sh` |
| Whole step, including "the checks spent nothing" (model calls and quotas unchanged) | Check script | `scripts/run_step09_10_checks.sh` |

## Recorded results

| Date (UTC) | Commit | Run by | Command | Result | Log |
|---|---|---|---|---|---|
| 2026-10-13 | worktree | Implementer | backend suite, ruff, mypy after the console API, content, publication and prompt caching | 394 passed in 28 min (17 new console and content tests, 3 new caching tests); lint, format and types clean | (console) |
| 2026-10-13 | worktree | Implementer | web lint, TypeScript and unit tests after every console screen | clean; 15 unit tests (role map equals the contract) | (console) |
| 2026-10-13 | worktree | Implementer | stack rebuilt in live mode with the real `.env` (`docker compose up -d --build --wait`) | every service healthy; `/healthz` mode live; API holds Anthropic, Brave, Firecrawl, Scrapfly and YouTube keys (names only); no run started | (console) |
| 2026-10-13 | worktree | Implementer | `bash scripts/run_step09_e2e.sh` (first) | 1 of 6 passed, then the review journey clicked the next Approve while the page was still refreshing (one decision recorded, the second never sent); the journey now waits for each decision to show | [e2e-20261013T100158Z.log](e2e-20261013T100158Z.log) |
| 2026-10-13 | worktree | Implementer | `bash scripts/run_step09_e2e.sh` | 6/6 journeys passed in 24 s; seed used only the scripted model (A05, A05, A07, A11 answered locally) | [e2e-20261013T100532Z.log](e2e-20261013T100532Z.log) |
| 2026-10-13 | worktree | Implementer | `bash scripts/run_step09_10_mutations.sh` | 12/12 rules caught | [mutation-check-20261013T100645Z.log](mutation-check-20261013T100645Z.log) |
| 2026-10-13 | worktree | Implementer | `bash scripts/run_step09_10_checks.sh` (a first attempt was stopped at a 121-character comment line, fixed, and its partial log removed) | 23/23 checks OK: regression, contracts (api 1.4.0, content 1.1.0, routes 1.1.0), ruff, mypy, 394 backend tests, web gates, images, stack healthy in live mode with the real credentials, new collections, every console screen for a real project, contracts through the API, public page serves no draft, prompt caching, journeys 6/6, hygiene; model calls (192, $2.4755) and every provider quota unchanged before and after | [checks-20261013T101601Z.log](checks-20261013T101601Z.log), [e2e-20261013T104556Z.log](e2e-20261013T104556Z.log) |
