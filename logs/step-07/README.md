# Step 07 test plan and logs

Step 07 builds the evidence layer: every finding can be traced to exact evidence, copies count once, evidence can be found by project, and a correction reaches everything that depends on it ([step spec](../../steps/07-evidence-and-retrieval.md), D50). It adds:

- one eligibility rule used everywhere;
- context windows and anchor checks;
- origin clusters, kept current by a scheduled job;
- filtered retrieval with a derived search index: keyword, vector (local bge-m3) and hybrid ranking;
- lineage collections and the "what depends on this?" lookup, wired into dependency invalidation;
- a labelled synthetic retrieval benchmark.

Embedding search was requested by the product owner on 5 Oct 2026 and is built on top of the keyword baseline (D51). The `embedder` service runs bge-m3 as int8 ONNX, pinned and hash-checked, capped at 1.5 GB.

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
- the embedder: pinned model loaded, memory cap, kill priority and restart policy, and a Hindi–English similarity check;
- the scheduled job that gives every real evidence span its vector;
- the evidence rules on the real stored data (`verify-evidence`);
- hybrid retrieval on the real evidence of the five projects: only that project's eligible evidence, with latency;
- the retrieval benchmark for keyword, vector and hybrid ranking (saved);
- the collection rules;
- hygiene.

It ends with `ALL CHECKS OK`. It makes no Claude call and runs no Whisper. The embedder's first start downloads the pinned model (568 MB) into a volume.

The mutation script disables 17 evidence rules one at a time (12 for the evidence layer and 5 for embedding search); each must be caught by its own test.

## Try it yourself

```bash
make search PROJECT=conscient-parq-sector-80-gurgaon Q="when will I get possession"
make search PROJECT=m3m-antalya-hills-sector-79-gurgaon Q="पज़ेशन"
make verify-evidence
make eval-retrieval
```

- `search` lists that project's eligible evidence, best first, by hybrid ranking. Each result shows its keyword score, its cosine similarity and any flags (for example `stale`). `--mode keyword` or `--mode vector` (through `python -m app.cli search-evidence`) ranks one way only. An empty query lists the newest evidence.
- `verify-evidence` re-derives every anchor from the stored source and checks the search index, clusters and lineage.
- `eval-retrieval` runs the labelled synthetic set in a scratch database that is dropped afterwards, scoring keyword, vector and hybrid ranking.

## Use cases

| ID | Use case | What it proves | Tests |
|---|---|---|---|
| UC-47 | Origin clusters | Normalisation keeps Hindi words and numbers whole. Three copies of one post count as one origin. A lightly edited copy and a copied paragraph join the origin; a short post with edits does not. Short identical comments stay separate opinions. Cluster IDs are stable and membership changes are versions. A scheduled job clusters new evidence within the hour | 6 |
| UC-48 | One eligibility rule | Stale is flagged; unavailable, review, another project's link, withdrawal and superseded revisions are not eligible. Identity work may use links in review. The retrieval filter admits exactly what the rule admits | 2 |
| UC-49 | Anchors and context | Context keeps whole sentences and words, in Hindi too. UTF-16 offsets for Hindi and emoji point at the same characters in a browser. Anchor checks catch an altered, moved or uncontained span. New evidence is stored with its context (text and speech). Older evidence gets its context once | 5 |
| UC-50 | Filtered retrieval | Only this project's words come back, never another project's. Withdrawn evidence leaves at once, its search copy at erasure, and a link in review is no support. An English query reaches Hindi speech through its kept translation. The benchmark is clean and reports its misses honestly | 4 |
| UC-52 | Embedding search (D51) | Vectors find what keywords miss (other word forms, English for Hindi), and hybrid keeps both. Vectors never cross projects. Without the embedder, search falls back to keywords and says so. A scheduled job makes the vectors, and remakes them for a new model. An entry whose evidence lost its words leaves the index. A model file that does not match its pinned hash is refused | 4 |
| UC-51 | Lineage | Exact revisions are followed from source to content. A source correction reaches every draft and active revision, withdraws the approved one and reports the rest. The evidence checks pass on good data and catch broken lineage | 3 |

## Known limits

