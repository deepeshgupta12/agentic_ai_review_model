# Step 02 test plan and logs

Step 02 freezes the contracts every later step builds on ([step spec](../../steps/02-ux-architecture-and-contracts.md)): versioned schemas, the API with roles, state machines, user journeys, agent outputs, canonical hashing, the console and public-page screens and the design direction. After approval it also gained two changes the product owner asked for: construction-status consistency (D27) and first-person reviews from real sources (D28).

Run the commands from the repository root. They need Python 3.10+, Node.js (for the cross-language check) and, for the GitHub check, the `gh` CLI signed in. The script creates a local `.venv` with the pinned packages on first run. In zsh, run `setopt interactivecomments` once if you paste commands that contain `#` comments.

## Run everything

```bash
git pull
bash scripts/run_step02_checks.sh
```

It prints every check and saves the output to `logs/step-02/checks-<UTC time>.log`. A good run ends with `ALL CHECKS OK` and exit code 0. Negative checks edit a temporary copy of the repository; your files are never changed.

## Use cases

| ID | Use case | What it proves | Tests |
|---|---|---|---|
| UC-08 | One status vocabulary with complete state machines | Backend, web and agent schemas share one vocabulary; no state is unreachable or a dead end; models are never actors | 8 |
| UC-09 | API and journeys | Every mandatory journey has a state path and an actor allowed to make each call; approval and publication are separate roles; no request body carries actor identity | 11 |
| UC-10 | Fixtures | Fixtures cover multi-project video, unknown date, insufficient evidence and withdrawal; the real input file matches its schema; no fixture mentions the five registered projects | 5 |
| UC-11 | Canonical hashing and text anchors | One hash across Python and JavaScript; one changed character changes it; floats and non-normalised text refused; Hindi and emoji offsets convert | 8 |
| UC-12 | Approval and public read | An edited payload cannot keep an approval; the public page never reads a newer draft or a disabled revision | 7 |
| UC-13 | Agent outputs | Every model-backed agent's output (A01–A11) fits Claude structured outputs; a model cannot report "failed" | 6 |
| UC-14 | Truth and publication rules in the schemas | Repetition does not verify a fact; source-policy rights form a chain (all 32 combinations); only people decide; serving fails closed | 5 |
| UC-15 | Docs and seed data | Generated docs are current; screens reference real operations; Step 01 data uses the same vocabulary | 3 |
| UC-16 | Construction status and first-person reviews (D27, D28) | "Lived here" before possession is flagged; the post's date decides the status; page wording follows status; a review keeps its author's words (no changed or added words, no dashes), comes from one source, cannot be approved while flagged, and is credited without a public link | 15 |

Total: 68 tests in [scripts/tests/test_contracts.py](../../scripts/tests/test_contracts.py), plus 59 Step 01 tests (two added: export status labels must map to a construction status) — 127 in all.

## What the checker covers

`.venv/bin/python scripts/check_contracts.py` runs 13 sections, each PASS or FAIL: schema files and references; status vocabulary and state machines; route table and OpenAPI; journeys; agent outputs; fixtures; canonical hashing; text anchors; approval and public-read rules; construction status and source reviews; Step 01 seed alignment; docs; JavaScript cross-check.

## Negative checks (in the script)

| Check | Change made to a temporary copy | Expected failure message |
|---|---|---|
| N1 | Journey J08: an analyst publishes | `may not call publish` |
| N2 | The approved payload's heading edited without a new hash | `payload_sha256 does not match the payload` |
| N3 | `minLength` added to an agent output schema | `keyword 'minLength' is not supported` |
| N4 | The only route to `rolled_back` removed | `'rolled_back' is unreachable` |
| N5 | A route edited without regenerating OpenAPI | `openapi.json is out of date` |
| N6 | A Python hash corrupted in the shared vectors | JavaScript reports `sha256 differs from Python` |

## Individual commands

```bash
.venv/bin/python scripts/check_contracts.py
.venv/bin/python -m unittest discover -s scripts/tests -v
node scripts/jcs_check.mjs
.venv/bin/python scripts/build_openapi.py --check
.venv/bin/python scripts/build_fixtures.py --check
python3 scripts/validate_inputs.py
```

