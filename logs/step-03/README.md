# Step 03 test plan and logs

Step 03 builds the engineering foundation every later step runs on ([step spec](../../steps/03-foundation-and-mongodb.md)). It covers:

- the Docker Compose stack: MongoDB as a single-node replica set, plus the API, worker, scheduler and web app;
- repeatable database setup and seeding;
- our own sign-in with roles and CSRF;
- the durable job primitive;
- the Claude model gateway;
- the Next.js console shell and public page;
- GitHub Actions CI.

Run the commands from the repository root. You need Docker (Compose v2+), uv, pnpm, Node.js, Python 3.10+ and the `gh` CLI signed in. `.env` must hold `SEED_USER_PASSWORD`; yours already does. In zsh, run `setopt interactivecomments` once if you paste commands that contain `#` comments.

## Run everything

```bash
git pull
bash scripts/run_step03_checks.sh
bash scripts/run_step03_mutations.sh
```

The first script does the following:

- builds and starts the stack, and leaves it running;
- repeats setup and seeding;
- signs in through the web app exactly as a browser does;
- restarts the real worker in the middle of a job;
- runs every test suite, linter and type check;
- runs three negative checks and the hygiene checks.

It saves the output to `logs/step-03/checks-<UTC time>.log`. A good run ends with `ALL CHECKS OK` and exit code 0. Secret values are read from `.env` but never printed.

The second script disables twelve backend rules one at a time on a scratch copy. A good run ends with `ALL MUTANTS CAUGHT`. Your files are never changed.

## Try it yourself: web and API side by side

```bash
make up
make seed
open http://localhost:3000/console
```

1. You are sent to the sign-in page. Sign in as `deepesh.gupta@client-site.example` with the password I gave you (also in your `.env` as `SEED_USER_PASSWORD`).
2. The dashboard shows your name, the magenta "Fixture mode" banner and "5 projects in the catalogue".
3. Operations lists 11 connectors, all "access pending".
4. http://localhost:3000/projects/dlf-privana-sector-76-gurgaon shows the public page's empty state (no insights published yet; the page is `noindex`).
5. Sign out. Going back to http://localhost:3000/console sends you to sign-in again.

API checks in a second terminal:

```bash
curl -s http://localhost:8000/readyz
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:3000/v1/auth/me
make config
make smoke-model
docker compose ps
```

The expected results, in order:

- `readyz` returns `{"status":"ready","replica_set":"rs0"}`;
- `/v1/auth/me` returns `401` when signed out;
- `make config` lists credential names only;
- `make smoke-model` prints `skipped: no ANTHROPIC_API_KEY configured` until a key is added;
- `docker compose ps` shows mongodb, api, worker, scheduler and web running.

`make down` stops everything and keeps the database.

## Use cases

| ID | Use case | What it proves | Backend tests | End-to-end checks in the script |
|---|---|---|---|---|
| UC-17 | Sign-in, roles and CSRF | Wrong password, signed-out and wrong-role calls are refused. A tampered, expired or revoked session fails. Mutations need the CSRF token. Repeated failures are rate limited. Inactive users cannot sign in | 13 | Redirect to sign-in, 401, HttpOnly cookie, five roles, CSRF 403/204, old cookie 401, 429 |
| UC-18 | Durable jobs | Claims are exclusive and fenced. An expired lease is recovered. A stale worker cannot finish its successor's job. Retries wait, then stop. Cancel and pause-for-review work. Every status change is allowed by the state machine | 15 | Real worker stopped mid-job and restarted; stale token refused; one job per logical key |
| UC-19 | Database setup | Collections, contract-derived validators and indexes. Repeating setup changes nothing. A transaction commits and aborts on the replica set. A LangGraph checkpoint saves and resumes | 7 | Setup repeated with no changes; no duplicate indexes; validator refuses an unknown role (N2) |
| UC-20 | Seeding | The five projects get the Step 01 slugs and keep their IDs when seeded again. An invalid input file is refused. Only an argon2 hash is stored. The password changes only on an explicit reset | 10 | Projects and users seeded twice; the second run changes nothing |
| UC-21 | Claude gateway | The configured model is used with the contract schema. Refusal and truncation fail. There is one bounded repair and retries on transient errors. Configured model IDs are confirmed through the Models API. With no key it is `access_pending` and the smoke test prints `skipped` | 19 | `make smoke-model` (skipped: no key yet, I02) |
| UC-22 | Contract alignment | The backend API matches `routes.json`. Agent schemas bundle as in Step 02. Web types match the OpenAPI file | 4 | `check:api`; out-of-date web types are caught (N3) |
| UC-23 | Settings, logs and secrets | Live mode refuses to start without secrets. Errors never echo configured values. Logs are JSON with a request ID and redacted secrets. Only credential names are reported | 15 | Credential names only; live mode refuses (N1); secret values absent from commits, service logs and `logs/` |
| UC-24 | Stack on a fresh machine | Compose builds and starts everything, the replica set initialises itself and the API reports ready | — | All services healthy; rs0 primary; readyz. The CI Compose job runs this on a clean GitHub runner |
| UC-25 | Console and public page | Sign-in page, protected console, dashboard, operations, public empty state with `noindex`, safe post-login redirects | 13 web (Vitest) | eslint, TypeScript, build; the pages above render with the right content |

Total: 83 backend tests (pytest, against the Compose MongoDB) and 13 web tests. The Step 01 validator and the 127 Step 01–02 tests are rerun as regression.

## Negative checks (in the script)

