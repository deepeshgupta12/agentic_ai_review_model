# Step 05 test plan and logs

Step 05 collects what is said publicly about the five projects and feeds it to Step 04 identity ([step spec](../../steps/05-text-and-social-connectors.md)). It adds:

- source policies in the database;
- safe fetching;
- three live connectors: Brave Search for discovery, the web reader for allow-listed pages, and the YouTube Data API for videos and comments;
- collection runs with honest coverage;
- the source lifecycle (unavailable, deleted, withdrawn, expired, edited), with re-checks of stored sources;
- the run and source APIs.

Everything below was run against the real sites and APIs for the five projects. Nothing was invented, and fixture data stays in test databases.

Run the commands from the repository root with the stack up (`make up`). In zsh, run `setopt interactivecomments` once if you paste commands that contain `#` comments.

## Run everything

```bash
git pull
make up
bash scripts/run_step05_checks.sh
bash scripts/run_step05_mutations.sh
```

The first script covers:

- the Steps 01–04 regression;
- the backend and web gates;
- repeatable setup and seeding;
- the policy, run, event-stream, source and health APIs through the web app;
- six negative checks;
- the collection rules checked on the real stored data;
- hygiene.

It starts no collection and uses no Brave or YouTube quota. It saves `logs/step-05/checks-<UTC time>.log` and ends with `ALL CHECKS OK`.

The second script disables twenty-three collection rules one at a time; each must be caught by its own test, ending with `ALL MUTANTS CAUGHT`.

## Try it yourself

```bash
make verify-collection
make recheck
make collect
```

- `verify-collection` is read-only. It checks the stored data against twelve rules, including policy, robots.txt, metadata-only and threads.
- `recheck` re-checks stored pages and YouTube records for edits and deletions. It uses YouTube units (1 per record) and paces web requests.
- `collect` starts a real run for all five projects. It takes about 30 minutes and uses roughly 80 Brave requests (of 2,000 a month), 20 YouTube searches (of 100 a day) and up to 50 Claude calls. Running it again reads only pages not read before.

In the console, http://localhost:3000/console still shows the dashboard. The review screens for sources, links and alias proposals come in Step 09. Until then the APIs below serve them:

- `/v1/projects/{id}/runs`
- `/v1/runs/{id}` and `/v1/runs/{id}/events`
- `/v1/projects/{id}/sources`
- `/v1/sources/{id}/revisions/{n}`
- `/v1/connectors/health`

## Use cases

