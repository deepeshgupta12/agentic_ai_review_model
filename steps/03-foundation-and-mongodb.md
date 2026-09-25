# Step 03: Engineering foundation and MongoDB setup

**Release:** 1.0, complete five-project POC. **Initial status:** not started.

Create the reproducible monorepo foundation: Docker Compose with a single-node MongoDB replica set, the FastAPI API/worker/scheduler entry points, the Next.js app shell, own authentication, the job primitive, the Claude API gateway smoke test, and GitHub Actions CI. Establish commands that subsequent steps can actually run.

## Prerequisites

[Step 01](01-requirements-and-access.md), [Step 02](02-ux-architecture-and-contracts.md)

Read [MASTER.md](../MASTER.md), the relevant entries in [DECISIONS.md](../DECISIONS.md), and these specifications:

- [Architecture and stack](../docs/01-architecture-and-stack.md)
- [Database and contracts](../docs/02-database-and-contracts.md)
- [API and console contracts](../docs/03-api-and-cms-contracts.md)
- [Workflow and publication](../docs/05-workflow-and-publication.md)

## Original requirements covered (revised)

3.1 Create the repository layout and pin compatible language/library versions.

3.2 Configure the API, worker, scheduler and web app to run from Docker Compose with `.env`-based secrets.

3.3 Create the MongoDB replica set, AI collections, required indexes, validators, job records and checkpoint storage.

3.4 Implement own authentication, roles, seeded users, audit events.

3.5 Build GitHub Actions CI for checks, schema compatibility, container build and versioned database setup scripts.

3.6 Configure telemetry, trace redaction, budgets and a baseline operations view.

Deliverables: reproducible local environment, working authentication, MongoDB setup, model-gateway smoke test and CI.

## Detailed implementation

### 03.1 Initialise the repository

Create `backend/`, `web/`, `scripts/`, `evals/`, `prompts/`, `.github/workflows/`, `docker-compose.yml`, `.env.example`, `.gitignore` (ignore `.env`, media caches, model weights). Preserve the handoff Markdown at the root.

### 03.2 Resolve compatible versions

Check current official documentation and pin: Python runtime, FastAPI, Pydantic, PyMongo, LangGraph and its MongoDB checkpointer, Anthropic Python SDK, faster-whisper, sentence-transformers (if adopted), Next.js, TypeScript, Tailwind, shadcn/ui, TanStack, Zod, TipTap, MongoDB server image. Record the matrix in DECISIONS.md. Query the Models API with the configured key to confirm the D10 model IDs exist for this account.

### 03.3 Docker Compose and entry points

Services: `mongodb` (started with `--replSet rs0` and a one-shot init that runs `rs.initiate()`), `api`, `worker`, `scheduler`, `web`. Provide API health/readiness, validated settings (fail fast on missing required values in live mode), graceful shutdown and explicit fixture/live modes. Document `make`/`just`/npm scripts for: up, down, seed, test, lint, typecheck, build.

### 03.4 Set up MongoDB safely

Create AI collections, validators (MongoDB JSON-schema subset) and indexes through repeatable, idempotent scripts. Create the `projects` catalogue collection and `scripts/seed_projects.py` that loads the five-project input file, generates IDs/slugs and is safe to re-run. Test the LangGraph checkpointer against the replica set and a transaction commit/abort.

### 03.5 Implement authentication and roles

`users` collection, `scripts/seed_users.py`, login/logout/me endpoints, signed HTTP-only session cookie, CSRF token on mutations, role dependencies for routes, denial tests and safe audit events. Fixture mode uses a seeded fixture user, never a bypass.

### 03.6 Build the job primitive

Implement atomic claim, heartbeat, fencing token, expiry recovery, retry scheduling and cancellation. Persist unique logical keys and checkpoint references. Subsequent collectors/agents use this primitive.

### 03.7 Model gateway smoke test

Implement `backend/app/agents/gateway.py` around the Anthropic SDK: role-based model selection from config, structured output via JSON-schema output format with a Pydantic model, usage/cost recording, refusal/incomplete handling, one bounded repair, retry with backoff on transport/rate-limit errors. Provide a `scripts/smoke_model.py` that performs one real structured-output call and records the returned model ID. Skip (not fail) in CI when no key is present, and say so in the output.

### 03.8 Web app shell and CI

Scaffold the Next.js app with the console layout, login page, protected route group, generated API client from OpenAPI, and the empty public page route. GitHub Actions: backend lint/type/test, web lint/type/test/build, schema fixture check, Docker build. No deployment jobs.

### 03.9 Observability

Correlation IDs, structured JSON logs, content/secret redaction, per-run budget/usage records, and a minimal operations endpoint the console can read.

## Required deliverables

- `docker compose up` brings up MongoDB replica set, API, worker, scheduler and web from documented commands on a fresh machine.
- Pinned dependency manifests and lockfiles, `.env.example`, repeatable DB setup and seed scripts.
- Working login/roles, job/checkpoint persistence, model-gateway smoke script and green CI.

## Acceptance checks

- [ ] A fresh machine installs and runs from documented commands; the replica set initialises automatically.
- [ ] Database setup can be repeated without duplicate indexes; project seeding is idempotent.
- [ ] Unauthorised callers and wrong-role requests are rejected; CSRF is enforced on mutations.
- [ ] A claimed job survives worker restart; an expired worker cannot complete a successor's job.
- [ ] A transaction commit and abort succeed against the Compose replica set.
- [ ] `scripts/smoke_model.py` completes one real structured-output call when a key is configured (recorded model ID in PROGRESS.md), or reports "skipped: no key".
- [ ] No credential or raw source body appears in the repository or standard logs.
- [ ] [PROGRESS.md](../PROGRESS.md) records changed paths, decisions, evidence, unresolved dependencies and the next action.

## Missing access or information

Without an Anthropic key the gateway is built and unit-tested with a recorded fake client; the live smoke test stays blocked. Everything else in this step has no external dependency.

## Coding prompt

```text
Implement Step 03 from steps/03-foundation-and-mongodb.md in this repository.
Read MASTER.md, PROGRESS.md, this step and its linked specifications. Create the monorepo
foundation: Docker Compose with a single-node MongoDB replica set, FastAPI API/worker/
scheduler entry points, own authentication with seeded users and roles, the durable job
primitive, the Claude API gateway with a real structured-output smoke script, the Next.js
console shell and GitHub Actions CI. Pin versions after checking official docs and record
them in DECISIONS.md. Do not invent passing test results. Run the checks, resolve failures,
and update PROGRESS.md with changed paths, actual results, decisions, blockers and the next
executable action.
```

## Completion and handoff

Mark this step complete only when its deliverables and applicable acceptance checks have evidence. Next: [Step 04: Project catalogue and identity resolution](04-project-identity.md)