| Check | What is tried | Expected failure message |
|---|---|---|
| N1 | Start the API in live mode with empty secrets | `live mode needs SESSION_SECRET, REVALIDATION_SECRET` |
| N2 | Insert a copy of the real user record with the role `superuser` (an unchanged copy is accepted first, so only the role differs) | `Document failed validation` (roles: value was not found in enum) |
| N3 | Change the OpenAPI file without regenerating the web types (on a temporary copy) | `Generated types are not up-to-date` |

## Mutation check (second script)

| Rule disabled | Test that must fail |
|---|---|
| Fencing token checked on completion | `test_expired_worker_cannot_complete_its_successors_job` |
| Expired leases returned to the queue | `test_claimed_job_survives_a_worker_restart` |
| Role check | `test_wrong_role_is_forbidden` |
| CSRF check on mutations | `test_mutation_without_csrf_token_is_rejected` |
| Session cookie signature | `test_tampered_cookie_is_rejected` |
| Session revocation and expiry | `test_logout_with_csrf_revokes_the_session` |
| Sign-in rate limit | `test_repeated_failures_are_rate_limited` |
| 12-character password minimum | `test_a_short_password_is_refused` |
| Model refusal handling | `test_refusal_is_a_failure_not_parsed` |
| One bounded repair | `test_second_invalid_output_fails_without_a_third_try` |
| Log redaction | `test_redaction_masks_known_secret_shapes_and_registered_values` |
| Settings errors hide input values | `test_a_failed_start_does_not_echo_configured_values` |

## Individual commands

```bash
make up
make seed
make test
make lint
make typecheck
make smoke-model
make config
make check-step03
make mutations-step03
make down
```

## Recorded results

| Date (UTC) | Commit | Run by | Command | Result | Log |
|---|---|---|---|---|---|
| 2026-09-28 08:02 | `54d3954` | GitHub Actions | CI: contracts, backend, web, Compose | All four jobs passed | [run 36394843164](https://github.com/deepeshgupta12/agentic_ai_review_model/actions/runs/36394843164) |
| 2026-09-28 08:37 | `38be1be` | Implementer | `bash scripts/run_step03_checks.sh` | ALL CHECKS OK, 45/45: 83 backend and 13 web tests; 127 regression tests; checker 13/13; N1–N3 as expected; hygiene OK. The labels were renumbered to match the test files afterwards; the checks are the same | [checks-20260928T083751Z.log](checks-20260928T083751Z.log) |
| 2026-09-28 08:43 | `38be1be` | Implementer | `bash scripts/run_step03_mutations.sh` | ALL MUTANTS CAUGHT: the unchanged copy passes 83/83; each of the 12 disabled rules is caught by its own test | [mutation-check-20260928T084324Z.log](mutation-check-20260928T084324Z.log) |
| 2026-09-28 | `38be1be`, `174d6ae` | GitHub Actions | CI: contracts, backend, web, Compose | All four jobs passed on both commits | [run ](https://github.com/deepeshgupta12/agentic_ai_review_model/actions/runs/), [run null](https://github.com/deepeshgupta12/agentic_ai_review_model/actions/runs/null) |
| 2026-09-28 08:58 | `174d6ae` | Implementer | `bash scripts/run_step03_checks.sh` (final script) | ALL CHECKS OK, 45/45, same results with the renumbered labels; user seeding now runs twice | [checks-20260928T085829Z.log](checks-20260928T085829Z.log) |

The first runs found four problems, all fixed before these results:

- N2 passed for the wrong reason: the copied user's ID broke the ID pattern, so even a valid copy was refused.
- Settings errors echoed part of the configured values.
- The mutation harness imported the wrong copy.
- The user-seeding check assumed the coordinator already existed.

No live integration was run. No Anthropic key is configured yet (I02), so the model smoke test reports `skipped`, as the step allows.

## Step 03 acceptance checks

- [x] A fresh machine installs and runs from documented commands, and the replica set initialises automatically (UC-24; README "Run it locally"; CI Compose job on a clean runner).
- [x] Database setup can be repeated without duplicate indexes, and project seeding is idempotent (UC-19, UC-20).
- [x] Unauthorised callers and wrong-role requests are rejected, and CSRF is enforced on mutations (UC-17; mutation check).
- [x] A claimed job survives a worker restart, and an expired worker cannot complete a successor's job (UC-18, including a real worker restart).
- [x] A transaction commit and abort succeed against the Compose replica set (UC-19, `test_database.py`).
- [x] The smoke command reports "skipped: no key". The real structured-output call and the model-ID check wait for the Anthropic key (I02); the returned model ID goes in PROGRESS.md when it runs.
- [x] No credential or raw source body appears in the repository or standard logs (UC-23; hygiene checks).
- [x] PROGRESS.md records changed paths, decisions, evidence, unresolved dependencies and the next action.
- [ ] Product owner approves items L–O below (D18 gate).

## Approvals needed (L–O)

| Item | Decision | Where |
|---|---|---|
| L | Version freeze: Python 3.13, Node 24, MongoDB 8.0, Next.js 16.3 / React 19.2, TypeScript 5.9, exact pins in the version matrix | DECISIONS D29 and "Version matrix (Step 03)" |
| M | Setup commands are backend CLI subcommands run through `make` (`make seed`, `make smoke-model`), not separate `scripts/seed_*.py` files | D30 |
| N | Session design: HttpOnly signed cookie, CSRF header on every change, 10 failed sign-ins per window, then 429; the web app calls the API on its own origin | D31 |
| O | shadcn/ui, TanStack, Zod and TipTap are added at Step 09 when the console screens need them, not installed unused now | D32 |