| ID | Use case | What it proves | Tests |
|---|---|---|---|
| UC-33 | Source policies | Seeded versions are current and match the contract. A stored version cannot change; a new one is created. The host decides the family, and a generic web host must be on the allow-list. Narrowing rights applies at once and is re-checked. Roles, and the chain of rights (collection, then AI use, then quotation and derived publication), are enforced | 15 |
| UC-34 | Safe fetching and storage | Refused, each hop re-checked: private, loopback and link-local addresses, odd URLs, too many redirects, oversized or wrong-type responses. An honest user agent is sent. Retry-After and backoff are respected. Hosts are paced. robots.txt follows RFC 9309, except that a robots.txt that refuses us (401, 403, 451; 429 after retries) means nothing is fetched (D45). URLs are normalised. Quotas are reserved atomically. The same page makes no new revision, and neither does a search hit found under another title; an edit makes one. Metadata-only items carry no text, and full content needs its text | 25 |
| UC-35 | Brave discovery | Hits are metadata only, never evidence. Paging stays in budget. A refusal is explicit. No request is made without quota | 2 |
| UC-36 | Web reader | These pages are never requested: not allowed by policy, disallowed by robots.txt, or reached through a redirect to a host that isn't allowed. Refusals are recorded and not worked around. Thin pages are counted. An allowed redirect is stored where it landed, with both addresses logged. Dates come only from markup | 6 |
| UC-37 | YouTube | Videos are metadata only, and titles are not evidence. Comments keep their thread: a reply belongs to its top comment. Search and units are separate quota buckets. Comments turned off is recorded as a fact | 2 |
| UC-38 | Collection runs | A run collects from each planned connector and reports honest coverage. Metadata never becomes evidence. Comments inherit their thread and follow it back to review. Replay creates no duplicates. One provider's outage leaves the others complete. Without credentials, nothing runs and coverage says so. Cancelling stops the jobs and keeps what was found. A connector the run didn't plan is never called. Only a page that may read next time leaves coverage partial. A redirected page isn't read twice. `verify-collection` catches planted violations. A connector added later joins existing configurations | 14 |
| UC-39 | Lifecycle and re-checks | One failure is temporary. Deletion needs two consecutive "gone" results. Erasure waits for invalidation. Withdrawal is idempotent. Retention expires old sources. A re-check turns an edit into a new revision linked to the same project, recovers from a temporary failure, corrects a stated date with an audit event, and deletes a removed video. Without a key, nothing is checked. Withdrawal, confirmed deletion and expiry reach older revisions too (D45) | 13 |
| UC-40 | Run, source and health APIs | Starting a run needs an Idempotency-Key and the researcher role, and replays. A source whose link the rules rejected matches the contract. Runs can be listed, read and cancelled. The event stream resumes from Last-Event-ID. Sources are filtered. Revision detail gives UTF-16 offsets, where each emoji counts as two. Withdrawal works through the API. Health shows real activity, including the web reader's | 7 |

Backend total: 231 tests (147 from Steps 03–04 plus 84 new), run against the Compose MongoDB replica set. Tests never see real credentials: the repository `.env` and credential variables in the shell are hidden from them.

## Live runs (30 Sep 2026)

The first run covered Conscient Parq only (03:36–03:43 UTC). A run for all five projects followed (04:35–05:06 UTC, one worker). Figures come from each run's recorded coverage.

| Project | Brave queries / hits kept | Web reader: attempts, pages read, matched | YouTube: searches, records (videos + comments), matched | Videos waiting for review |
|---|---|---|---|---|
| Conscient Parq (first run) | 12 / 108 | 40, 29, 14 (coverage repaired from the fetch log, item 1 below) | 4, 70, 62 | 5 |
| DLF Privana | 19 / 162 | 40, 34, 18 | 4, 111, 104 | 16 |
| Conscient Parq | 12 / 109 | 11, 0 new (29 already read), 0 | 4, 61, 52 | 5 |
| Sobha Crescent | 12 / 137 | 40, 31, 18 | 4, 217, 203 | 21 |
| M3M Forestia West | 11 / 108 | 36, 25, 7 | 4, 36, 23 | 11 |
| M3M Antalya Hills | 24 / 220 | 32, 25, 7 | 4, 168, 163 | 15 |

Brave hit counts include the same address found by several queries.

**Stored now: 905 records.**

- 264 unique Brave hits (metadata only).
- 158 page revisions: 87 current; 71 MagicBricks revisions withdrawn and erased (item 6 below).
- 203 videos (metadata only) and 280 comments.

**Links:**

| Status | Links |
|---|---|
| auto-accepted | 422 |
| in review | 98 |
| rejected | 118 |

There are 350 evidence spans. Spans on withdrawn pages are ineligible and their text is erased.

**Spend:**

- Brave: 100 of 2,000 requests this month.
- YouTube: 24 searches and 278 units on the collection day, plus 456 units for re-checks.
- A01: 45 Claude calls (claude-sonnet-5, 192,935 input and 35,445 output tokens). All completed, and none changed a link status.

Re-checks: 4 passes and 799 checks over 627 re-checkable records.

| Result | Count | Notes |
|---|---|---|
| Present | 785 | |
| Changed | 14 | Stored as new revisions; all were MagicBricks listing pages |
| Gone or unreachable | 0 | |
| Stated dates corrected | 13 of 144 pages | Each is now "unknown": they had been guessed from text such as copyright years |

