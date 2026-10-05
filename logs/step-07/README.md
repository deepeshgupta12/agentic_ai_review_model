# Step 07 test plan and logs

Step 07 builds the evidence layer: every finding can be traced to exact evidence, copies count once, evidence can be found by project, and a correction reaches everything that depends on it ([step spec](../../steps/07-evidence-and-retrieval.md), D50). It adds:

- one eligibility rule used everywhere;
- context windows and anchor checks;
- origin clusters, kept current by a scheduled job;
- filtered keyword retrieval with a derived search index;
- lineage collections and the "what depends on this?" lookup, wired into dependency invalidation;
- a labelled synthetic retrieval benchmark.

Embedding search (local `bge-m3`) was requested by the product owner on 5 Oct 2026 and is being added on top of the keyword baseline recorded here.

Run the commands from the repository root with the stack up (`make up`). In zsh, run `setopt interactivecomments` once if you paste commands that contain `#` comments.

## Run everything

```bash
git pull
make up
bash scripts/run_step07_checks.sh
bash scripts/run_step07_mutations.sh
```

The check script covers:

- the Steps 01–06 regression;
- the backend and web gates;
- the new collections and indexes, and that repeating setup changes nothing;
- the scheduled clustering job on the real evidence, then a stable repeat;
- context windows for older evidence, added once;
- the evidence rules on the real stored data (`verify-evidence`);
- retrieval on the real evidence of the five projects: only that project's eligible evidence, with latency;
- the retrieval benchmark (saved);
- the collection rules;
- hygiene.

It ends with `ALL CHECKS OK`. It makes no Claude call and runs no Whisper.

The mutation script disables 12 evidence rules one at a time; each must be caught by its own test.

## Try it yourself

```bash
make search PROJECT=conscient-parq-sector-80-gurgaon Q="possession"
make search PROJECT=m3m-antalya-hills-sector-79-gurgaon Q="पज़ेशन"
make verify-evidence
make eval-retrieval
```

- `search` lists that project's eligible evidence for the words, best first, with flags (for example `stale`). An empty query lists the newest evidence.
- `verify-evidence` re-derives every anchor from the stored source and checks the search index, clusters and lineage.
- `eval-retrieval` runs the labelled synthetic set in a scratch database that is dropped afterwards.

## Use cases

| ID | Use case | What it proves | Tests |
|---|---|---|---|
| UC-47 | Origin clusters | Normalisation keeps Hindi words and numbers whole. Three copies of one post count as one origin. A lightly edited copy and a copied paragraph join the origin; a short post with edits does not. Short identical comments stay separate opinions. Cluster IDs are stable and membership changes are versions. A scheduled job clusters new evidence within the hour | 6 |
| UC-48 | One eligibility rule | Stale is flagged; unavailable, review, another project's link, withdrawal and superseded revisions are not eligible. Identity work may use links in review. The retrieval filter admits exactly what the rule admits | 2 |
| UC-49 | Anchors and context | Context keeps whole sentences and words, in Hindi too. UTF-16 offsets for Hindi and emoji point at the same characters in a browser. Anchor checks catch an altered, moved or uncontained span. New evidence is stored with its context (text and speech). Older evidence gets its context once | 5 |
| UC-50 | Filtered retrieval | Only this project's words come back, never another project's. Withdrawn evidence leaves at once, its search copy at erasure, and a link in review is no support. An English query reaches Hindi speech through its kept translation. The benchmark is clean and reports its misses honestly | 4 |
| UC-51 | Lineage | Exact revisions are followed from source to content. A source correction reaches every draft and active revision, withdraws the approved one and reports the rest. The evidence checks pass on good data and catch broken lineage | 3 |

## Known limits

- **Keyword ranking only.** No stemming ("floods" does not match "flooding") and no cross-language matching without a stored translation. The benchmark shows both.
- **Search API.** Retrieval is a backend service and a command; a console route waits for Step 09.
- **Claims, findings and content** do not exist yet (Steps 08–11). Lineage is tested with records built from the contract fixtures.
- **Devanagari localities** ("सेक्टर 102") send a post's link to review (I19).

## Recorded results

| Date (UTC) | Commit | Run by | Command | Result | Log |
|---|---|---|---|---|---|
| 2026-10-05 | worktree | Implementer | backend suite, ruff, mypy, contracts, web gates | 287 tests passed (20 for Step 07); lint and types clean; contracts 13/13; web gates OK | (console) |
| 2026-10-05 10:03 | `a894ffc` | Implementer | `bash scripts/run_step07_checks.sh` | **ALL CHECKS OK, 20/20.** 287 backend tests. The scheduler queued clustering and the worker clustered 437 waiting spans: 363 sources, 3 joined origins (two syndicated article pairs, one set of three identical comments); a repeat changed nothing. Context added to 110 older spans once. verify-evidence 8/8. Retrieval on the five projects' real evidence: 35 searches, p50 18 ms, p95 270 ms, none from another project or ineligible. Benchmark recall@10 0.9: same language 1.0 (17 queries), cross-language 0.5 (2), other word form 0.0 (1); no wrong-project, withdrawn or anchor errors; p50 9 ms | [log](checks-20261005T100321Z.log) |
| 2026-10-05 10:20 | `a894ffc` | Implementer | `verify-evidence` again, after the searches filled the index | 8/8; the search-index rule looked at 437 entries, 0 broken (in the check run it ran before any search and saw 0) | (console) |
| 2026-10-05 10:21 | `a894ffc` | Implementer | `bash scripts/run_step07_mutations.sh` | **ALL MUTANTS CAUGHT, 12/12** | [log](mutation-check-20261005T102125Z.log) |

The keyword baseline missed exactly what keywords cannot match: "flooding rains" for "floods after rain", and English queries for two Hindi posts without a stored translation. These are the cases embedding search is meant to close.
