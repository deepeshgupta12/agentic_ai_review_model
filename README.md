# the client: coding handoff (v1.1)

Prepared 25 September 2026. This is a build specification, not an implemented application. All development steps are initially **not started**. Deliver one complete release for five real projects as a **standalone POC**: own MongoDB, own project catalogue, own moderator console, own public project page, Claude API as the model provider. See [CHANGELOG.md](CHANGELOG.md) for what changed from v1.0.

Start with [MASTER.md](MASTER.md). It defines scope, architecture, reading order, implementation rules and release gates. Then use the 14 numbered files under `steps/`, one work package at a time. Each contains the original numbered requirements, implementation details, acceptance checks and a ready-to-use coding prompt.

## Repository setup

1. Create a new private GitHub repository and copy the contents of this directory to its root (keep the directory structure; links are relative).
2. Open it in VS Code (or Visual Studio) with Claude Code. Claude Code reads `CLAUDE.md`, which imports `AGENTS.md` ([memory guide](https://code.claude.com/docs/en/memory)).
3. Fill `contracts/five-project-input-template.json` with the five projects (name, alternate names, locality, city; micromarket optional).
4. Put the Anthropic API key in a local `.env` (never committed); Step 03 defines the placeholder `.env.example`.
5. Give Claude Code the bootstrap prompt in MASTER.md and work from the repository terminal so it can inspect, edit, run and verify.
6. Keep [PROGRESS.md](PROGRESS.md) and [DECISIONS.md](DECISIONS.md) current after each work package; they are the handoff between sessions.

Expected layout after Step 03: `backend/` (Python, FastAPI, LangGraph, PyMongo), `web/` (Next.js console + public page), `docker-compose.yml` (MongoDB single-node replica set, API, worker, web), `.github/workflows/` (CI), `evals/`, `prompts/`, `scripts/`.

## What is included

- Master execution guide, changelog and 14 implementation step files.
- Shared architecture, database, API, agent, publication, source-access, editorial and evaluation specifications.
- Instructions for Claude Code and Codex, a progress ledger and an input/decision register.
- Original full plan, preserved unchanged for reference (much of its "existing CMS/MongoDB" language is historical after v1.1).
- Original JSON exchange schema, synthetic example and five-project input template.

The original JSON schema is an illustrative exchange contract, not a complete production schema; [database and contracts](docs/02-database-and-contracts.md) lists the required extensions. No credentials, real project names or implemented code are included. A synthetic local demonstration is useful during construction but does not prove real source integration.