`verify-collection` passes all 13 rules on the stored data ([log](verify-collection-20260930T101422Z.log)). The go-live evidence for the three connectors is in [live-connectors](live-connectors-20260930T110436Z.log). Collection logs: [first run](live-collect-parq-20260930T033613Z.log), [five projects](live-collect-all-20260930T043528Z.log), [re-checks](live-recheck-20260930T064644Z.log).

## What the live runs found, and what changed

Running against real sites found ten problems that the tests had missed. Each is now fixed and covered by a test:

1. **The web reader ran for a project that had not enabled it.** The first Conscient Parq run read 29 pages although `web_fetch` wasn't in that project's configuration, and the run's coverage didn't mention it. A run now uses only the connectors it planned (D43). Configurations seeded before a connector existed now receive it with its default (`seed-projects`). The first run's coverage was repaired from the fetch log with an audit event ([repair log](repair-first-run-20260930T051701Z.log)).
2. **A redirect wasn't traceable.** A DLF blog address redirected to another path. The fetch log named only the address asked for, while the page was stored where it landed. The log now keeps both addresses, and the page takes the policy of where it landed. The one record was repaired, with the evidence recorded (the page was stored 5 ms after that fetch, with no other fetch in between).
3. **Guessed dates.** All 144 pages had a "publication date". Trafilatura's default date search also reads free text, for example "Updated on 29 September". Dates now come only from structured markup (D44), and the re-check corrected the stored dates with an audit event for each.
4. **Coverage status depended on luck.** The same permanent error made coverage `partial` for one project and `complete` for another. Now only a page that may read next time (a retryable error) makes coverage partial.
5. **A code path read the real keys in tests.** The new re-check handler asked the global settings for credentials, and in tests those came from the repository `.env`. No request left the machine, because tests use a fake internet. Tests now run without the `.env` file and without credential variables.

6. **Sites that refused our crawler were read.** Sites behind bot protection answered robots.txt with 403 and a challenge page, and the code read that as "no robots.txt" (RFC 9309 allows that reading). Asked again, 14 of 15 such hosts refuse us, including MagicBricks, whose project pages D34 had already recorded as off-limits. A refusal now means nothing is fetched from that site (D45). All 57 MagicBricks pages (71 revisions) were withdrawn, their text erased and their evidence made ineligible ([clean-up log](withdraw-robots-refused-20260930T101129Z.log)). `verify-collection` now checks that no page is kept from a site that refused us.
7. **Older revisions kept their text.** Withdrawal, confirmed deletion and retention expiry changed only the current revision; the contract gave a superseded revision no way to be withdrawn. State machines 1.2.0 adds those transitions, and the lifecycle applies them to every revision (D45).
8. **Search hits multiplied.** The same address found by different queries under slightly different titles became revisions 2, 3 and 4. A search hit's title is not content, so it is now the same record.

9. **A rule-rejected link could not be shown.** The first run of the check script found that a page's detail failed its contract: a link the matching rules had rejected carried no decision, which the schema demanded. The schema now asks for a decision only on `accepted` links (`sources.schema.json` 1.1.0, D45).
10. **Health hid two working connectors.** The web reader and Claude showed no last success, because health read only cursor state. It now reads the fetch log and agent runs.

There was also a gap: stored sources were never re-checked, because the lifecycle rules had no driver. The `check_availability` job (D44) now does this, run by `make recheck` until refresh arrives at Step 13.

## Negative checks (in the script)

| Check | What is tried | Expected result |
|---|---|---|
| N1 | Start a run without an Idempotency-Key | 422 |
| N2 | Start a run with `reddit_api`, which no project enables | 422 `validation_failed` (no run starts) |
| N3 | Cancel an unknown run | 404 |
| N4 | Withdraw a source without an Idempotency-Key | 422 |
| N5 | Create an incomplete policy version | 422 |
| N6 | Store a job with a kind outside the contract (the same record with a valid kind is accepted and rolled back first) | MongoDB `Document failed validation` |

