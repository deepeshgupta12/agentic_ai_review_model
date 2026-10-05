# Implementation progress and session handoff

**Initial status:** handoff 1.1 delivered; no product code has been implemented or validated. All steps start `not_started`. Update this file in the repository as work proceeds.

## Work ledger

| Step | Work package | Status | Changed paths / commit | Validation evidence |
|---|---|---|---|---|
| 01 | [Requirements, source access and acceptance definition](steps/01-requirements-and-access.md) | complete (approved 25 Sep 2026) | `2b6476c`, `f0932cb`, `90a8c8b`: `seed/`, `scripts/validate_inputs.py`, `scripts/tests/`, `scripts/run_step01_checks.sh`, `evals/step-01-evaluation-brief.md`, `DECISIONS.md` | [logs/step-01](logs/step-01/README.md): all checks OK at `90a8c8b` (57/57 tests, N1–N5 fail as expected); mutation check OK at `f0932cb` |
| 02 | [UX, architecture and contracts](steps/02-ux-architecture-and-contracts.md) | complete (approved 28 Sep 2026) | `57c8e3e`, `fb6cf66`, `88685f6`: `contracts/v1/`, `docs/09`, `docs/10`, `scripts/contract_tools.py`, `scripts/check_contracts.py`, `scripts/build_openapi.py`, `scripts/build_fixtures.py`, `scripts/jcs_check.mjs`, `scripts/tests/test_contracts.py`, `scripts/run_step02_checks.sh`, `seed/`, `DECISIONS.md` | [logs/step-02](logs/step-02/README.md): all checks OK at `88685f6` (127/127 tests, checker 13/13, N1–N6 as expected); product owner's own run OK at `bec6225`; mutation checks OK |
| 03 | [Engineering foundation and MongoDB setup](steps/03-foundation-and-mongodb.md) | complete (approved 28 Sep 2026) | `0847027`, `54d3954`, `38be1be`, `174d6ae`: `backend/`, `web/`, `docker-compose.yml`, `.env.example`, `Makefile`, `.github/workflows/ci.yml`, `prompts/`, `scripts/init_env.py`, `scripts/run_step03_checks.sh`, `scripts/run_step03_mutations.sh`, `DECISIONS.md` | [logs/step-03](logs/step-03/README.md): all 45 checks OK at `174d6ae`; product owner's own run OK at `929a4ac` (45/45 checks, 12/12 mutants caught); CI green. Live model check done 29 Sep 2026: `claude-sonnet-5` and `claude-opus-5-5` confirmed, structured outputs on both ([log](logs/step-03/live-model-check-20260929T060000Z.log)) |
| 04 | [Project catalogue and identity resolution](steps/04-project-identity.md) | complete (approved 29 Sep 2026) | `da76682`, `ed57fdf`, `5cc63a6`: `backend/app/identity/`, `backend/app/api/routes_projects.py`, `routes_identity.py`, `idempotency.py`, `backend/app/decisions.py`, `seed/construction_status.json`, `evals/identity/v1/`, `prompts/a01_project_identity.1.0.md`, `contracts/v1/state_machines.json` and `journeys.json` (1.1.0), `scripts/run_step04_*.sh`, `scripts/set_env_secret.py`, `DECISIONS.md` | [logs/step-04](logs/step-04/README.md): 32/32 at `5cc63a6` (143 backend tests); product owner's run 32/32 and 16/16 mutants at `4606c3a`; CI green. Live A01 verified 29 Sep 2026 ([log](logs/step-04/live-a01-check-20260929T060000Z.log)). Carried forward: invalidation of findings and approvals joins at Steps 07–11 |
| 05 | [Text and social collection](steps/05-text-and-social-connectors.md) | complete (approved 1 Oct 2026: U–X; Y points 2–4; Y point 1 replaced by D46) | `6881ccd`, `bebbd76`, `0fa6640`, `5e0cfd6`, `aca3128`, `38716a0`: `backend/app/sources/` (policies, http, robots, quota, state, store, collection, lifecycle, recheck, verify), `backend/app/connectors/` (brave, web, youtube, registry), `backend/app/api/routes_runs.py`, `routes_sources.py`, `routes_policies.py`, `contracts/v1/` (operations 1.1.0, state machines 1.2.0, sources 1.1.0), `seed/source_policies.json`, `seed/connectors.json`, `scripts/run_step05_*.sh`, `DECISIONS.md` (D40–D44), `docs/02`, `docs/06` | [logs/step-05](logs/step-05/README.md): live runs for all five projects 30 Sep 2026; at `38716a0` (after D46) 29/29 checks (236 backend tests, `verify-collection` 13/13 on 1,010 records) and 25/25 mutants; CI green |
| 06 | [Videos, shorts and multilingual processing](steps/06-video-and-language-processing.md) | complete (approved 5 Oct 2026: Z1, Step 06; Z2 accepted 1 Oct; Z3 frames implemented as D49) | `fb5ce62` and follow-ups: `backend/app/media/` (windows, language, fetch, pipeline, translate, evaluation), `backend/app/api/routes_media.py`, `backend/Dockerfile.media`, `docker-compose.yml` (media-worker; MongoDB protected), `prompts/a04_language_context.1.0.md`, `prompts/a03_video_understanding.1.0.md`, `backend/app/media/frames.py`, `evals/media/v1/` (speech and frames), contracts (sources 1.4.0, common 1.1.0, agents 1.1.0, operations 1.2.0), `seed/source_policies.json` (spoken_video_content v3, youtube v3), `scripts/run_step06_*.sh`, `DECISIONS.md` (D47–D49, I17) | [logs/step-06](logs/step-06/README.md): 23/23 checks at `982028c` and by the product owner at `5028a5a`; 16/16 mutants; frames (Z3): 271 backend tests, A03 6/6 phrases and 3/3 renders; 1 Oct live attempts `network_refused` (I17); 2 Oct: 5 real videos (79 windows, 43 speech and 36 frame evidence); 5 Oct at `5578a70`: 24/24 checks, 26/26 mutants, 272 backend tests |
| 07 | [Evidence storage, deduplication and retrieval](steps/07-evidence-and-retrieval.md) | in_progress (keyword layer built and checked: 20/20 checks, 12/12 mutants at `a894ffc`; embedding search requested by the product owner on 5 Oct, being added) | `606762d`, `a894ffc`: `backend/app/evidence/` (similarity, clusters, eligibility, context, anchors, retrieval, lineage, verify, benchmark), `backend/app/identity/invalidation.py`, `backend/app/setup/database.py` (5 collections), scheduler and worker (`cluster_origins`), contracts (api 1.2.0, operations 1.3.0), `evals/retrieval/v1/`, `backend/tests/test_evidence.py`, `scripts/run_step07_*.sh` | [logs/step-07](logs/step-07/README.md): 287 backend tests; 20/20 checks; 12/12 mutants; benchmark recall@10 0.9 (same language 1.0, cross-language 0.5, other word form 0.0), no wrong-project, withdrawn or anchor errors |
| 08 | [Agent development and master workflow](steps/08-agents-and-master-workflow.md) | not_started | — | — |
| 09 | [Moderator console](steps/09-cms-moderation.md) | not_started | — | — |
| 10 | [SEO/AEO content and quality controls](steps/10-seo-aeo-and-editorial-qa.md) | not_started | — | — |
| 11 | [Publication and public page](steps/11-publishing-and-recovery.md) | not_started | — | — |
| 12 | [Evaluation, security and capacity qualification](steps/12-evaluation-security-and-capacity.md) | not_started | — | — |
| 13 | [Operations, freshness and analytics](steps/13-operations-and-freshness.md) | not_started | — | — |
| 14 | [One complete five-project POC release](steps/14-single-release-and-handover.md) | not_started | — | — |

