# Step 07 test plan and logs

Step 07 builds the evidence layer: every finding can be traced to exact evidence, copies count once, evidence can be found by project, and a correction reaches everything that depends on it ([step spec](../../steps/07-evidence-and-retrieval.md), D50). It adds:

- one eligibility rule used everywhere;
- context windows and anchor checks;
- origin clusters, kept current by a scheduled job;
- filtered keyword retrieval with a derived search index;
- lineage collections and the "what depends on this?" lookup, wired into dependency invalidation;
- a labelled synthetic retrieval benchmark.

Embeddings are not part of the baseline (D50): they are a measured option. Their memory cost matters on the 4 GB Docker VM (I18).

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