- **Keyword ranking alone** has no stemming and no cross-language matching without a stored translation; hybrid ranking with bge-m3 closes both on the benchmark. Vector similarity is computed over at most 2,000 entries per project, which is plenty for this POC.
- **Memory.** The embedder uses about 0.75 GB. Docker's 4 GB VM is tight; the product owner chose 6 GB (I18). This Mac has 8.6 GB in total.
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
| 2026-10-06 04:38 | `447deb0` | Implementer | `bash scripts/run_step07_checks.sh` (with embeddings) | 17/22. The embedder image did not build: uv's 60-second bytecode limit timed out on a numpy file while four images built at once on the 4 GB VM. Compose kept the old containers, so the checks after the build ran against `a894ffc` code and do not count. Fixed with `UV_COMPILE_BYTECODE_TIMEOUT=600` in all three images; the embedder image then built and imported on its own | [log](checks-20261006T043835Z.log) |
| 2026-10-06 09:43 | `4764a1e` | Implementer | `bash scripts/run_step07_checks.sh` | 7/22. All images built and the embedder downloaded, verified and loaded the model (healthy). But while four images built after the test suite on the 4 GB VM, MongoDB's `mongosh` health probe kept exceeding its 5-second timeout, so it was marked unhealthy while serving normally, and Compose did not start the services that depend on it. Every later check failed for that reason alone. The stack was brought back up unchanged (MongoDB never restarted, no data touched). Fixed: the probe timeout is 20 s, and the script builds first, waits for MongoDB to be healthy, then starts the stack | [log](checks-20261006T094342Z.log) |
| 2026-10-07 10:16 | `9ebfcc9` | Implementer | `bash scripts/run_step07_checks.sh` | 23/24. The stack built and started cleanly. Embeddings: all 437 real evidence spans got vectors. Hybrid search on real data: 35 searches, p50 52 ms, p95 182 ms, none from another project or ineligible. Benchmark recall@10: keyword 0.839, vector 1.0, hybrid 1.0; MRR 0.861, 0.982, 0.954; no errors. **Failed:** the embedding check counted 29 failed jobs from earlier that day (`ConnectError` while the stack ran after the second run), not from this run. Found while investigating: the embedder had hit its 1.5 GB cap 477 times and held 490 MB in swap, because batches of 8 long texts did not fit. One 4,000-character text took 16 s (1.2 s natively), and batches exceeded the 120 s timeout. Fixed: one text per request, no swap for the embedder, a 15 s query timeout falling back to keywords, embedding queued only when the embedder is ready, error causes kept, and the check counts only its own run's jobs | [log](checks-20261007T101621Z.log) |
| 2026-10-08 10:14 | `f04c4a1` | Implementer | `bash scripts/run_step07_checks.sh` (the product owner had stopped their other Docker stack) | **ALL CHECKS OK, 24/24.** 291 backend tests. Embedder: pinned model ready, 1.07 GB of its 1.5 GB cap, swap 0; one 4,000-character text 7.4 s (16 s before, when it swapped), one query 1.8 s. All 437 real spans already had vectors from run 3, so the embedding job had nothing to do in this run. Clustering stable (3 joined origins). verify-evidence 8/8 on 447 spans and 437 search entries. Hybrid search on the five projects' real evidence: 35 searches, p50 228 ms, p95 613 ms, none from another project or ineligible. Benchmark recall@10 / MRR@10: keyword 0.839 / 0.861, vector 1.0 / 0.982, hybrid 1.0 / 0.954; no wrong-project, withdrawn or anchor errors | [log](checks-20261008T101429Z.log) |
| 2026-10-08 10:31 | `f04c4a1` | Implementer | `bash scripts/run_step07_mutations.sh` | **ALL MUTANTS CAUGHT, 17/17** (12 evidence layer, 5 embedding search) | [log](mutation-check-20261008T103136Z.log) |
| 2026-10-09 04:58 | `60bf593` | GitHub Actions | CI, including the embedder (model downloaded at the pinned commit, a 1,024-dimension vector returned) | All four jobs passed | `gh run view 37886392860` |
| 2026-10-09 05:17 | `ed8f1e0` | Implementer | backend suite, then `bash scripts/run_step07_mutations.sh` after D52 (Whisper and bge-m3 take turns) | 292 backend tests passed; **ALL MUTANTS CAUGHT, 21/21** (4 new for D52) | [log](mutation-check-20261009T051709Z.log) |

The keyword baseline missed exactly what keywords cannot match: "flooding rains" for "floods after rain", and English queries for two Hindi posts without a stored translation. These are the cases embedding search is meant to close.

## Approvals

| Item | Decision | Where |
|---|---|---|
| Step 07 | **Approved 9 Oct 2026**: the evidence layer (D50) and embedding search with hybrid ranking as the default (D51) | D50, D51 |
| I19 | Devanagari localities: fixed at Step 08 with the identity evaluation re-run (agreed 9 Oct 2026) | I19 |
| I18 | Docker stays at 4 GB, the product owner's limit (9 Oct 2026). Follow-up: Whisper and bge-m3 take turns (D52), tested and mutation-checked | I18, D52 |