Allowed status values: not_started, in_progress, blocked, complete. Completion requires the step's stated deliverables and checks. If code works with fixtures but a mandatory live integration is pending, record both facts and leave the applicable gate blocked.

## Current handoff

- Active step: 07 (evidence storage, deduplication and retrieval). The keyword layer is built and checked (20/20, 12/12 at `a894ffc`). The product owner asked on 5 Oct 2026 for embedding search as well (local `bge-m3`), which is being added. Step 06 is complete (approved 5 Oct 2026).
- **I17:** on 1 Oct 2026 the office firewall blocked youtube.com (confirmed by the product owner). On 2 Oct YouTube was reachable, and 5 real project videos were processed (captions, audio, frames). The TLS handshake is reset by name, while DNS, googleapis.com and google.com work. Videos tried end metadata-only with `network_refused`; nothing works around it. The YouTube Data API (discovery) still works. The product owner will test the end-to-end flow later from another network.
- Proven:
  - real Whisper `large-v3-turbo` in the media worker on the synthetic speech set: 20/22 key facts;
  - real A04 on its sentences: 5/5 kept, 12/12 facts;
  - real A03 on three synthetic frames: 6/6 phrases read verbatim, 3/3 graphics recognised;
  - the whole pipeline with fakes.
- Next action: add embedding search (bge-m3, local) with a hybrid ranker, measure it on the benchmark, re-run the Step 07 checks. The product owner raises Docker Desktop to 6 GB (I18), after which the stack is brought back up and the VM size recorded.
- Step 06 input from the product owner's earlier project (youtube-learning-copilot, reviewed 30 Sep 2026):
  - adapt the fallback order, video-ID parsing, ffmpeg 16 kHz mono and loading Whisper once;
  - do not reuse its cookie and proxy workarounds (D33) or its OpenAI and Ollama calls;
  - avoid its ASCII-only tokenizer, which deletes Hindi text;
  - the repository has no licence, so reimplement rather than copy.
- Waiting for the Step 09 console:
  - links in `needs_review`;
  - 3 alias proposals from A01 (D17).