## Mutation check (second script)

These rules are each disabled, one at a time, and must be caught by their own test:

- **Policy and fetching:**
  - policy before any request;
  - robots.txt;
  - the policy check on every redirect hop;
  - both addresses in the fetch log;
  - dates from markup only;
  - non-public addresses refused;
  - no Brave request without quota;
  - the generic web allow-list.
- **Storage and runs:**
  - no text on metadata-only items;
  - no new revision for an unchanged page;
  - only planned connectors;
  - partial coverage only for retryable errors;
  - inherited comment links following their parent.
- **Lifecycle and checks:**
  - two consecutive "gone" results before deletion;
  - erasure only after invalidation;
  - edits becoming new revisions;
  - date corrections;
  - `verify-collection` catching evidence from metadata-only records;
  - the Idempotency-Key on runs.

## Recorded results

| Date (UTC) | Commit | Run by | Command | Result | Log |
|---|---|---|---|---|---|
| 2026-09-30 03:36 | `0fa6640` + fixes in progress | Implementer | `collect --project conscient-parq-sector-80-gurgaon` | Run completed. The CLI summary failed on a field name, since fixed. Found item 1 | [log](live-collect-parq-20260930T033613Z.log) |
| 2026-09-30 04:35 | `0fa6640` + fixes in progress | Implementer | `collect` (five projects) | 5 runs completed in 31 minutes; no job failed | [log](live-collect-all-20260930T043528Z.log) |
| 2026-09-30 05:17 | same | Implementer | record repairs (items 1 and 2) | Coverage repaired from 40 fetch records; one fetch record backfilled; a repeat run changed nothing | [log](repair-first-run-20260930T051701Z.log) |
| 2026-09-30 05:17 | same | Implementer | `verify-collection` | 12/12 | [log](verify-collection-20260930T051712Z.log) |
| 2026-09-30 06:46 | same | Implementer | `recheck-sources` ×4 | 799 checks: 785 present, 14 changed (new revisions), 13 dates corrected | [log](live-recheck-20260930T064644Z.log) |
| 2026-09-30 06:55 | same | Implementer | `bash scripts/run_step05_mutations.sh` | 15 of 19 shown caught. Two were caught, but the script missed parametrized test names; one targeted the wrong test; one exposed a weak test (metadata-only text). All four fixed | [log](mutation-check-20260930T065504Z.log) |
| 2026-09-30 07:41 | same | Implementer | `bash scripts/run_step05_mutations.sh` | ALL MUTANTS CAUGHT, 19/19 | [log](mutation-check-20260930T074151Z.log) |
| 2026-09-30 10:11 | same | Implementer | D45 clean-up | 14 of 15 hosts refuse our crawler; 57 MagicBricks pages (71 revisions) withdrawn and erased | [log](withdraw-robots-refused-20260930T101129Z.log) |
| 2026-09-30 10:14 | same | Implementer | `verify-collection` | 13/13 on 905 records | [log](verify-collection-20260930T101422Z.log) |
| 2026-09-30 11:04 | same | Implementer | go-live evidence | brave_search, web_fetch and youtube_data_api marked live | [log](live-connectors-20260930T110436Z.log) |
| 2026-10-01 06:03 | `5e0cfd6` | Implementer | `bash scripts/run_step05_checks.sh` | 27/29. The source-detail contract failed on a rule-rejected link (item 9). The health check wrongly needed this month's Brave use above zero, after the monthly reset, and health showed no web reader success (item 10). All fixed | [log](checks-20261001T060323Z.log) |



## Step 05 acceptance checks

