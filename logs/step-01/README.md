# Step 01 test plan and logs

Step 01 registers the five projects, the source-access plan, the initial source policies, the operating defaults and the acceptance definitions ([step spec](../../steps/01-requirements-and-access.md)). This page lists the use cases, the commands to check them, the recorded results and the approvals needed to close the step.

Run the commands from the repository root. They need Python 3.10+ and nothing else; the GitHub check also needs the `gh` CLI signed in.

## Run everything

```bash
git pull
bash scripts/run_step01_checks.sh
```

It prints every check and saves the output to `logs/step-01/checks-<UTC time>.log`. A good run ends with `ALL CHECKS OK` and exit code 0. The real input files are never changed; negative checks edit temporary copies.

## Use cases

| ID | Use case | Step 01 acceptance check it proves | Tests |
|---|---|---|---|
| UC-01 | Register the five projects | Every project row validates, or the failing project and field are named; no extra projects | 13 |
| UC-02 | Slugs and search forms | D19 convention: slugs, search forms (Hindi kept intact), full and short RERA IDs compare equal | 9 |
| UC-03 | Connector matrix | Every connector is `access_pending` with a credential location and go-live demonstration; `live` needs recorded proof | 10 |
| UC-04 | Source policies | Policies exist for every connector family; rights are consistent; sources without an agreement stay blocked | 8 |
| UC-05 | Operating defaults | Defaults stay proposed until a named person accepts them; open items have no value | 6 |
| UC-06 | Decision register and secrets | DECISIONS.md registry matches the JSON; no secret in seed data; `.env` is ignored | 6 |
| UC-07 | Command line | Exit code 0 on the real files, 1 on bad input; JSON output | 4 |

Total: 56 tests in [scripts/tests/test_validate_inputs.py](../../scripts/tests/test_validate_inputs.py).

## Negative checks (in the script)

| Check | Change made to a temporary copy | Expected result |
|---|---|---|
| N1 | DLF Privana's locality set to `<Locality>` | FAIL naming `projects[0] (DLF Privana)` and `locality` |
| N2 | Brave marked `live` without a recorded demonstration | FAIL: `'live' requires last_verified ... and verification_ref`, plus registry drift |
| N3 | AI processing switched on for Reddit | FAIL: `AI processing allowed without collection` |
| N4 | A fake API key pasted into seed data | FAIL: `contains a secret-like value` |
| N5 | DLF Privana pasted over project 5 | FAIL: duplicate slug, probable duplicate project |

## Individual commands

```bash
# All 56 use-case tests
python3 -m unittest discover -s scripts/tests -v

# Validator on the real files, with the registration preview
python3 scripts/validate_inputs.py

# Same result as JSON
python3 scripts/validate_inputs.py --json

# One negative check by hand: must print "Result: FAIL" and exit=1
sed 's/"Sector 76"/"<Locality>"/' contracts/five-project-input-template.json > /tmp/step01-bad.json
python3 scripts/validate_inputs.py --projects /tmp/step01-bad.json; echo "exit=$?"
```

## Expected registration preview

| # | Project | Slug | RERA registrations |
|---|---|---|---|
| 1 | DLF Privana | `dlf-privana-sector-76-gurgaon` | 3 (South, West, North) |
| 2 | Conscient Parq | `conscient-parq-sector-80-gurgaon` | 1 |
| 3 | Sobha Crescent | `sobha-crescent-sector-63a-gurgaon` | 1 |
| 4 | M3M Forestia West | `m3m-forestia-west-manesar-sector-9-gurgaon` | 1 |
| 5 | M3M Antalya Hills | `m3m-antalya-hills-sector-79-gurgaon` | 4 |

One warning is expected: the search name `parq` is a single word, so Step 04 uses it only together with the developer or locality (D17).

## Recorded results

| Date (UTC) | Commit | Command | Result | Log |
|---|---|---|---|---|
| 2026-09-25 06:21 | `f0932cb` | `bash scripts/run_step01_checks.sh` | ALL CHECKS OK: 56/56 tests; validator PASS with the expected warning; N1–N5 fail as expected; hygiene OK | [checks-20260925T062111Z.log](checks-20260925T062111Z.log) |
| 2026-09-25 06:21 | `f0932cb` | Mutation check (six validator rules disabled one at a time on a scratch copy) | Each disabled rule is caught by the tests written for it | [mutation-check-20260925T062128Z.log](mutation-check-20260925T062128Z.log) |

No live integration was run: no credentials are configured, and Step 01 does not call any source.

## Step 01 acceptance checks

- [x] Every project row validates or is explicitly unresolved with the missing field named (UC-01, N1).
- [x] Every connector has a row with status `access_pending`, credential location and demonstration criteria (UC-03, UC-06).
- [x] Initial source policies exist as seed data for every platform family in the matrix (UC-04).
- [x] No extra project inputs or separate product release introduced (UC-01; single release in the acceptance definitions).
- [x] PROGRESS.md records changed paths, decisions, evidence, unresolved dependencies and the next action.
- [ ] Product owner approves the proposed items below (D18 gate). Step 01 is marked complete only after this.

## Approvals requested

| # | Item | Where | Proposed |
|---|---|---|---|
| A | Mandatory sources for the demo (I04) | [seed/connectors.json](../../seed/connectors.json), [DECISIONS.md](../../DECISIONS.md#connector-registry) | Anthropic, Brave, YouTube, and one of Firecrawl/Playwright; the rest optional |
| B | Initial source policies (I06) | [seed/source_policies.json](../../seed/source_policies.json) | Web pages: collect and analyse, paraphrase with link, no quotes, 90 days. YouTube: API only, 30 days. HARERA: registry facts may be quoted, 365 days. Reddit, X, Meta, Quora, LinkedIn, listening provider and video transcripts: blocked until access or a decision exists |
| C | Operating defaults (I07, I08, I10, I14) | [seed/operating_defaults.json](../../seed/operating_defaults.json) | English/Hindi/Hinglish in, en-IN out; daily + manual refresh; 90-day lookback; IST display; opinion "recurring" at 3 independent sources; stale warning at 30 days; withdrawal removed from the page within 60 minutes; public page `noindex` |
| D | Slug and ID convention (D19) | [DECISIONS.md](../../DECISIONS.md) | `name-locality-city`, generated once and kept stable |
| E | Release acceptance definitions (I11) | [DECISIONS.md](../../DECISIONS.md#release-acceptance-definitions-proposed-step-01) | Targets from docs/07 |

Still open, and needed later rather than for Step 02: transcript route (I05, Step 06), seeded users (I09, Step 03), correction owner (I10), demo machine (I12, Step 13), moderator capacity (I11), alternate names (I01).
