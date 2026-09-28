# Step 02 test plan and logs

Step 02 freezes the contracts every later step builds on ([step spec](../../steps/02-ux-architecture-and-contracts.md)): versioned schemas, the API with roles, state machines, user journeys, agent outputs, canonical hashing, the console and public-page screens, and the design direction. This page lists the use cases, the commands to check them, the recorded results and the approvals needed to close the step.

Run the commands from the repository root. They need Python 3.10+, Node.js (for the cross-language check) and, for the GitHub check, the `gh` CLI signed in. The script creates a local `.venv` with the pinned packages on first run.

## Run everything

```bash
git pull
bash scripts/run_step02_checks.sh
```

It prints every check and saves the output to `logs/step-02/checks-<UTC time>.log`. A good run ends with `ALL CHECKS OK` and exit code 0. Negative checks edit a temporary copy of the repository; your files are never changed.

## Use cases

| ID | Use case | Step 02 acceptance check it proves | Tests |
|---|---|---|---|
| UC-08 | One status vocabulary with complete state machines | Backend, web and agent schemas share one vocabulary; no state is unreachable or a dead end; models are never actors | 8 |
| UC-09 | API and journeys | Every mandatory journey has a state path and an actor allowed to make each call; approval and publication are separate roles; no request body carries actor identity | 11 |
| UC-10 | Fixtures | Fixtures cover multi-project video, unknown date, insufficient evidence and withdrawal; your real input file matches its schema; no fixture mentions your five projects | 5 |
| UC-11 | Canonical hashing and text anchors | One hash across Python and JavaScript; one changed character changes it; floats and non-normalised text are refused; Hindi and emoji offsets convert correctly | 8 |
| UC-12 | Approval and public read | An edited payload cannot keep an approval; the public page never reads a newer draft or a disabled revision | 7 |
| UC-13 | Agent outputs | Every model-backed agent's output fits Claude structured outputs; a model cannot report "failed" | 6 |
| UC-14 | Truth and publication rules in the schemas | Repetition does not verify a fact; source-policy rights form a chain (all 32 combinations tested); only people decide; serving fails closed | 5 |
| UC-15 | Docs and seed data | Generated docs are current; screens reference real operations; Step 01 data uses the same vocabulary | 3 |

Total: 53 new tests in [scripts/tests/test_contracts.py](../../scripts/tests/test_contracts.py), plus the 57 Step 01 tests (110 in all).

## What the checker covers

`.venv/bin/python scripts/check_contracts.py` runs 12 sections, each PASS or FAIL: schema files and references; status vocabulary and state machines; route table and OpenAPI; journeys; agent outputs; fixtures; canonical hashing; text anchors; approval and public-read rules; Step 01 seed alignment; docs; JavaScript cross-check.

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
# Contract checker: 12 sections, all PASS
.venv/bin/python scripts/check_contracts.py

# All 110 tests
.venv/bin/python -m unittest discover -s scripts/tests -v

# Independent JavaScript check of hashes and text offsets
node scripts/jcs_check.mjs

# Generated files are current
.venv/bin/python scripts/build_openapi.py --check
.venv/bin/python scripts/build_fixtures.py --check
```

## What to review

| Item | Where |
|---|---|
| Contract overview, conventions, how the ten baseline gaps were resolved | [contracts/v1/README.md](../../contracts/v1/README.md) |
| Screens, public page and design direction | [docs/09-screen-specifications.md](../../docs/09-screen-specifications.md) |
| Journeys and state machines, readable | [docs/10-journeys-and-states.md](../../docs/10-journeys-and-states.md) |
| API operations and roles | [contracts/v1/routes.json](../../contracts/v1/routes.json) |
| Decisions D22–D26 | [DECISIONS.md](../../DECISIONS.md) |

## Recorded results

| Date (UTC) | Commit | Command | Result | Log |
|---|---|---|---|---|
| 2026-09-28 05:14 | `57c8e3e` | `bash scripts/run_step02_checks.sh` | ALL CHECKS OK: Step 01 regression; 110/110 tests; checker 12/12; OpenAPI and fixtures current; JavaScript agrees; N1–N6 fail as expected; hygiene OK | [checks-20260928T051449Z.log](checks-20260928T051449Z.log) |
| 2026-09-28 05:15 | `57c8e3e` | Mutation check (six rules disabled one at a time on a scratch copy) | Each disabled rule is caught by the tests written for it. One first attempt disabled the float check in a way that still rejected floats through a fallback; the rerun that really accepts floats is caught | [mutation-check-20260928T051513Z.log](mutation-check-20260928T051513Z.log) |

No live integration was run: no credentials are configured, and Step 02 calls no external service.

## Step 02 acceptance checks

- [x] Every mandatory journey has a state path and API/actor mapping (UC-09; 17 journeys cover 22 required paths).
- [x] Schema fixtures cover multi-project video, unknown date, insufficient evidence and withdrawal (UC-10).
- [x] An edited payload cannot retain approval by contract; independent-source counts are not treated as truth (UC-12, UC-14).
- [x] FE, backend and agent schemas use the same status vocabulary and ID/revision conventions (UC-08; one source in `common.schema.json`, inline copies rejected).
- [x] Relevant repository checks were actually run and their results recorded (above).
- [x] PROGRESS.md records changed paths, decisions, evidence, unresolved dependencies and the next action.
- [ ] Product owner approves the items below (D18 gate). Step 02 is marked complete only after this.

## Approvals requested

| # | Item | Where | Proposed |
|---|---|---|---|
| F | Contracts v1 as the base for all code (D22) | [contracts/v1/README.md](../../contracts/v1/README.md) | Nine schema files, one definition per shape; the baseline schema kept only as history |
| G | Extended status lists | [docs/10](../../docs/10-journeys-and-states.md) | Workflow `cancelled`; content `changes_requested` and `rejected`; finding `superseded` |
| H | API surface and roles | [routes.json](../../contracts/v1/routes.json) | 47 operations. Moderators approve; only publishers publish, roll back or unpublish; researchers and moderators decide aliases; admins manage users and policies |
| I | Canonical hashing and anchors (D23, D24) | [contracts/v1/README.md](../../contracts/v1/README.md#canonical-hashing-d23) | RFC 8785 + SHA-256; whole numbers only in hashed content; code-point offsets with UTF-16 views |
| J | Design direction (D25, I15) | [docs/09](../../docs/09-screen-specifications.md#design-direction-proposed-i15--d25) | Calm, dense console; Inter/Noto Sans Devanagari/JetBrains Mono; one teal accent; advantages and considerations in neutral ink, never green/red; the public module labelled as a the client summary |
| K | Public page markers and revalidation | [docs/09](../../docs/09-screen-specifications.md#public-project-page--projectsslug) | `data-insights-*` markers; HMAC-signed `POST /api/revalidate`; `noindex` for the POC |

Deferred inputs, asked at the step that needs them: seeded users and roles (I09) at Step 03 is next.