- [x] Crash/retry of the same page creates no duplicate source revision. Covered by UC-34 and UC-38 (replay). On the live data, "one record per source revision" holds for every stored record.
- [x] One provider outage lets other sources finish and visibly marks partial coverage (UC-38).
- [x] Thread context, missing publication dates and deleted or edited items behave as specified:
  - replies keep their top comment, and comments inherit their thread (D42; UC-37, UC-38);
  - unknown dates stay unknown, and stated dates come only from markup (D44);
  - deletion needs two "gone" results; edits become new revisions (UC-39);
  - live re-check results are in the table above.
- [x] A metadata-only search hit cannot become an eligible content claim. Covered by UC-38, and on the live data "no evidence comes from a metadata-only record" holds for all 350 evidence spans.
- [x] Each mandatory live connector has an actual authorised query result, separate from mocks. The Brave, web reader and YouTube runs for the five projects are listed above, with the evidence log ([live connectors](live-connectors-20260930T110436Z.log)). The registry marks them live with that log.
- [x] Relevant repository checks were actually run and their results recorded (above).
- [x] PROGRESS.md records changed paths, decisions, evidence, unresolved dependencies and the next action.
- [ ] The product owner approves items U–Y.

## Approvals (U–Y), for the product owner

| Item | Decision | Where |
|---|---|---|
| U | The web reader is plain HTTP plus Trafilatura, not Crawl4AI, whose stealth modes exist to get past bot protection. Script-rendered pages are counted as thin; Playwright stays optional and without stealth | D40 |
| V | YouTube comments are fetched only for videos matched to a project. A comment that names no project inherits its video's (or top comment's) match. If that match is undone, the comment goes back to review | D42 |
| W | Run rules and budgets: <ul><li>only the connectors a run planned;</li><li>coverage `partial` only when something may read next time;</li><li>Brave hits are discovery only;</li><li>redirects are stored where they land;</li><li>Brave 2 pages per query;</li><li>YouTube 4 searches per project and 3 comment pages per video;</li><li>40 web pages per run, 3 seconds per host;</li><li>A01 10 calls per run;</li><li>new connectors join existing configurations with their default</li></ul> | D43 |
| X | Re-checks and dates: <ul><li>a new job kind `check_availability` (contract amendment, operations 1.1.0);</li><li>two consecutive "gone" results mean deleted, and an edit becomes a new revision;</li><li>publication dates only from structured markup, with stored dates corrected and audited;</li><li>daily scheduling at Step 13, `make recheck` until then</li></ul> | D44 |
| Y | <ul><li>A robots.txt that refuses our crawler (401, 403 and the like) means nothing is fetched from that site; only 404 or 410 means there is no robots.txt. The 57 MagicBricks pages read before this fix were withdrawn and erased.</li><li>Withdrawal, deletion and expiry reach older revisions too (contract amendment, state machines 1.2.0).</li><li>A Brave hit found again under another title is the same record.</li></ul> | D45 |

D41 (the allow-list: developer, broker and news sites; not client-site.example) was accepted on 29 Sep 2026.

## Known limits (honest coverage)

- **Portals:**
  - 99acres and Housing.com refuse automated requests (403 and 406), and MagicBricks' robots.txt disallows project pages. They stay unread; D34's route needs a data agreement.
  - NoBroker, Houseiy and HomznSpace pages are read where robots.txt allows.
- **Web comments:** comments on generic web pages are kept inside the page text ("Comments on this page"). They are not split per author yet.
- **Brave hits:** hits are discovery only, so a hit whose page was refused or not read has no project match.
- **YouTube videos** are metadata only. What is said in them needs transcripts (Step 06).
- **Waiting for review:**
  - links in `needs_review` wait for the Step 09 console;
  - 3 alias proposals from A01 wait for a decision (D17).
- **Other platforms:** Reddit, X, Meta, Quora, LinkedIn and a listening provider have no credential (`access_pending`). Coverage says so, and nothing is inferred for them.