- Refresh scheduling of collection and re-checks arrives at Step 13. Until then use `make collect` and `make recheck` by hand.
- Collection tools and competitor portals: D33 and D34, with D40 replacing Crawl4AI and D46 for robots.txt (recorded, not enforced). 99acres and Housing.com refuse the pages themselves (403, 406), which is not worked around, so they stay unread. MagicBricks, NoBroker, Houseiy and HomznSpace pages are read.
- Local stack: `make up`, then `make seed`; sign in as `deepesh.gupta@client-site.example`. The password is only in the local `.env` (`SEED_USER_PASSWORD`, git-ignored). `APP_MODE` is `fixture`: it controls only the session secret and the API docs page. Fixture data never enters `sy_poc`; tests and smoke checks use their own databases.
- Running services: MongoDB 8.0 replica set `rs0` (protected from the kernel's out-of-memory killer), API :8000, worker (`WORKER_ROLE=general`: `collect`, `check_availability`, `erase_payloads`, `invalidate_dependencies`), media-worker (`WORKER_ROLE=media`: `process_media`; 2 GB, killed first under memory pressure), scheduler and web :3000, all on 127.0.0.1. The Docker VM has 4 GB, shared with the product owner's other stacks.
- D21: the product owner will build the review-posting agent outside this repository; nothing here supports it. The agreed review form is D28.
- Deferred inputs, asked at the step that needs them: moderator capacity I11 (Step 09), correction owner I10 (before Step 11), demo machine I12 (Step 13).
- Repository: https://github.com/deepeshgupta12/agentic_ai_review_model (private), all work on `main` (D18). CI runs contracts, backend, web and Compose jobs on every push.
- Credentials (names only), all in `.env`, never `.env.example`; the pre-commit hook guards this:
  - live: ANTHROPIC_API_KEY (workspace-scoped), BRAVE_SEARCH_API_KEY, YOUTUBE_API_KEY;
  - not configured: Firecrawl, Reddit, X, Meta, listening provider.
- Not in this repository's commits: `AGENTS.md` has an uncommitted local vexp section, and `.codex/` and `.github/copilot-instructions.md` are untracked. They were added by another tool, so they are left out of the Step 05 commits for the product owner to keep or discard.
- Tooling: backend `cd backend && uv run …` (unset any `VIRTUAL_ENV`); web `cd web && pnpm …`; contract checks in `.venv`. `make help` lists everything.

## Session log

```text
Date / tool / branch / commit: 2026-09-25 / Claude Code (VS Code) / main / e197ab9 → f0932cb
Step and scope completed: GitHub repo created; Step 01 (01.1–01.6) built and checked; awaiting approval
Files changed: .gitignore; seed/connectors.json, seed/source_policies.json, seed/operating_defaults.json;
  scripts/validate_inputs.py, scripts/tests/test_validate_inputs.py, scripts/run_step01_checks.sh;
  evals/step-01-evaluation-brief.md; DECISIONS.md; PROGRESS.md; logs/step-01/
Decisions made, with DECISIONS.md IDs: D18 confirmed (repo and approval workflow); D19, D20 proposed;
  input statuses I02–I14 updated; connector registry and acceptance definitions added
Checks actually run and results: run_step01_checks.sh at f0932cb: 56/56 tests pass; validator PASS
  (1 expected warning: 'parq' is a single word); N1–N5 fail as expected; no .env/.DS_Store tracked;
  repo PRIVATE on main. Mutation check: 6 rules disabled one at a time, each caught by its tests.
  The validator also caught one data error during the build (haryanarera.gov.in missing from the web
  route's excluded hosts), fixed before commit.
Live integrations verified (credential present + real query result): none; no credentials configured
Fixture-only behavior still awaiting live validation: none in this step (no source is called)
Known defects / missing inputs / owner: approvals A–E and open inputs above (product owner);
  spec issues listed above (implementer, Step 02)
Remaining acceptance checks: product-owner approval of A–E
Next executable action: product owner reviews logs/step-01/README.md and approves or amends A–E
```

```text
Date / tool / branch / commit: 2026-09-25 / Claude Code (VS Code) / main / 682d555 → 90a8c8b
Step and scope completed: Step 01 closed after product-owner approval of A–E
Files changed: seed/operating_defaults.json, seed/source_policies.json, seed/connectors.json (approvals);
  scripts/validate_inputs.py (accepted policies need an approver), scripts/tests/test_validate_inputs.py
  (+1 test; one test updated because output_locale is now genuinely accepted), scripts/run_step01_checks.sh;
  DECISIONS.md; logs/step-01/README.md; PROGRESS.md
Decisions made, with DECISIONS.md IDs: I04, I06, I07, I08, I11 accepted; I10 SLA and I14 noindex accepted;
  D19 accepted; D21 recorded (user-persona review-posting agent requested, not implemented)
Checks actually run and results: run_step01_checks.sh at 90a8c8b: 57/57 tests pass; validator PASS
  (expected 'parq' warning); N1–N5 fail as expected; hygiene OK
Live integrations verified (credential present + real query result): none
Fixture-only behavior still awaiting live validation: none in this step
Known defects / missing inputs / owner: deferred inputs listed above (product owner); D21 open with
  stakeholders; spec issues listed above (implementer, Step 02)
Remaining acceptance checks: none for Step 01
Next executable action: confirm the D21 alternative question, then start Step 02
```

```text
Date / tool / branch / commit: 2026-09-25 → 2026-09-28 (paused 25 Sep, resumed 28 Sep) / Claude Code (VS Code) / main / f712a54 → 57c8e3e
Step and scope completed: Step 02 (02.1–02.7) built and checked; awaiting approval
Files changed: contracts/v1/ (9 schemas, routes.json, openapi.json, state_machines.json, journeys.json,
  README.md, fixtures/); docs/09, docs/10 (generated); docs/02, 03, 04, 05; README.md; steps/04, 05;
  scripts/contract_tools.py, check_contracts.py, build_openapi.py, build_fixtures.py, jcs_check.mjs,
  requirements.txt, run_step02_checks.sh, run_step01_checks.sh (runs only its own tests);
  scripts/tests/test_contracts.py; DECISIONS.md; CHANGELOG.md; PROGRESS.md; logs/step-02/
Decisions made, with DECISIONS.md IDs: D22–D26 proposed; D10 notes on Opus 5.5/Haiku to verify at Step 03;
  D21 updated (product owner builds that agent outside this repository); I13 done, I15 proposed
Checks actually run and results: run_step02_checks.sh at 57c8e3e: Step 01 regression OK; 110/110 tests;
  checker 12/12 sections; OpenAPI and fixtures current; Node v25.9.0 agrees on 15 hash/offset checks;
  N1–N6 fail as expected; hygiene OK. Mutation check: six rules disabled one at a time, each caught
  (first float mutation was equivalent; rerun recorded).
  During the build the checks found and I fixed: pointer schemas that rejected their own fields; verified
  unpublish needing a hash; a missing changes_requested content state; system actor for unpublish;
  PolicyFamily pattern rejecting the approved family 'x'; a placeholder op reference in docs/09;
  a test that could not follow the recursive JSON-LD schema.
Live integrations verified (credential present + real query result): none; no credentials configured
Fixture-only behavior still awaiting live validation: none in this step (no service is called)
Known defects / missing inputs / owner: approvals F–K (product owner); seeded users and roles I09 before Step 03
Remaining acceptance checks: product-owner approval of F–K
Next executable action: product owner reviews logs/step-02/README.md and approves or amends F–K
```

```text
Date / tool / branch / commit: 2026-09-28 / Claude Code (VS Code) / main / bec6225 → 88685f6
Step and scope completed: Step 02 closed. F–K approved; D27 and D28 added at the product owner's request
Files changed: contracts/v1 (common, catalogue, evidence, content, agents, api schemas; routes.json; state_machines.json;
  journeys.json J18–J19; new content_rules.json; regenerated openapi.json and fixtures); docs/02, 04, 06, 08, 09, 10;
  MASTER.md; steps/08; evals brief; seed/source_policies.json (web and YouTube v2), seed/operating_defaults.json
  (show_review_source_links off); scripts/contract_tools.py, check_contracts.py, build_fixtures.py, validate_inputs.py,
  run_step02_checks.sh; tests; DECISIONS.md; CHANGELOG.md; logs/step-02/
Decisions made, with DECISIONS.md IDs: D22–D26, I13, I15 accepted; D27, D28 added; D15, D21, I06 updated; I16 opened
Checks actually run and results: product owner's run at bec6225 all OK; run_step02_checks.sh at 88685f6 all OK
  (59 Step 01 tests, 127/127 tests, checker 13/13, N1–N6 as expected); D27/D28 mutation check: six rules, each caught
Live integrations verified (credential present + real query result): none; no credentials configured
Fixture-only behavior still awaiting live validation: none in this step
Known defects / missing inputs / owner: I09 seeded users and roles (product owner, before Step 03); I16 per-phase status
  (Step 04); I05 transcript route decides when spoken video reviews start (Step 06)
Remaining acceptance checks: none for Step 02
Next executable action: collect I09, then start Step 03
```

```text
Date / tool / branch / commit: 2026-09-28 / Claude Code (VS Code) / main / 7260b46 → 38be1be
Step and scope completed: Step 03 (03.1–03.9) built and checked; awaiting approval of L–O
Files changed: backend/ (app: config, observability, ids, db, errors, contracts, setup, auth, audit, api, jobs, workers,
  scheduler, agents/gateway, seed, cli; tests; pyproject.toml, uv.lock, Dockerfile); web/ (Next.js console shell,
  public page, proxy, API clients, generated types, Vitest, Dockerfile); docker-compose.yml; .env.example;
  .dockerignore; Makefile; .github/workflows/ci.yml; prompts/README.md; scripts/init_env.py,
  run_step03_checks.sh, run_step03_mutations.sh; seed/connectors.json (anthropic demonstration text);
  DECISIONS.md; README.md; CHANGELOG.md; docs/02, docs/03; steps/03; logs/step-03/
Decisions made, with DECISIONS.md IDs: I09 accepted (sole coordinator, all roles); D29–D32 proposed; version matrix
  added; I02 and the anthropic registry row updated
Checks actually run and results: run_step03_checks.sh at 38be1be: 45/45 OK (Step 01-02 regression; ruff, mypy and
  83 backend tests against the Compose replica set; eslint, TypeScript, API types, 13 Vitest tests, production
  build; stack healthy, rs0 primary; setup and seeding repeat with no changes; sign-in, CSRF, rate limit and
  logout through the web app; a job claimed before a real worker restart is recovered and the stale token
  refused; N1–N3 fail as expected; secret values absent from commits, service logs and logs/; ports on
  127.0.0.1). Mutation check at 38be1be: 12 rules disabled one at a time, each caught by its own test.
  GitHub Actions green on 54d3954 and 38be1be.
  The checks found and I fixed: an N2 check that passed for the wrong reason; settings errors echoing
  configured values (now hidden); a mutation harness importing the wrong copy; a user-seeding check that
  assumed an existing coordinator; route types missing from a clean typecheck (now `next typegen` first).
Live integrations verified (credential present + real query result): none; no credentials configured
Fixture-only behavior still awaiting live validation: the Claude smoke call and model-ID check (I02)
Known defects / missing inputs / owner: approvals L–O (product owner); Anthropic key I02 (product owner);
  I01 alternate names and I16 per-phase status before Step 04 (product owner)
Remaining acceptance checks: product-owner approval of L–O; live smoke call once the key exists
Next executable action: product owner runs the Step 03 checks and approves or amends L–O
```

```text
Date / tool / branch / commit: 2026-09-28 / Claude Code (VS Code) / main / 929a4ac → (this commit)
Step and scope completed: Step 03 closed after product-owner approval of L–O
Files changed: DECISIONS.md (D29–D32 accepted); logs/step-03/ (README results and approvals; the product owner's
  check and mutation logs); web/vitest.config.ts renamed to vitest.config.mts; PROGRESS.md
Decisions made, with DECISIONS.md IDs: D29, D30, D31, D32 accepted (items L, M, N, O)
Checks actually run and results: product owner at 929a4ac: run_step03_checks.sh 45/45 OK, run_step03_mutations.sh
  12/12 caught; console tried in the browser and working. After the rename: 13/13 Vitest tests with no
  CommonJS warning; eslint and TypeScript clean
Live integrations verified (credential present + real query result): none; no credentials configured
Fixture-only behavior still awaiting live validation: the Claude smoke call and model-ID check (I02)
Known defects / missing inputs / owner: I01 alternate names and I16 per-phase status (product owner, now);
  Anthropic key I02 (product owner)
Remaining acceptance checks: none for Step 03 beyond the live smoke call, which waits for the key
Next executable action: collect I01 and I16, then start Step 04
```

```text
Date / tool / branch / commit: 2026-09-28 → 2026-09-29 / Claude Code (VS Code) / main / eb8edde → ed57fdf
Step and scope completed: Step 04 (04.1–04.8) built and checked; awaiting approval of P–T. Also recorded D33/D34
  (collection tools, competitor portals; I05 settled) and I01/I16 (alternate names by A01; phase statuses)
Files changed: backend/app/identity/ (rules, text, catalogue, matching, intake, evidence, links, aliases, agent,
  queries, invalidation, service, policies, evaluation); backend/app/api/routes_projects.py, routes_identity.py,
  idempotency.py, deps.py, main.py; backend/app/decisions.py; backend/app/setup/database.py (8 collections);
  backend/app/seed/projects.py (shared import, status seeding); backend/app/cli.py (match-text, plan-queries,
  eval-identity, fixture-smoke-identity); backend/app/jobs/queue.py (enqueue in a transaction); worker registers
  invalidate_dependencies; backend/Dockerfile (prompts, evals); 7 new test files; contracts/v1 state machines and
  journeys 1.1.0; docs/02, 04, 10; seed/construction_status.json; evals/identity/v1; prompts/a01_project_identity.1.0.md;
  scripts/run_step04_checks.sh, run_step04_mutations.sh, run_step03_checks.sh (seed output shape); Makefile; CI;
  README; CHANGELOG; DECISIONS.md; logs/step-04/
Decisions made, with DECISIONS.md IDs: D33, D34 accepted (tools; competitor portals, risk accepted by the product
  owner; account sign-in, bot-protection bypass and robots-disallowed paths declined); I01, I05, I16 settled;
  D35–D39 proposed
Checks actually run and results: run_step04_checks.sh at ed57fdf: 32/32 OK (regression; 142 backend tests; web
  gates; setup and seeding idempotent incl. 7 status records; catalogue/config APIs through the web app; five query
  plans; three real-catalogue dry runs; fixture smoke on a scratch database with the real worker; evaluation;
  N1–N6; hygiene incl. no fixture data in the real catalogue). Mutation check at da76682: 16/16 caught after two
  weak tests found by its first run were strengthened. CI green on da76682 incl. identity smoke in containers.
  Web research for I16 (M3M Antalya Hills phases) with sources recorded in seed/construction_status.json.
Live integrations verified (credential present + real query result): none; no credentials configured
Fixture-only behavior still awaiting live validation: A01 (fake client only); identity evaluation is synthetic (D39)
Known defects / missing inputs / owner: approvals P–T (product owner); Antalya Phase II status (product owner);
  Anthropic key I02 (product owner); findings/approval invalidation completes at Steps 07–11 (implementer)
Remaining acceptance checks: approval of P–T; the invalidation of findings and approvals once they exist
Next executable action: product owner runs the Step 04 checks and approves or amends P–T
```

```text
Date / tool / branch / commit: 2026-09-29 / Claude Code (VS Code) / main / 4606c3a → 5cc63a6
Step and scope completed: Step 04 closed after product-owner approval of P–T; I16 closed (Antalya Phase II ready)
Files changed: DECISIONS.md (D35–D39 accepted; I16); seed/construction_status.json (8 records); backend/app/cli.py
  (fixture-smoke-identity --live-a01); tests (Phase II, live option); scripts/run_step04_checks.sh (8 records);
  scripts/set_env_secret.py and `make set-secret`; logs/step-04/ (product owner's runs; closing run); PROGRESS.md
Decisions made, with DECISIONS.md IDs: D35, D36, D37, D38, D39 accepted (items P, Q, R, S, T); I16 settled
Checks actually run and results: product owner at 4606c3a: run_step04_checks.sh 32/32, run_step04_mutations.sh
  16/16. Implementer at 5cc63a6: run_step04_checks.sh 32/32 (143 backend tests; Phase II ready in the config);
  set_env_secret.py refuses unknown names and non-terminal input without touching .env
Live integrations verified (credential present + real query result): none yet; the product owner has the Anthropic
  key and will store it with `make set-secret`
Fixture-only behavior still awaiting live validation: smoke-model real call and model-ID check; live A01
Known defects / missing inputs / owner: Anthropic key in .env (product owner); Brave and YouTube keys for Step 05 (I03)
Remaining acceptance checks: Step 03 live smoke call (key); Step 04 invalidation of findings/approvals (Steps 07–11)
Next executable action: product owner runs `make set-secret NAME=ANTHROPIC_API_KEY` and `make up`
```

```text
Date / tool / branch / commit: 2026-09-29 / Claude Code (VS Code) / main / ed0f13f → (this commit)
Step and scope completed: Anthropic key live (Step 03 live smoke; Step 04 live A01); secret guard
Files changed: scripts/check_no_secrets.py, Makefile (`make hooks`, pre-commit hook installed locally), CI (.env.example check);
  backend: optional ANTHROPIC_WORKSPACE_ID (anthropic-workspace-id header), bad_request status in the model check;
  seed/connectors.json (anthropic live); scripts/validate_inputs.py (live needs an existing evidence file) and its tests;
  backend/tests/test_auth_api.py and run_step03_checks.sh (connector statuses follow the registry); DECISIONS (D10 verified,
  I02 done, registry row, matrix); logs/step-03 and step-04 live logs and READMEs; PROGRESS.md
Decisions made, with DECISIONS.md IDs: D10 verified on the account; I02 done
Checks actually run and results: the product owner pasted keys into .env.example as well as .env; found before any commit
  (origin and HEAD had empty values), restored, and a pre-commit guard added and tested. First key was organisation-level:
  400 "not scoped to a workspace"; the product owner replaced it with a workspace-scoped key and deleted the old one.
  make smoke-model: 3 roles available, structured call completed (claude-sonnet-5, req_011CfXEZY6AQiDxY1oSagZyt,
  1,102/61 tokens, abstained on no evidence). Opus 5.5 structured call completed (req_011CfXEe5LimvvW1x4j5MmQh).
  fixture-smoke-identity --live-a01: 9/9 (A01 3,515/1,178 tokens; suggestion recorded, link stayed in review; alias
  'QR Lakeside' proposed through the backend check). Regression: 128 Step 01–02 tests OK; checker 13/13
Live integrations verified (credential present + real query result): anthropic (live, 29 Sep 2026)
Fixture-only behavior still awaiting live validation: source connectors (Step 05)
Known defects / missing inputs / owner: none blocking Step 05; YOUTUBE_API_KEY added by the product owner the same day
Remaining acceptance checks: Step 04 invalidation of findings/approvals joins at Steps 07–11
Next executable action: start Step 05
```

```text
Date / tool / branch / commit: 2026-09-29 to 2026-10-01 / Claude Code (VS Code) / main / 32ed8a6 → aca3128
Step and scope completed: Step 05 built and live: source policies, safe fetching, Brave, web reader, YouTube, runs,
  lifecycle and re-checks, run/source APIs; live runs for the five projects; awaiting approval of U–Y
Files changed: backend/app/sources/ (policies, http, robots, quota, state, store, collection, lifecycle, recheck,
  verify), backend/app/connectors/ (base, brave, web, youtube, registry), backend/app/api/routes_runs.py,
  routes_sources.py, routes_policies.py, routes_ops.py (health), cli.py (collect, recheck-sources,
  verify-collection, discover-hosts, seed-policies), seed/projects.py (new connectors join configs), worker and
  scheduler; contracts/v1 operations 1.1.0 (job kind check_availability), state machines 1.2.0 (older revisions)
  and sources 1.1.0 (rule-rejected links need no decision); fixtures; web/lib/api-schema.d.ts; seed/source_policies.json (web v4), seed/connectors.json (three live);
  tests (+84, 231 in total; conftest hides real credentials); scripts/run_step05_checks.sh, run_step05_mutations.sh,
  scripts/tests (registry tests order-independent); Makefile; DECISIONS (D40–D45, I03, registry, matrix);
  docs/02, docs/06, docs/10 (generated); CHANGELOG; logs/step-05/
Decisions made, with DECISIONS.md IDs: D41 accepted (29 Sep 2026); D40, D42, D43, D44, D45 proposed (items U–Y)
Checks actually run and results: live collection for all five projects (logs/step-05/live-collect-*.log);
  4 re-check passes, 799 checks; verify-collection 13/13 on 905 stored records. One full backend run had a
  fixture error in test_lifecycle (setup or teardown, details not captured); the test file alone and a full
  rerun with error reporting (230 passed) did not reproduce it, so watch for a recurrence. Backend suite, lint, mypy,
  web gates, Step 01–02 suites and the contract checker. run_step05_checks.sh at 5e0cfd6 gave 27/29: the
  source-detail contract failed on a rule-rejected link, and health showed no web reader success. Both were
  fixed (sources 1.1.0, D45). At aca3128: run_step05_checks.sh 29/29 (231 backend tests) and
  run_step05_mutations.sh 23/23; CI green
Live integrations verified (credential present + real query result): brave_search, web_fetch, youtube_data_api
  (live 30 Sep 2026, logs/step-05/live-connectors-20260930T110436Z.log); anthropic used live for 45 A01 calls
Fixture-only behavior still awaiting live validation: none for Step 05's connectors; video transcripts are Step 06
Known defects / missing inputs / owner: 99acres, Housing.com, MagicBricks and 11 other sites refuse our crawler
  (unread, D45); comments on generic web pages are not split per author; some homepages carry a markup date that
  may be a modification date; links in review and 3 alias proposals wait for the Step 09 console (product owner)
Remaining acceptance checks: product owner's runs of both Step 05 scripts and approval of U–Y
Next executable action: product owner runs `bash scripts/run_step05_checks.sh` and
  `bash scripts/run_step05_mutations.sh`, then approves or amends U–Y
```

```text
Date / tool / branch / commit: 2026-10-01 / Claude Code (VS Code) / main / 6b7a4a3 → 38716a0
Step and scope completed: Step 05 closed. The product owner approved U–X and Y points 2–4, and declined Y point 1:
  "we can bypass robots.txt" (D46)
Files changed: contracts (sources 1.2.0 and api 1.1.0: SourcePolicy.robots_txt), fixtures, web/lib/api-schema.d.ts;
  backend: policies (robots_txt, obeys_robots), web reader (robots.txt blocks only under obey), robots.py notes,
  config (user agent no longer claims to respect robots.txt), verify (robots rules apply where the policy obeys),
  store/collection (a source a person withdrew is never collected again); tests (+5, 236 in total);
  seed/source_policies.json (web_public_pages v5, competitor_portals v2, official_records v2: record_only);
  scripts/run_step05_*.sh (2 new mutants, 25 in total); DECISIONS (U–X accepted, D45 points, D46, D33 note);
  AGENTS.md rule line (only that line committed); docs/06 rule 2; logs/step-05
Decisions made, with DECISIONS.md IDs: D40, D42, D43, D44 accepted; D45 points 2–4 accepted, point 1 replaced by D46
Checks actually run and results: backend 236 passed; contracts 13/13; Step 01–02 suites OK. Live run under D46:
  5 runs, 70 new pages (57 MagicBricks; 3 on robots-disallowed paths); 30 refused pages not worked around;
  verify-collection 13/13 on 1,010 records. The product owner's own runs at 06:40 and 06:46 were disrupted by
  concurrent edits in the same folder (recorded as not valid)
Live integrations verified (credential present + real query result): unchanged (anthropic, brave_search, web_fetch,
  youtube_data_api)
Fixture-only behavior still awaiting live validation: none for Step 05
Known defects / missing inputs / owner: 99acres and Housing.com refuse their pages (not worked around); generic
  web comments are not split per author; markup dates on some homepages may be modification dates
Remaining acceptance checks: none for Step 05. At 38716a0: run_step05_checks.sh 29/29, run_step05_mutations.sh
  25/25. The product owner re-runs both scripts at that commit
Next executable action: Step 06 in a separate worktree
```

```text
Date / tool / branch / commit: 2026-10-01 / Claude Code (VS Code) / step-06 worktree, pushed to main / bba19cd → fb5ce62 and follow-ups
Step and scope completed: Step 06 built: spoken-content policy v2, transcript routes, windows, speech evidence and
  matching, language flags, A04 translation with backend checks, media library API, media worker, speech set
Files changed: backend/app/media/ (new), routes_media.py, identity (identify_media, create_media_evidence,
  window inheritance cascade), lifecycle (transcript erasure), verify (transcript rules), worker (roles), jobs
  (process_media), config, setup (ai_media_segments), cli (transcribe-videos, eval-media, eval-language);
  backend/Dockerfile.media, pyproject + uv.lock (group media), docker-compose.yml (media-worker, oom_score_adj);
  contracts (sources 1.3.0, operations 1.2.0), fixtures, web types; seed (spoken_video_content v2, youtube v3,
  spoken_video_transcripts connector); prompts/a04_language_context.1.0.md; evals/media/v1; tests (test_media.py,
  policy/seed test updates); scripts/run_step06_*.sh; Makefile; DECISIONS (D47–D49, I17, registry, matrix);
  docs/02, docs/06; CHANGELOG; logs/step-06
Decisions made, with DECISIONS.md IDs: D47, D48, D49 proposed (Z1–Z3); I17 opened
Checks actually run and results: run_step06_checks.sh 23/23 at 982028c (258 backend tests), run_step06_mutations.sh
  16/16; details in logs/step-06/README.md. During the work: the speech set with small
  (13/22 facts) and large-v3-turbo (19/22 natively, 20/22 in the media worker); live A04 (first run found a false
  Hindi negation, "कीमत"; fixed; then 5/5 kept, 12/12 facts)
Incident: at 08:23 UTC a 3 GB model test container in the 4 GB Docker VM got MongoDB killed for lack of memory
  (exit 137, OOMKilled). Restarted at once with no data lost (1,010 sources, 731 links, 368 evidence, 11 runs);
  the API and worker reconnected. Safeguards: media worker capped at 2 GB and killed first; MongoDB protected (D48)
Live integrations verified (credential present + real query result): A04 on Claude (live); youtube.com captions
  and audio blocked by the network (I17)
Fixture-only behavior still awaiting live validation: caption and audio acquisition for real project videos
Known defects / missing inputs / owner: I17 (product owner); transcription in Docker runs at about 3–11x real time
Remaining acceptance checks: live media analysis on a permitted real sample (I17); approval of Z1–Z3
Next executable action: product owner answers I17 and decides Z1–Z3
```

```text
Date / tool / branch / commit: 2026-10-01..02 / Claude Code (VS Code) / step-07 worktree, then main / 606762d → (this commit)
Step and scope completed: Step 06 amendment Z3, frames and on-screen text (Step 06.5), as the product owner directed
  ("Z3 - Not Ok, it needs to be implemented"); D48 accepted (Z2); I17 reclassified (office firewall; test later)
Files changed: backend/app/media/ (frames.py new: A03 runner; fetch.py: one YtDlpMedia download, sample_frames,
  transcriber converts its own audio; pipeline.py: speech plus frames, store_frame_segments, skip audit, fallbacks;
  language.py: frame_flags; evaluation.py: evaluate_frames); agents/gateway.py (image content blocks); identity/
  (evidence modality per segment; inherited frame links return to review); sources/verify.py (frame rule; all media
  modalities); config.py (MEDIA_FRAMES_*); cli.py (eval-frames; frame counts); prompts/a03_video_understanding.1.0.md;
  contracts (common 1.1.0, agents 1.1.0, sources 1.4.0) and fixtures; web types; seed (spoken_video_content v3);
  evals/media/v1/frames; tests/test_media.py (UC-46b, 8 tests); scripts/run_step06_*.sh; Makefile; DECISIONS
  (D48, D49, I17); docs/04, docs/06; CHANGELOG; logs/step-06 (the owner's 23/23 and 16/16 runs recorded)
Decisions made, with DECISIONS.md IDs: D49 rewritten as implemented (Z3); D48 accepted; I17 updated
Checks actually run and results: backend suite 271 passed; ruff and mypy clean; contracts 13/13; web gates OK;
  live A03 on the synthetic frames 6/6 phrases, 3/3 graphics (claude-sonnet-5, 3,053/311 tokens);
  run_step06_checks.sh and run_step06_mutations.sh after this commit: see logs/step-06/README.md
Live integrations verified (credential present + real query result): A03 vision on Claude (synthetic frames only)
Fixture-only behavior still awaiting live validation: captions, audio and frames of real project videos (I17)
Known defects / missing inputs / owner: I17 (office firewall; product owner tests from another network)
Remaining acceptance checks: Step 06 live gate; Z1 approval; Step 07 deliverables
Next executable action: continue Step 07
```

```text
Date / tool / branch / commit: 2026-10-02 / Claude Code (VS Code) / step-07 worktree, then main / 9a167f4 → (this commit)
Step and scope completed: the Step 06 check run at 9a167f4 reached YouTube; fixes for what the first real videos showed
Files changed: backend/app/media/ (frames.py: output cap 8,192, phone numbers replaced; pipeline.py: on-screen text
  tagged by its own script; evaluation.py: frames_record, dataset fields per contract); cli.py; tests/test_media.py
  (phone and language assertions; frame-check record test); docker-compose.yml (MongoDB cache 0.25 GB; media worker
  restart on failure); scripts/run_step06_checks.sh (exit code of a killed speech check; restart policy checked);
  DECISIONS (D48 amended, D49 results, I17, I18 new); CHANGELOG; logs/step-06
Decisions made, with DECISIONS.md IDs: D48 amended (implementer); I18 opened for the product owner
Checks actually run and results: run_step06_checks.sh at 9a167f4 22/24 (log checks-20261002T073247Z.log): the speech
  check was killed when the Docker VM ran out of memory, and the frame check's record failed the contract; both fixed.
  Speech check alone afterwards: 20/22 facts. tests/test_media.py 31 passed
Live integrations verified (credential present + real query result): youtube.com captions, audio download and A03 on
  real frames (2 Oct 2026, 5 videos); A04 5/5 again
Fixture-only behavior still awaiting live validation: none for the video route; the fixes need a clean check run
Known defects / missing inputs / owner: I18 (Docker VM memory, product owner); Z1 approval
Remaining acceptance checks: a clean run_step06_checks.sh and run_step06_mutations.sh after this commit
Next executable action: run both Step 06 scripts, record them, push; continue Step 07
```

```text
Date / tool / branch / commit: 2026-10-05 / Claude Code (VS Code) / main / 5578a70
Step and scope completed: Step 06 re-checked after the fixes
Checks actually run and results: run_step06_checks.sh ALL CHECKS OK 24/24 (272 backend tests; speech 20/22; A04 5/5;
  A03 frame check 6/6 and 3/3; verify-collection on the 2 Oct real videos); run_step06_mutations.sh 26/26
Live integrations verified (credential present + real query result): YouTube refused again on 5 Oct (5 attempts
  network_refused, I17); the 2 Oct fixes for real frames are tested with fakes only
Known defects / missing inputs / owner: I17 (network), I18 (Docker VM memory), Z1 (product owner)
Next executable action: product owner approves Z1 and Step 06; continue Step 07
```

```text
Date / tool / branch / commit: 2026-10-05 / Claude Code (VS Code) / step-07 worktree, then main / a894ffc
Step and scope completed: Step 07 keyword layer checked; Step 06 approved by the product owner (Z1 and the step)
Checks actually run and results: run_step07_checks.sh ALL CHECKS OK 20/20 (287 backend tests; scheduled clustering on
  437 real evidence spans, 3 joined origins, stable repeat; context added to 110 older spans once; verify-evidence 8/8,
  re-run with the search index filled: 437 entries, 0 broken; retrieval on the five projects' real evidence: 35
  searches, p50 18 ms, p95 270 ms, 0 results from another project or ineligible; benchmark recall@10 0.9, 0 wrong-project,
  0 withdrawn, 0 anchor errors); run_step07_mutations.sh 12/12
Decisions made, with DECISIONS.md IDs: D47 accepted (Z1); I18 decided (6 GB); embedding search requested (D50 to be
  amended when built)
Next executable action: embedding search with bge-m3; product owner applies 6 GB in Docker Desktop
```

## Session entry template

```text
Date / tool / branch / commit:
Step and scope completed:
Files changed:
Decisions made, with DECISIONS.md IDs:
Checks actually run and results:
Live integrations verified (credential present + real query result):
Fixture-only behavior still awaiting live validation:
Known defects / missing inputs / owner:
Remaining acceptance checks:
Next executable action:
```

## Release gate ledger

Copy the gates from [validation and release](docs/07-validation-and-release.md) when measurement begins. Record target, observed result, dataset/commit/environment, evidence path, owner and pass/fail/blocked. No gate has passed merely because these Markdown files exist.