The last command now shows each project's construction status mapped from its export label.

## Recorded results

| Date (UTC) | Commit | Run by | Command | Result | Log |
|---|---|---|---|---|---|
| 2026-09-28 05:14 | `57c8e3e` | Implementer | `bash scripts/run_step02_checks.sh` | ALL CHECKS OK: 110/110 tests; checker 12/12; N1–N6 as expected | [checks-20260928T051449Z.log](checks-20260928T051449Z.log) |
| 2026-09-28 05:15 | `57c8e3e` | Implementer | Mutation check, six rules | Each disabled rule caught; an equivalent float mutant noted and rerun | [mutation-check-20260928T051513Z.log](mutation-check-20260928T051513Z.log) |
| 2026-09-28 06:00 | `bec6225` | Product owner, own machine | `bash scripts/run_step02_checks.sh` | ALL CHECKS OK; independent confirmation before approval | [checks-20260928T060001Z.log](checks-20260928T060001Z.log) |
| 2026-09-28 06:43 | `fb6cf66` | Implementer | Mutation check, six D27/D28 rules | Each disabled rule caught by its tests | [mutation-check-20260928T064355Z.log](mutation-check-20260928T064355Z.log) |
| 2026-09-28 06:44 | `88685f6` | Implementer | `bash scripts/run_step02_checks.sh` after D27/D28 | ALL CHECKS OK: 59 Step 01 tests; 127/127 tests; checker 13/13; N1–N6 as expected; hygiene OK | [checks-20260928T064420Z.log](checks-20260928T064420Z.log) |

No live integration was run: no credentials are configured, and Step 02 calls no external service.

## Step 02 acceptance checks

- [x] Every mandatory journey has a state path and API/actor mapping (UC-09; 19 journeys cover 24 required paths).
- [x] Schema fixtures cover multi-project video, unknown date, insufficient evidence and withdrawal (UC-10).
- [x] An edited payload cannot retain approval by contract; independent-source counts are not treated as truth (UC-12, UC-14).
- [x] FE, backend and agent schemas use the same status vocabulary and ID/revision conventions (UC-08).
- [x] Relevant repository checks were actually run and their results recorded (above).
- [x] PROGRESS.md records changed paths, decisions, evidence, unresolved dependencies and the next action.
- [x] Product owner approved items F–K on 28 Sep 2026 (D18 gate).

## Approvals (granted 28 Sep 2026)

| # | Item | Approved |
|---|---|---|
| F | Contracts v1 as the base for all code (D22) | Nine schema files, one definition per shape; baseline schema kept as history |
| G | Extended status lists | Workflow `cancelled`; content `changes_requested` and `rejected`; finding `superseded` |
| H | API surface and roles | Moderators approve; only publishers publish, roll back or unpublish; researchers and moderators decide aliases; admins manage users and policies |
| I | Canonical hashing and anchors (D23, D24) | RFC 8785 + SHA-256; whole numbers only in hashed content; code-point offsets with UTF-16 views |
| J | Design direction (D25, I15) | Calm, dense console; one teal accent; advantages and considerations in neutral ink; public module labelled as a the client summary |
| K | Public page markers and revalidation | `data-insights-*` markers; HMAC-signed revalidation; `noindex` for the POC |

## Added after approval, at the product owner's request

**D27 Construction-status consistency.** Status is kept per project and per phase with its source and date. A post or review claiming first-hand living before possession, or in a partly ready project with no phase named, is flagged, kept out of content and sent to a moderator; the post's date decides which status applies. the client's own page text cannot say "residents" before possession.

**D28 First-person reviews from real sources.** Agreed conditions: one review is one real post, comment or video by one person; the author's words, cleaned of dashes or translated from Hinglish without changing meaning; a credit line naming who, platform and date (no public link, per the product owner); moderator approval of each; the D27 status check applies. Video included: YouTube comments now, spoken reviews once a transcript route exists (I05). New agent A11 Review curator; web and YouTube policies at version 2 with quotation allowed.

Deferred inputs, asked at the step that needs them: seeded users and roles (I09) now, for Step 03; construction status per phase for DLF Privana and M3M Antalya Hills (I16) at Step 04.
